"""Import specifier resolution for multiple languages.

Converts raw import statements (Python, JS/TS, Java, and a generic fallback)
into repo-relative path stems, honoring tsconfig path aliases and npm/yarn
workspace package exports for JavaScript-family projects.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_ts_paths(repo_root: str | Path) -> dict[str, str]:
    """Collect TypeScript/JavaScript path aliases from tsconfig/jsconfig files.

    Recursively finds ``tsconfig.json``/``jsconfig.json`` (excluding
    ``node_modules``) and flattens each ``compilerOptions.paths`` alias to its
    first target, resolved to a repo-relative directory prefix. Wildcard
    suffixes are stripped so aliases can be matched by prefix.

    Args:
        repo_root: Root directory of the cloned repository.

    Returns:
        Mapping of alias prefix (e.g. ``@/``) to repo-relative target prefix.
    """
    root = Path(repo_root)
    paths: dict[str, str] = {}

    for config_name in ("tsconfig.json", "jsconfig.json"):
        for config_file in root.rglob(config_name):
            if "node_modules" in config_file.parts:
                continue
            try:
                data = json.loads(config_file.read_text(errors="ignore"))
                compiler_options = data.get("compilerOptions", {})
                base_url = compiler_options.get("baseUrl", ".")
                raw_paths = compiler_options.get("paths", {})
                for alias, targets in raw_paths.items():
                    if targets:
                        abs_target = (
                            config_file.parent / base_url / targets[0].rstrip("*")
                        ).resolve()
                        try:
                            rel_target = str(
                                abs_target.relative_to(root.resolve())
                            ).replace("\\", "/")
                        except ValueError:
                            # Target resolves outside the repo (e.g. monorepo
                            # sibling); can't be matched against stored paths.
                            continue
                        # Strip wildcard so aliases match by prefix later.
                        paths[alias.rstrip("*")] = rel_target
            except Exception:
                pass

    return paths


def load_workspace_map(repo_root: str) -> dict[str, str]:
    """Build a map of workspace package names to their source directories.

    Scans all ``package.json`` files (excluding ``node_modules``) in monorepo
    workspaces and maps each package name — plus subpath export patterns — to
    the corresponding repo-relative source path. Prefers ``exports`` entries,
    falling back to ``main`` (with ``dist/`` rewritten to ``src/`` when
    present), then to the package directory itself.

    Args:
        repo_root: Root directory of the cloned repository.

    Returns:
        Mapping of package name or ``name/prefix`` key to repo-relative path.
    """
    root = Path(repo_root)
    workspace_map: dict[str, str] = {}

    for pkg_file in root.rglob("package.json"):
        if "node_modules" in pkg_file.parts:
            continue
        try:
            data = json.loads(pkg_file.read_text(errors="ignore"))
            name = data.get("name")
            if not name:
                continue

            pkg_dir = str(pkg_file.parent.relative_to(root)).replace("\\", "/")

            # Skip uninteresting root packages: no exports and no main means
            # nothing useful to map beyond the directory itself.
            if "/" not in name and not data.get("exports"):
                if pkg_dir == "." or not data.get("main"):
                    continue

            exports = data.get("exports", {})
            has_root_export = False

            if isinstance(exports, dict):
                for pattern, target in exports.items():
                    if isinstance(target, dict):
                        # Conditional exports: prefer runtime entry over types.
                        resolved = (
                            target.get("import")
                            or target.get("types")
                            or target.get("default")
                        )
                    elif isinstance(target, str):
                        resolved = target
                    else:
                        continue

                    if not resolved:
                        continue

                    clean_target = resolved.lstrip("./")

                    if pattern == ".":
                        # Root export: map both the package name and a
                        # `name/` prefix (to its source dir) so subpath imports
                        # like `pkg/utils` resolve into src/.
                        entry = clean_target.rsplit(".", 1)[0]
                        workspace_map[name] = f"{pkg_dir}/{entry}"
                        has_root_export = True
                        src_dir = str(Path(clean_target).parent)
                        if src_dir and src_dir != ".":
                            workspace_map[f"{name}/"] = f"{pkg_dir}/{src_dir}/"
                        else:
                            workspace_map[f"{name}/"] = f"{pkg_dir}/"
                    elif "*" in pattern:
                        pat_prefix = pattern.lstrip("./").split("*")[0]
                        tgt_prefix = clean_target.split("*")[0]
                        key = f"{name}/{pat_prefix}" if pat_prefix else f"{name}/"
                        workspace_map[key] = f"{pkg_dir}/{tgt_prefix}"
                    else:
                        clean_pattern = pattern.lstrip("./")
                        entry = clean_target.rsplit(".", 1)[0]
                        workspace_map[f"{name}/{clean_pattern}"] = f"{pkg_dir}/{entry}"

            if not has_root_export:
                main = data.get("main", "")
                if main:
                    entry = main.lstrip("./").rsplit(".", 1)[0]
                    # Published builds point at dist/, but we index src/.
                    src_entry = (
                        entry.replace("dist/", "src/", 1) if "dist/" in entry else entry
                    )
                    workspace_map[name] = f"{pkg_dir}/{src_entry}"
                    src_dir = str(Path(src_entry).parent)
                    if src_dir and src_dir != ".":
                        workspace_map[f"{name}/"] = f"{pkg_dir}/{src_dir}/"
                    else:
                        workspace_map[f"{name}/"] = f"{pkg_dir}/"
                else:
                    workspace_map[name] = pkg_dir

        except Exception:
            pass

    return workspace_map


def resolve_import(
    language: str,
    import_name: str,
    importing_file: str,
    repo_root: str,
    ts_paths: dict[str, str] | None = None,
    workspace_map: dict[str, str] | None = None,
) -> str | None:
    """Resolve an import specifier to a repo-relative path stem.

    Dispatches on the importing file's language: Python handles relative dots,
    JS/TS consults workspace maps and tsconfig aliases before relative paths,
    Java converts dotted class names to ``.java`` paths, and other languages
    use a generic heuristic resolver.

    Args:
        language: Language identifier of the importing file.
        import_name: Raw import specifier extracted by the parser.
        importing_file: Repo-relative path of the file containing the import.
        repo_root: Root directory of the cloned repository.
        ts_paths: Optional tsconfig alias map from :func:`load_ts_paths`.
        workspace_map: Optional workspace package map from
            :func:`load_workspace_map`.

    Returns:
        A repo-relative path stem (no extension), or None if the import cannot
        be resolved internally (e.g. bare module specifiers).
    """
    if not import_name or import_name in ("<anonymous>", ""):
        return None
    if language == "python":
        return _resolve_python_import(import_name, importing_file, repo_root)
    elif language in ("javascript", "typescript", "tsx", "jsx"):
        return _resolve_js_import(
            import_name, importing_file, repo_root, ts_paths, workspace_map
        )
    elif language == "java":
        return _resolve_java_import(import_name)
    else:
        return _resolve_generic_import(import_name, importing_file, repo_root)


def _resolve_python_import(
    import_name: str, importing_file: str, repo_root: str
) -> str | None:
    """Resolve a Python import specifier to a path stem."""
    if " as " in import_name:
        import_name = import_name.split(" as ")[0].strip()

    importing_dir = Path(importing_file).parent

    if import_name.startswith("."):
        return _resolve_python_relative(import_name, importing_dir, repo_root)

    return import_name.replace(".", "/")


def _resolve_python_relative(
    import_name: str, importing_dir: Path, repo_root: str
) -> str | None:
    """Resolve a Python relative import (leading dots) against the importing dir."""
    dots = len(import_name) - len(import_name.lstrip("."))
    remainder = import_name.lstrip(".")

    base = importing_dir
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        resolved = base / Path(remainder.replace(".", "/"))
    else:
        resolved = base

    return str(resolved).replace("\\", "/")


def _resolve_js_import(
    import_name: str,
    importing_file: str,
    repo_root: str,
    ts_paths: dict[str, str] | None,
    workspace_map: dict[str, str] | None,
) -> str | None:
    """Resolve a JS/TS import via workspace map, tsconfig alias, or relative path.

    Bare specifiers (non-``@``-scoped packages without a workspace mapping)
    return None since they refer to external dependencies.
    """
    if workspace_map:
        # Longest-prefix match picks the most specific workspace package
        # (e.g. @scope/pkg/utils over @scope/pkg).
        best_key = ""
        for pkg_name in workspace_map:
            if import_name == pkg_name or import_name.startswith(pkg_name):
                if len(pkg_name) > len(best_key):
                    best_key = pkg_name
        if best_key:
            remainder = import_name[len(best_key) :]
            return (workspace_map[best_key] + remainder).lstrip("/")

    if ts_paths:
        resolved = _resolve_ts_alias(import_name, ts_paths)
        if resolved:
            return resolved

    if import_name.startswith("@"):
        # Scoped packages are external unless a workspace mapping matched above.
        return None

    if not import_name.startswith("."):
        return None

    importing_dir = Path(importing_file).parent
    resolved_path = importing_dir / import_name

    parts = []
    for part in str(resolved_path).replace("\\", "/").split("/"):
        # Manual ../ normalization: popping on ".." collapses relative hops.
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)

    return "/".join(parts)


def _resolve_ts_alias(import_name: str, ts_paths: dict[str, str]) -> str | None:
    """Match an import against tsconfig path aliases by longest prefix."""
    for prefix, target in ts_paths.items():
        if not prefix:
            continue
        # First matching alias wins; relies on dict insertion order rather
        # than explicitly comparing prefix lengths.
        if import_name.startswith(prefix):
            remainder = import_name[len(prefix) :]
            resolved = Path(target) / remainder
            return str(resolved).replace("\\", "/")
    return None


def _resolve_java_import(import_name: str) -> str | None:
    """Convert a Java dotted import into a ``.java`` path stem.

    Heuristically drops the trailing segment when it looks like a member
    (wildcard, all-caps constant, or lowercase field) rather than a class.
    """
    name = import_name.replace("import ", "").strip().rstrip(";")

    parts = name.split(".")
    if len(parts) < 2:
        return None

    last = parts[-1]
    # `import foo.bar.BAZ` often imports a constant/member, not a class;
    # drop segments that look like members so the path points at the file.
    if last == "*" or last == last.upper() or last[0].islower():
        parts = parts[:-1]

    return "/".join(parts) + ".java"


def _resolve_generic_import(
    import_name: str, importing_file: str, repo_root: str
) -> str | None:
    """Resolve imports for unsupported languages using dot/slash heuristics."""
    import_name = import_name.strip("\"'")

    if "/" not in import_name and "." not in import_name:
        return None

    if "." in import_name and "/" not in import_name:
        import_name = import_name.replace(".", "/")

    if import_name.startswith("."):
        importing_dir = Path(importing_file).parent
        resolved_path = importing_dir / import_name

        parts = []
        for part in str(resolved_path).replace("\\", "/").split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)

        return "/".join(parts)

    return import_name.strip("/")

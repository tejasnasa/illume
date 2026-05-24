import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_ts_paths(repo_root: str | Path) -> dict[str, str]:
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
                            continue
                        paths[alias.rstrip("*")] = rel_target
            except Exception:
                pass

    return paths


def load_workspace_map(repo_root: str) -> dict[str, str]:
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

            if "/" not in name and not data.get("exports"):
                if pkg_dir == "." or not data.get("main"):
                    continue

            exports = data.get("exports", {})
            has_root_export = False

            if isinstance(exports, dict):
                for pattern, target in exports.items():
                    if isinstance(target, dict):
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
    if " as " in import_name:
        import_name = import_name.split(" as ")[0].strip()

    importing_dir = Path(importing_file).parent

    if import_name.startswith("."):
        return _resolve_python_relative(import_name, importing_dir, repo_root)

    return import_name.replace(".", "/")


def _resolve_python_relative(
    import_name: str, importing_dir: Path, repo_root: str
) -> str | None:
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
    if workspace_map:
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
        return None

    if not import_name.startswith("."):
        return None

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


def _resolve_ts_alias(import_name: str, ts_paths: dict[str, str]) -> str | None:
    for prefix, target in ts_paths.items():
        if not prefix:
            continue
        if import_name.startswith(prefix):
            remainder = import_name[len(prefix) :]
            resolved = Path(target) / remainder
            return str(resolved).replace("\\", "/")
    return None


def _resolve_java_import(import_name: str) -> str | None:
    name = import_name.replace("import ", "").strip().rstrip(";")

    parts = name.split(".")
    if len(parts) < 2:
        return None

    last = parts[-1]
    if last == "*" or last == last.upper() or last[0].islower():
        parts = parts[:-1]

    return "/".join(parts) + ".java"


def _resolve_generic_import(
    import_name: str, importing_file: str, repo_root: str
) -> str | None:
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

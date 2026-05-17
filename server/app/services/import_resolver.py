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
                        abs_target = (config_file.parent / base_url / targets[0].rstrip("*")).resolve()
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
    """
    Scan all package.json files to build a map of workspace package name → directory.
    e.g. {"@repo/ui": "packages/ui", "@repo/config": "packages/config"}
    """
    root = Path(repo_root)
    workspace_map: dict[str, str] = {}

    for pkg_file in root.rglob("package.json"):
        if "node_modules" in pkg_file.parts:
            continue
        try:
            data = json.loads(pkg_file.read_text(errors="ignore"))
            name = data.get("name")
            if name:
                pkg_dir = str(pkg_file.parent.relative_to(root)).replace("\\", "/")
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
    if language == "Python":
        return _resolve_python_import(import_name, importing_file, repo_root)
    elif language in ("JavaScript", "TypeScript"):
        return _resolve_js_import(
            import_name, importing_file, repo_root, ts_paths, workspace_map
        )
    elif language == "Java":
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
        for pkg_name, pkg_dir in workspace_map.items():
            if import_name == pkg_name or import_name.startswith(pkg_name + "/"):
                remainder = import_name[len(pkg_name):]
                return (pkg_dir + remainder).lstrip("/")

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

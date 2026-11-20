"""Run manifest: the record written beside every eval output directory.

It captures what produced the numbers: the code revision and whether the tree was dirty,
the dependency lock, the arm configurations, prompt and model versions, prices, corpus
pins and the split. A dirty tree is recorded, never refused.
"""

import hashlib
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SERVER_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"


def git_state(repo_dir: Path = SERVER_ROOT) -> dict[str, Any]:
    """Read the git revision and dirtiness of a working tree.

    Args:
        repo_dir: Any directory inside the repository.

    Returns:
        ``{"sha": str | None, "dirty": bool | None}``. Both are ``None`` when git is
        missing or the directory is not a repository.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except OSError, subprocess.SubprocessError:
        return {"sha": None, "dirty": None}
    return {"sha": sha, "dirty": bool(porcelain.strip())}


def file_sha256(path: Path) -> str | None:
    """Return the SHA-256 hex digest of a file, or ``None`` if it does not exist.

    Args:
        path: The file to hash.

    Returns:
        The hex digest, or ``None``.
    """
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    *,
    arms: Mapping[str, str],
    prompt_version: str,
    models: Mapping[str, str],
    reported_snapshots: Mapping[str, str],
    price_table_version: str,
    agent_token_cap: int,
    corpus_pins: Mapping[str, str],
    split_hash: str,
    eval_instruction: str,
    git: Mapping[str, Any] | None = None,
    uv_lock_sha256: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the manifest dictionary.

    Args:
        arms: Arm name to ``config_hash``.
        prompt_version: The agent prompt version.
        models: Role to configured model id.
        reported_snapshots: Role to the snapshot id the provider reported.
        price_table_version: Version of the price table used for cost accounting.
        agent_token_cap: The agent's token cap.
        corpus_pins: Repository name to pinned base commit.
        split_hash: Hash of the dev/test split.
        eval_instruction: The instruction text given to the evaluated system.
        git: ``{"sha", "dirty"}``; read from the working tree when omitted.
        uv_lock_sha256: Digest of ``uv.lock``; computed when omitted.
        created_at: Timestamp; the current UTC time when omitted.

    Returns:
        A JSON-serialisable dictionary.
    """
    state = dict(git) if git is not None else git_state()
    if uv_lock_sha256 is None:
        uv_lock_sha256 = file_sha256(SERVER_ROOT / "uv.lock")
    stamp = created_at or datetime.now(UTC)
    return {
        "git_sha": state.get("sha"),
        "dirty": state.get("dirty"),
        "uv_lock_sha256": uv_lock_sha256,
        "arms": dict(arms),
        "prompt_version": prompt_version,
        "models": dict(models),
        "reported_snapshots": dict(reported_snapshots),
        "price_table_version": price_table_version,
        "agent_token_cap": agent_token_cap,
        "corpus_pins": dict(corpus_pins),
        "split_hash": split_hash,
        "eval_instruction": eval_instruction,
        "created_at": stamp.astimezone(UTC).isoformat(),
    }


def write_manifest(out_dir: Path, **kwargs: Any) -> Path:
    """Write ``manifest.json`` into an output directory.

    Args:
        out_dir: The directory to write into; created if missing.
        **kwargs: Arguments for ``build_manifest``.

    Returns:
        The path of the written file.
    """
    manifest = build_manifest(**kwargs)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path

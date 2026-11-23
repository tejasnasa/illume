"""Git output is decoded as UTF-8 whatever the platform's locale encoding is."""

import os
import subprocess

import pytest

from app.services.git_analyzer import _parse_git_log, _run_git_log

pytestmark = pytest.mark.integration

# "ā" encodes to C4 81 in UTF-8, and 0x81 has no mapping in cp1252, the locale encoding
# a Windows worker decodes with by default.
MESSAGE = "Fix the āccent handling"
AUTHOR = "Zoë Ñúñez"


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def test_a_non_ascii_commit_is_read_and_parsed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "café.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": AUTHOR,
        "GIT_AUTHOR_EMAIL": "zoe@example.com",
        "GIT_COMMITTER_NAME": AUTHOR,
        "GIT_COMMITTER_EMAIL": "zoe@example.com",
    }
    _git(repo, "-c", "i18n.commitEncoding=utf-8", "commit", "-q", "-m", MESSAGE, env=env)

    raw = _run_git_log(repo)

    assert raw is not None and MESSAGE in raw
    commits = _parse_git_log(raw)
    assert len(commits) == 1

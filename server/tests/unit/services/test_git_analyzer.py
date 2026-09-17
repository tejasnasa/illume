"""Git history parsing and ownership aggregation.

Everything below `analyze_git_history` is pure: canned `git log --numstat` text goes in,
structured records come out. No git binary is invoked, so these run anywhere and cannot
flap on the local git version.
"""

from datetime import UTC, datetime

import pytest

from app.services.git_analyzer import (
    FIELD_SEPARATOR,
    GIT_LOG_MAX_COMMITS,
    _aggregate_file_stats,
    _detect_test_files,
    _generate_test_candidates,
    _looks_like_header,
    _normalise_rename_path,
    _parse_git_date,
    _parse_git_log,
    _parse_numstat_line,
)

pytestmark = pytest.mark.unit

# Built from the module's own separator rather than a literal, so the fixture cannot
# drift from the format string the parser expects.
S = FIELD_SEPARATOR

HEADER_A = S.join(
    ["a" * 40, "alice@example.com", "Alice Smith", "Add the thing", "2026-01-15 10:30:00 +0000"]
)
HEADER_B = S.join(
    ["b" * 40, "bob@example.com", "Bob Jones", "Fix the thing", "2026-01-16 11:00:00 +0000"]
)

SAMPLE_LOG = f"""{HEADER_A}

10\t2\tsrc/app.py
5\t0\tsrc/util.py

{HEADER_B}

3\t1\tsrc/app.py
"""


class TestHeaderDetection:
    def test_recognises_a_commit_hash(self):
        assert _looks_like_header(HEADER_A)

    @pytest.mark.parametrize(
        "line",
        [
            "10\t2\tsrc/app.py",
            "feat: add | to the message",
            S.join(
                [
                    "not-a-hash",
                    "someone@example.com",
                    "Name",
                    "msg",
                    "2026-01-01 00:00:00 +0000",
                ]
            ),
        ],
    )
    def test_rejects_non_headers(self, line):
        assert not _looks_like_header(line)

    def test_a_short_hex_prefix_is_not_a_header(self):
        """Fewer than 7 hex characters is not a git hash."""
        assert not _looks_like_header(f"abc123{S}x")

    def test_uppercase_hex_is_not_treated_as_a_hash(self):
        """git emits lowercase; the regex is case-sensitive."""
        assert not _looks_like_header(f"{'A' * 40}{S}x")


class TestParseGitLog:
    def test_parses_both_commits(self):
        commits = _parse_git_log(SAMPLE_LOG)

        assert len(commits) == 2
        assert commits[0]["hash"] == "a" * 40
        assert commits[1]["hash"] == "b" * 40

    def test_captures_commit_metadata(self):
        first = _parse_git_log(SAMPLE_LOG)[0]

        assert first["author_name"] == "Alice Smith"
        assert first["author_email"] == "alice@example.com"
        assert first["message"] == "Add the thing"

    def test_lowercases_author_email(self):
        """Emails are lowercased so the same person is not counted as two authors."""
        raw = (
            S.join(
                [
                    "c" * 40,
                    "Mixed.Case@Example.COM",
                    "Car",
                    "msg",
                    "2026-01-01 00:00:00 +0000",
                ]
            )
            + "\n"
        )

        assert _parse_git_log(raw)[0]["author_email"] == "mixed.case@example.com"

    def test_attaches_numstat_rows_to_their_commit(self):
        commits = _parse_git_log(SAMPLE_LOG)

        assert [f["path"] for f in commits[0]["files"]] == ["src/app.py", "src/util.py"]
        assert [f["path"] for f in commits[1]["files"]] == ["src/app.py"]

    def test_captures_added_and_deleted_counts(self):
        first_file = _parse_git_log(SAMPLE_LOG)[0]["files"][0]

        assert first_file["added"] == 10
        assert first_file["deleted"] == 2

    def test_parses_the_final_commit(self):
        """The last commit has no successor header to trigger the flush."""
        assert _parse_git_log(SAMPLE_LOG)[-1]["files"] != []

    def test_empty_input_yields_no_commits(self):
        assert _parse_git_log("") == []

    def test_commit_without_file_changes_is_still_recorded(self):
        raw = f"{HEADER_A}\n\n{HEADER_B}\n\n1\t1\tx.py\n"

        commits = _parse_git_log(raw)

        assert len(commits) == 2
        assert commits[0]["files"] == []

    def test_a_pipe_in_a_commit_message_is_preserved(self):
        """
        Commit subjects routinely contain pipes, so the separator is a control character
        that cannot appear in a message. With a pipe delimiter this truncated the subject
        at the first `|` *and* pushed the remainder into the date field, which failed to
        parse and fell back to the wall clock.
        """
        raw = (
            S.join(
                [
                    "d" * 40,
                    "dev@example.com",
                    "Dev",
                    "feat: a | b | c",
                    "2026-01-01 00:00:00 +0000",
                ]
            )
            + "\n\n1\t1\tx.py\n"
        )

        commit = _parse_git_log(raw)[0]

        assert commit["message"] == "feat: a | b | c"
        assert commit["timestamp"] == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_malformed_header_is_skipped(self):
        raw = f"{'e' * 40}{S}only-two-fields\n\n1\t1\tx.py\n"

        assert _parse_git_log(raw) == []


class TestNumstatLine:
    def test_parses_a_normal_row(self):
        assert _parse_numstat_line("10\t2\tsrc/app.py") == {
            "path": "src/app.py",
            "added": 10,
            "deleted": 2,
        }

    def test_binary_files_are_zeroed(self):
        """`-` marks binary content, which numstat cannot count."""
        assert _parse_numstat_line("-\t-\tlogo.png") == {
            "path": "logo.png",
            "added": 0,
            "deleted": 0,
        }

    @pytest.mark.parametrize("line", ["", "only-one-field", "10\tnopath"])
    def test_malformed_rows_return_none(self, line):
        assert _parse_numstat_line(line) is None

    def test_non_numeric_counts_return_none(self):
        assert _parse_numstat_line("ten\t2\tx.py") is None

    def test_windows_separators_are_normalised(self):
        assert _parse_numstat_line("1\t1\tsrc\\nested\\app.py")["path"] == "src/nested/app.py"

    def test_a_path_containing_tabs_is_preserved(self):
        """`split('\\t', 2)` keeps everything after the counts as one path."""
        assert _parse_numstat_line("1\t1\tsrc/weird\tname.py")["path"] == "src/weird\tname.py"


class TestRenameNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("src/{old => new}/file.py", "src/new/file.py"),
            ("{a.py => b.py}", "b.py"),
            ("src/old/{a.py => b.py}", "src/old/b.py"),
            # One side of the arrow is empty when a file moves into or out of a
            # directory. These used to fall through unmatched, leaving the literal
            # braces in the path so it matched no File row and the file's ownership
            # data was silently dropped.
            ("src/{ => sub}/file.py", "src/sub/file.py"),
            ("src/{sub => }/file.py", "src/file.py"),
        ],
    )
    def test_collapses_rename_syntax(self, raw, expected):
        assert _normalise_rename_path(raw) == expected

    def test_an_empty_side_does_not_leave_stray_braces(self):
        """The failure mode was literal braces surviving into the path."""
        for raw in ("src/{ => sub}/file.py", "src/{sub => }/file.py"):
            assert "{" not in _normalise_rename_path(raw)

    def test_ordinary_paths_pass_through(self):
        assert _normalise_rename_path("src/app.py") == "src/app.py"


class TestDateParsing:
    def test_converts_to_utc(self):
        parsed = _parse_git_date("2026-01-15 10:30:00 +0000")

        assert parsed == datetime(2026, 1, 15, 10, 30, tzinfo=UTC)

    def test_converts_a_non_utc_offset(self):
        parsed = _parse_git_date("2026-01-15 10:30:00 +0530")

        assert parsed == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)

    def test_unparseable_input_falls_back_to_now(self):
        """A bad date must not abort analysis of the whole repository."""
        before = datetime.now(UTC)

        parsed = _parse_git_date("not a date")

        assert parsed >= before


class TestAggregateFileStats:
    def test_counts_commits_per_file(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        assert stats["src/app.py"]["change_frequency"] == 2
        assert stats["src/util.py"]["change_frequency"] == 1

    def test_computes_ownership_percentages(self):
        """Alice and Bob each touch app.py once in this sample, so it is an even split."""
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))
        contributors = stats["src/app.py"]["contributors"]

        by_email = {c["email"]: c["percentage"] for c in contributors}
        assert by_email["alice@example.com"] == pytest.approx(50.0, abs=0.1)
        assert by_email["bob@example.com"] == pytest.approx(50.0, abs=0.1)

    def test_a_dominant_author_is_weighted_by_commit_count(self):
        """Three commits from one author against one from another is a 75/25 split."""
        from datetime import datetime

        def commit(email, name):
            return {
                "hash": f"{email[:6]:0<40}",
                "author_email": email,
                "author_name": name,
                "message": "m",
                "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
                "files": [{"path": "shared.py", "added": 1, "deleted": 0}],
            }

        commits = [commit("a@example.com", "A") for _ in range(3)]
        commits.append(commit("b@example.com", "B"))

        contributors = _aggregate_file_stats(commits)["shared.py"]["contributors"]

        by_email = {c["email"]: c["percentage"] for c in contributors}
        assert by_email["a@example.com"] == pytest.approx(75.0)
        assert by_email["b@example.com"] == pytest.approx(25.0)

    def test_percentages_sum_to_about_one_hundred(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        total = sum(c["percentage"] for c in stats["src/app.py"]["contributors"])
        assert total == pytest.approx(100.0, abs=0.2)

    def test_contributors_are_ordered_by_commit_count(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        counts = [c["commit_count"] for c in stats["src/app.py"]["contributors"]]
        assert counts == sorted(counts, reverse=True)

    def test_primary_owner_is_the_top_contributor(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        assert stats["src/app.py"]["primary_owner_email"] == "alice@example.com"
        assert stats["src/app.py"]["primary_owner_name"] == "Alice Smith"

    def test_single_author_file_is_a_knowledge_silo(self):
        """Bus factor 1: losing this person loses the file."""
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        assert stats["src/util.py"]["is_knowledge_silo"] is True

    def test_multi_author_file_is_not_a_knowledge_silo(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        assert stats["src/app.py"]["is_knowledge_silo"] is False

    def test_last_modified_is_the_most_recent_commit(self):
        stats = _aggregate_file_stats(_parse_git_log(SAMPLE_LOG))

        # Bob's commit is a day after Alice's.
        assert stats["src/app.py"]["git_last_modified"] == datetime(2026, 1, 16, 11, 0, tzinfo=UTC)

    def test_out_of_order_commits_still_pick_the_latest(self):
        """
        Commits are not guaranteed to arrive chronologically, so the aggregation must
        compare timestamps rather than assume the last one wins.
        """
        newer = {
            "hash": "n" * 40,
            "author_email": "a@example.com",
            "author_name": "A",
            "message": "newer",
            "timestamp": datetime(2026, 6, 1, tzinfo=UTC),
            "files": [{"path": "x.py", "added": 1, "deleted": 0}],
        }
        older = {**newer, "timestamp": datetime(2026, 1, 1, tzinfo=UTC)}

        stats = _aggregate_file_stats([newer, older])

        assert stats["x.py"]["git_last_modified"] == datetime(2026, 6, 1, tzinfo=UTC)

    def test_empty_input_yields_no_stats(self):
        assert _aggregate_file_stats([]) == {}


class TestTestFileCandidates:
    """
    Candidates are built with `str(Path / name)`, so they use the OS separator. The
    comparisons here normalise to forward slashes so the assertions read the same on
    every platform.
    """

    def candidates(self) -> list[str]:
        from pathlib import Path

        generated = _generate_test_candidates(Path("src"), "app", ".py")
        return [c.replace("\\", "/") for c in generated]

    def test_generates_sibling_variants(self):
        candidates = self.candidates()

        assert "src/test_app.py" in candidates
        assert "src/app_test.py" in candidates

    def test_includes_repo_level_test_directories(self):
        assert any(c.startswith("tests/") for c in self.candidates())

    def test_includes_colocated_test_folders(self):
        candidates = self.candidates()

        assert any(c.startswith("src/__tests__/") for c in candidates)
        assert any(c.startswith("src/tests/") for c in candidates)

    def test_detects_a_colocated_test_file(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")
        (tmp_path / "test_app.py").write_text("def test(): pass")

        assert _detect_test_files(tmp_path, ["app.py"]) == {"app.py": True}

    def test_reports_no_test_when_none_exists(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")

        assert _detect_test_files(tmp_path, ["app.py"]) == {"app.py": False}

    def test_detects_a_test_in_a_tests_directory(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x = 1")
        (tmp_path / "src" / "tests").mkdir()
        (tmp_path / "src" / "tests" / "test_app.py").write_text("def test(): pass")

        assert _detect_test_files(tmp_path, ["src/app.py"])["src/app.py"] is True

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert _detect_test_files(tmp_path, ["never-existed.py"]) == {"never-existed.py": False}


class TestCommitCap:
    def test_cap_is_configured(self):
        """The pipeline promises a bounded git history read."""
        assert GIT_LOG_MAX_COMMITS == 500

    def test_git_log_command_applies_the_cap(self, monkeypatch, tmp_path):
        from app.services import git_analyzer

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd

            class Result:
                stdout = ""

            return Result()

        monkeypatch.setattr(git_analyzer.subprocess, "run", fake_run)

        git_analyzer._run_git_log(tmp_path)

        assert f"-n{GIT_LOG_MAX_COMMITS}" in captured["cmd"]
        assert "--numstat" in captured["cmd"]

    def test_a_git_failure_raises_runtime_error(self, monkeypatch, tmp_path):
        import subprocess as sp

        from app.services import git_analyzer

        def fake_run(cmd, **kwargs):
            raise sp.CalledProcessError(returncode=1, cmd=cmd, stderr="not a repo")

        monkeypatch.setattr(git_analyzer.subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="git log failed"):
            git_analyzer._run_git_log(tmp_path)

    def test_a_timeout_raises_runtime_error(self, monkeypatch, tmp_path):
        import subprocess as sp

        from app.services import git_analyzer

        def fake_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd=cmd, timeout=120)

        monkeypatch.setattr(git_analyzer.subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="timed out"):
            git_analyzer._run_git_log(tmp_path)

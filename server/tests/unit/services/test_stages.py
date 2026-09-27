"""The stage vocabulary, and the guard that stops it drifting.

``Stage`` and the names passed to ``stage(...)`` by the timing instrumentation
describe the same graph, so a name present on only one side is a real defect
that is invisible at runtime: the timer logs under one label while the progress
stream publishes another, and nothing raises. Pinning the two together is the
entire reason ``Stage`` exists rather than each call site using a bare string.
"""

import ast
from pathlib import Path

import pytest

from app.services._stages import Phase, Stage

pytestmark = pytest.mark.unit

# ``tests/unit/services/test_stages.py`` -> ``tests`` -> ``server``, then ``app``.
APP_ROOT = Path(__file__).resolve().parents[3] / "app"


def _timed_stage_names() -> set[str]:
    """Collect every string literal passed as the first argument of ``stage(...)``.

    Walks the whole ``app`` tree rather than just ``_stage_timer``. That module
    only *defines* ``stage`` -- its own mentions of it sit inside docstring
    examples, which ``ast`` sees as string constants rather than calls -- so
    parsing it alone returns an empty set and any comparison against it would
    pass while checking nothing.
    """
    names: set[str] = set()
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "stage"):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
    return names


class TestTimedStageNames:
    def test_the_scan_finds_the_stages_the_pipeline_runs(self):
        """Guards the parser itself; an empty scan would make the tests below vacuous."""
        found = _timed_stage_names()
        assert len(found) >= 14, f"expected the full pipeline vocabulary, found {sorted(found)}"
        assert "parse" in found
        assert "glossary" in found

    def test_docstring_examples_are_not_mistaken_for_calls(self):
        """``_stage_timer``'s examples must not leak in as if they were real stages."""
        assert "scanner" not in _timed_stage_names()


class TestStageVocabulary:
    def test_every_timed_stage_has_a_member(self):
        unknown = _timed_stage_names() - set(Stage)
        assert unknown == set(), (
            f"stage(...) names with no Stage member: {sorted(unknown)} -- the timing "
            "vocabulary and the progress vocabulary have drifted apart"
        )

    def test_every_member_except_ready_is_timed(self):
        """``READY`` is published but never timed; everything else must have a timer."""
        untimed = set(Stage) - _timed_stage_names() - {Stage.READY}
        assert untimed == set(), f"Stage members with no stage(...) timer: {sorted(untimed)}"

    def test_member_values_match_their_names(self):
        """
        The client matches on the value, so a member whose value drifted from
        its name would be a silent rename on the wire.
        """
        for member in Stage:
            assert member.value == member.name.lower(), f"{member.name} != {member.value!r}"


class TestPhaseVocabulary:
    def test_the_four_lifecycle_phases(self):
        assert set(Phase) == {Phase.STARTED, Phase.PROGRESS, Phase.DONE, Phase.FAILED}

    def test_member_values_match_their_names(self):
        for member in Phase:
            assert member.value == member.name.lower()

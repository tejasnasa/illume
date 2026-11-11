"""What a tool returns, and how it is shown to the model.

Every tool returns a Pydantic model. The model sees ``render()``, a compact text
form; the step log and the interface keep ``model_dump(mode="json")``. Text that
came out of the repository is wrapped in ``<source>`` blocks, so the model can
tell evidence from instructions, and a result never exceeds
:data:`MAX_RESULT_CHARS`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, computed_field

from app.services.retrieval.context import escape_fence

MAX_RESULT_CHARS = 12_000

Provenance = Literal["repo", "history"]


def _attribute(value: str) -> str:
    """A value safe inside a double-quoted attribute."""
    return value.replace('"', "&quot;").replace("<", "&lt;")


def fence(key: str, body: str, *, label: str = "code", provenance: Provenance = "repo") -> str:
    """Wraps repository text in a ``<source>`` block.

    Any ``<source`` or ``</source`` inside the body is made harmless first, so
    the text cannot close its own block and speak outside it.

    Args:
        key: The citation key for the text, or ``tool:<name>`` for a listing
            that is not itself citable.
        body: The text.
        label: What kind of text it is, shown as the ``type`` attribute.
        provenance: ``history`` for commits and pull requests, ``repo`` for the rest.
    """
    return (
        f'<source key="{_attribute(key)}" type="{_attribute(label)}" '
        f'provenance="{provenance}">\n{escape_fence(body)}\n</source>'
    )


def numbered(text: str, first_line: int) -> str:
    """The text with each line prefixed by its line number in the file."""
    lines = text.splitlines()
    width = len(str(first_line + max(len(lines) - 1, 0)))
    return "\n".join(f"{first_line + i:>{width}}  {line}" for i, line in enumerate(lines))


def excerpt(text: str, limit: int) -> str:
    """The text cut to ``limit`` characters, with an ellipsis when it was cut."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cap_text(text: str, limit: int = MAX_RESULT_CHARS) -> tuple[str, bool]:
    """Cuts a result to ``limit`` characters and says so.

    The cut falls on a line break when one is near, a block left open by the cut
    is closed, and the note names how much was kept. The result, note included,
    is never longer than ``limit``.

    Returns:
        The text and whether it was cut.
    """
    if len(text) <= limit:
        return text, False
    note = (
        f"\n[output truncated: the first {{kept:,}} of {len(text):,} characters are shown. "
        "Narrow the request, or read the rest in smaller parts.]"
    )
    reserve = len(note) + len("\n</source>") + 8
    kept = text[: limit - reserve]
    newline = kept.rfind("\n")
    if newline > len(kept) * 0.8:
        kept = kept[:newline]
    closing = "\n</source>" if kept.count("<source ") > kept.count("</source>") else ""
    return kept + closing + note.format(kept=len(kept)), True


class ToolOutput(BaseModel):
    """Base of every tool result.

    Attributes:
        note: A sentence for the model when something needs saying, such as a
            path that does not exist.
    """

    note: str | None = None

    def render(self) -> str:
        """The compact text the model sees."""
        raise NotImplementedError

    def note_line(self) -> str:
        """The note as a line to put above the result, or nothing."""
        return f"{self.note}\n" if self.note else ""


class ListOutput(ToolOutput):
    """A result that is a list, which always says how much of it is shown.

    Attributes:
        total: How many items exist.
        items: The items returned; subclasses give them a type.
    """

    total: int
    items: list[Any]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def returned(self) -> int:
        """How many items are in ``items``."""
        return len(self.items)

    def count_line(self, noun: str) -> str:
        """``n of m <noun>``, with a hint when some are left out."""
        line = f"{self.returned} of {self.total} {noun}"
        if self.returned < self.total:
            line += " (more exist; narrow the request or raise the limit)"
        return line

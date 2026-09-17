"""Shared validation for free-text and paginated request values.

Two classes of input passed every check the application had -- JSON decoding,
pydantic's own constraints -- and then raised *inside* the database driver, which
nothing caught, so both became a logged traceback and an opaque 500 with no
``detail`` for the client to render:

* a NUL byte, which no text column can hold, so ``asyncpg`` fails while encoding
  the parameter (``CharacterNotInRepertoireError``). Verified for ``ILIKE``
  patterns, equality comparisons, and plain ``TEXT`` casts alike -- it is a
  property of the parameter encoder, not of any one query;
* an unbounded ``page``, whose computed ``(page - 1) * page_size`` offset
  overflows ``BIGINT`` (``DataError: value out of int64 range``).

Both were confirmed against the live driver. ``FreeText`` and ``PageNumber`` live
here so that the next free-text or paginated endpoint inherits the checks rather
than reintroducing the shape.
"""

from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator

# The largest `page_size` any paginated route accepts, used to derive the bound below.
MAX_PAGE_SIZE = 200

# PostgreSQL's OFFSET is a signed 64-bit integer, and routes compute `(page - 1) *
# page_size` in Python, where the integer is unbounded. A page large enough for that
# product to exceed int64 therefore reaches asyncpg as an unrepresentable value, which
# raises DataError -- an unhandled 500.
#
# Derived from the limit rather than picked. An arbitrary "practical" ceiling would
# reject pages that work today: `page=1000000000` returns an empty page quite happily,
# and the suite's control test pins exactly that, because the boundary really is int64
# and not some smaller number. Deriving it also means raising a route's `page_size`
# ceiling cannot silently invalidate the bound.
MAX_PAGE = 2**63 // MAX_PAGE_SIZE


def _no_control_characters(value: str | None) -> str | None:
    """Reject control characters in a free-text value.

    The NUL byte is the one that actually raises against the driver, but the rest
    of C0 is equally meaningless in a file path, a search term, or a person's name.
    Rejecting the whole class closes the *shape* rather than the single character
    that happened to be reported. ``DEL`` is included because it is the other
    non-printing character a naive ``< 32`` test misses.

    Args:
        value: The string to check, or None for an optional field.

    Returns:
        The value unchanged when it is acceptable.

    Raises:
        ValueError: If the value contains a control character.
    """
    if value is None:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("must not contain control characters")
    return value


NoControlCharacters = AfterValidator(_no_control_characters)
"""Reusable validator metadata for a free-text value.

For a **query parameter**, this has to be placed inside the same ``Annotated`` as the
``Query(...)``::

    q: Annotated[str, Query(min_length=1), NoControlCharacters]

It cannot be attached to a type alias that is then used *alongside* a separate
``Query(...)`` default -- FastAPI rebuilds the field from the query metadata and
silently drops validator metadata it does not recognise, so the check simply never
runs. That failure is invisible: the endpoint behaves exactly as it did before, which
is why the param count and status codes are worth checking after any change here.

For a **request body**, a plain alias is enough, because pydantic builds that schema
itself and keeps the validator.
"""

FreeText = Annotated[str, NoControlCharacters]
"""A ``str`` that cannot contain a control character."""

OptionalFreeText = Annotated[str | None, NoControlCharacters]
"""An optional ``str`` that cannot contain a control character when present."""

PageNumber = Annotated[int, Query(ge=1, le=MAX_PAGE)]
"""A 1-indexed page number, bounded so its offset cannot overflow ``BIGINT``."""

"""Registry of self-test cases for the eval harness.

Metric and scoring modules register cases that check their own arithmetic against
hand-computed values; ``python -m evals selftest`` runs them all.
"""

from collections.abc import Callable

Case = Callable[[], None]

_CASES: dict[str, Case] = {}


def register(name: str) -> Callable[[Case], Case]:
    """Register a self-test case.

    A case passes when it returns and fails when it raises.

    Args:
        name: A unique, human-readable case name.

    Returns:
        A decorator that records the function and returns it unchanged.

    Raises:
        ValueError: If ``name`` is already registered.
    """

    def decorator(fn: Case) -> Case:
        if name in _CASES:
            raise ValueError(f"duplicate selftest case {name!r}")
        _CASES[name] = fn
        return fn

    return decorator


def run_all() -> tuple[list[str], list[tuple[str, str]]]:
    """Run every registered case.

    Returns:
        A ``(passed, failed)`` pair: names of passing cases, and ``(name, message)`` for
        each failing one.
    """
    passed: list[str] = []
    failed: list[tuple[str, str]] = []
    for name, fn in _CASES.items():
        try:
            fn()
        except Exception as exc:
            failed.append((name, f"{type(exc).__name__}: {exc}"))
        else:
            passed.append(name)
    return passed, failed

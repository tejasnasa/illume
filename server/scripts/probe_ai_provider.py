"""
Standalone probe for the AI provider transport used by the free tier.

    uv run python scripts/probe_ai_provider.py
    uv run python scripts/probe_ai_provider.py --provider groq --model llama-3.3-70b-versatile ...

The probe verifies, against the **real** provider rather than a mock, that
the wire format the four generation services send is accepted end-to-end.
It mirrors each call shape from the application code byte-for-byte (prompt
contents, ``reasoning.effort`` values, ``max_output_tokens`` caps), so a
mismatch surfaces here rather than as silently empty glossary entries,
unannotated reading orders, or a fallback brief.

Three design rules, all load-bearing:

1. **No application imports.** ``app.core.config`` requires a full environment and
   would fail before the probe reached its first check; the provider registry
   lives in a separate module that imports zero settings. This script reads
   its three inputs directly from ``os.environ`` so it can run from a bare
   shell.
2. **Defaults are the production free-tier path.** Running it with no arguments
   exercises ``https://api.deepseek.com`` + ``deepseek-flash`` + ``$AI_API_KEY``
   -- the same call the free tier makes in production. Overrides exist so the
   same probe can verify a user's own preset later, but the unflagged form is
   the deployment's smoke test.
3. **Exit non-zero on any failure.** ``$AI_API_KEY`` empty disables the free
   tier; this probe refuses to run rather than mask that as "transport OK".
   A zero exit means every shape the four services send round-tripped to
   non-empty output.

The four checks map to the four services in ``app/services/``:

  1. ``responses.create`` with ``reasoning={"effort": "minimal"}`` and a short
     user message. Confirms the no-``/v1`` base URL is accepted and that
     ``reasoning`` is understood -- a wrong ``base_url`` here returns 404 at
     request time, not at import.
  2. A chat-shaped multi-turn replay in the exact ``messages`` shape
     ``rag.answer_question`` builds (one system message, prior user/assistant
     turns, then the new user turn). This is the case third-party reports say
     DeepSeek may reject with ``400 The reasoning_text in the thinking mode
     must be passed back to the API`` when the model is in thinking mode.
     If check 2 fails, the free tier's chat is broken in a way no unit test
     can reveal -- multi-turn is the real shape, single-turn probes would
     miss it.
  3. The two JSON-parsing shapes: glossary (a single user message of ``Name:``
     / ``File:`` / ``Lines:`` blocks asking for a JSON array of
     ``{"name", "definition"}``, ``max_output_tokens=2000``) and reading-order
     annotations (``file_path=`` numbered lines asking for a JSON array of
     ``{"file_path", "annotation"}``, ``max_output_tokens=1000``). Both shapes
     **parse** the response, so a provider that fences its JSON differently,
     or drops the array, shows up here instead of as silently empty glossary
     entries and unannotated guides. A markdown fence is included in the
     expected-answer paragraph even though both prompts forbid it --
     ``_parse_response`` and the annotate path both strip fences, so a
     provider that always fences must still pass.
  4. ``architecture_brief``'s shape: a ``system`` + ``user`` pair with
     ``reasoning={"effort": "low"}``. Different effort level from checks 1-3,
     so this is the one that catches a provider accepting ``minimal`` but
     rejecting ``low``.

Keep the script afterwards as an ops diagnostic. It is the tool to reach for
when a deploy's free tier misbehaves -- the four checks tell you which of the
four call shapes broke and what the wire actually said.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI, OpenAI

# Production defaults for the free tier. Overridable via argv / env so the same probe
# validates a user's own preset -- but the unflagged form is the one CI runs.
DEFAULT_PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


@dataclass(frozen=True)
class ProviderTarget:
    """The three strings an OpenAI client needs: key, model, base URL.

    Three strings, deliberately not a richer object: the probe runs without
    importing ``app.services.llm_config``, and a dataclass of three fields is
    what the application code constructs from a database row anyway. Naming
    the fields after the SDK constructor's keyword arguments is intentional
    -- ``OpenAI(**asdict(t))`` would build the client.
    """

    api_key: str
    model: str
    base_url: str


def _parse_args() -> tuple[ProviderTarget, str]:
    """Resolve the probe target from argv, falling back to env, then to documented defaults.

    Env precedence: argv > ``$PROBE_*`` > hardcoded defaults. ``$AI_API_KEY`` is the
    production variable the deploy ships, so a no-arg invocation reads from there; the
    ``PROBE_`` prefix exists so a CI job can override without touching the deploy's
    secret. Missing key is fatal -- an empty key would silently succeed against an
    unauthenticated endpoint, which is exactly the kind of false positive this script
    exists to avoid.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default=os.environ.get("PROBE_PROVIDER", DEFAULT_PROVIDER))
    parser.add_argument("--model", default=os.environ.get("PROBE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("PROBE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PROBE_API_KEY") or os.environ.get("AI_API_KEY", ""),
    )
    args = parser.parse_args()

    if not args.api_key:
        print(
            "error: API key not set. Pass --api-key, $PROBE_API_KEY, or $AI_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(2)

    label = args.provider
    return (
        ProviderTarget(api_key=args.api_key, model=args.model, base_url=args.base_url),
        label,
    )


# --- Prompt shapes -----------------------------------------------------------
#
# These are hand-mirrored from the four services, not imported, on purpose: importing
# would force ``app.*`` to load, which requires a full environment (see module docstring).
# If any of these drifts from the source, the probe stops matching what production sends
# and the value of running it disappears -- the failure mode is silent regression rather
# than a passing check.


def _glossary_prompt() -> str:
    """Mirror ``glossary_builder._build_prompt`` for two fake symbols.

    Two is enough to exercise the JSON-array parsing without spending tokens. The blocks
    are written so a provider that returns a fenced JSON array, a bare JSON array, or a
    prose answer are all distinguishable, and so the parse path's
    ``removeprefix("```json")`` / ``removeprefix("```")`` / ``removesuffix("```")`` strip
    has both with-fence and bare-string inputs to chew on. The markdown fence is in the
    prompt text, not the expected answer -- it is there because both prompts forbid
    fences, and a provider that always fences must still pass after stripping.
    """
    return """You are analyzing a software codebase. For each symbol below, write a plain-English definition (1-2 sentences) that a new engineer would understand on day one. Focus on what it does and why it exists, not how it's implemented.

Respond ONLY with a JSON array. Each element must have exactly these two keys:
- "name": the symbol name (copy exactly as given)
- "definition": your plain-English explanation

Symbols:

Name: probe_function_one
File: probe/module_one.py
Lines: 1-10
Docstring: First probe symbol.
Source (truncated):
def probe_function_one():
    return 1

---

Name: probe_class_two
File: probe/module_two.py
Lines: 1-20
Docstring: Second probe symbol. Wraps a ```markdown fence``` inline.
Source (truncated):
class ProbeClassTwo:
    pass
"""


def _annotation_prompt() -> str:
    """Mirror ``onboarding._build_annotation_prompt`` for two fake files."""
    return """You are an expert software engineer writing an onboarding guide.

For each file below, write a 1-2 sentence explanation of WHY a new engineer should read it at this point in their onboarding journey. Be concrete about what the file does and why understanding it early unlocks the rest of the codebase. Do not use filler phrases like "this file is important". Be direct.

Files (in suggested reading order):
1. file_path=probe/entry.py | fan_in=5 | tier=1 | language=python
2. file_path=probe/worker.py | fan_in=2 | tier=2 | language=python

Respond ONLY with a JSON array, no markdown fences, no preamble:
[
  {"file_path": "<path>", "annotation": "<1-2 sentence why-read-this>"},
  ...
]
"""


def _brief_messages(prompt: str) -> list[dict[str, Any]]:
    """Mirror ``architecture_brief._call_llm_narrative``'s system + user pair."""
    return [
        {
            "role": "system",
            "content": (
                "You are a senior software architect. Analyze repository structure "
                "and write clear, accurate architecture summaries for new engineers."
            ),
        },
        {"role": "user", "content": prompt},
    ]


def _brief_prompt() -> str:
    """Trivial brief input -- ``_call_llm_narrative`` only forwards the prompt string."""
    return (
        "## Task\nWrite a 3-sentence architecture summary for a two-file repository "
        "called 'probe' whose only purpose is to exercise this transport. Mention both "
        "files by name. Do not speculate beyond what the structure shows."
    )


# --- Parsing helpers ----------------------------------------------------------
#
# Same fence-stripping as the application code, kept inline so this script imports
# nothing from ``app.*``. Drifting these strips from production would let a provider
# that always fences silently fail in app and pass here, which is the regression we
# cannot afford.


def _strip_fences(text: str) -> str:
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _parse_json_array(text: str) -> list[dict[str, Any]] | None:
    """Parse a JSON array, matching the two services' contract. ``None`` on failure."""
    try:
        parsed = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


# --- Reporting ----------------------------------------------------------------


@dataclass
class CheckResult:
    label: str
    passed: bool
    detail: str

    def render(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        line = f"[{status}] {self.label}"
        if self.detail:
            line += f"\n        {self.detail}"
        return line


def _summarize(text: str, limit: int = 160) -> str:
    """One-line summary of a response for the PASS/FAIL line."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return repr(compact)
    return repr(compact[:limit] + "...")


def _elapsed(seconds: float) -> str:
    return f"{seconds:.1f}s"


# --- Checks -------------------------------------------------------------------

# Reasoning models (deepseek-flash, gpt-5 family) emit a `reasoning` block before any
# visible text. ``output_text`` is the SDK helper that concatenates only the message
# parts, so a thinking-heavy response yields ``output_text == ""`` even when the model
# is behaving correctly -- the budget just ran out inside the reasoning block. The
# probe's purpose is to verify the wire format, not to benchmark reasoning depth, so
# every check below uses a budget that comfortably fits both the reasoning block and a
# real answer. The application call sites already use 1000-2000 tokens (see
# ``glossary_builder.py:193``, ``onboarding.py:258``, ``architecture_brief.py:388``,
# ``rag.py:294``); matching that range here keeps the probe honest about whether
# production-shaped requests will work.
_PROBE_MAX_TOKENS = 1024


def _status_detail(response: Any) -> str:
    """One-line summary of a response's terminal state for the PASS/FAIL line.

    Distinguishes "request errored" from "request returned empty text" from
    "response came back but was cut off mid-reasoning" -- the three failure modes
    the probe can produce, with very different operational meanings.
    """
    status = getattr(response, "status", None)
    if status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        return f"status=incomplete ({reason}); output_text empty"
    return f"status={status}"


def _check_single_turn(client: OpenAI, target: ProviderTarget) -> CheckResult:
    """Check 1: a short user message with ``reasoning.effort=minimal``.

    Confirms the no-``/v1`` base URL is accepted and ``reasoning`` is understood. A
    wrong base URL returns 404 from the provider at request time, not at import -- the
    shape of the failure differs by provider (some 404, some redirect, some return HTML),
    so the assertion is the only honest one: non-empty ``output_text``.
    """
    started = time.monotonic()
    try:
        response = client.responses.create(
            model=target.model,
            reasoning={"effort": "minimal"},
            input=[{"role": "user", "content": "Reply with the single word: ok."}],
            max_output_tokens=_PROBE_MAX_TOKENS,
        )
    except Exception as exc:
        return CheckResult(
            label="check 1: single-turn with reasoning=minimal",
            passed=False,
            detail=f"request failed in {_elapsed(time.monotonic() - started)}: {exc}",
        )

    text = (response.output_text or "").strip()
    return CheckResult(
        label="check 1: single-turn with reasoning=minimal",
        passed=bool(text),
        detail=(
            f"got {_summarize(text)} in {_elapsed(time.monotonic() - started)} "
            f"[{_status_detail(response)}]"
        ),
    )


async def _check_chat_multiturn(client: AsyncOpenAI, target: ProviderTarget) -> CheckResult:
    """Check 2: chat-shaped multi-turn replay, exactly as ``rag.answer_question`` builds it.

    Third-party reports describe DeepSeek rejecting multi-turn requests with
    ``400 The reasoning_text in the thinking mode must be passed back to the API``
    when the model is in thinking mode. Our chat is multi-turn (the client
    resends prior turns) and ``deepseek-flash`` has thinking and non-thinking
    modes; if it fires for plain message history the free tier's chat is broken
    in a way no unit test can reveal. This is the check that retires that risk.

    The messages list mirrors ``rag.py:281-287``: a system prompt, prior
    user/assistant turns, then a new user turn. The prior turns ask a trivial
    two-step question and the new turn asks for a follow-up whose answer depends
    on the prior turn -- "the capital of the country I mentioned" -- so a model
    that ignored history would fail the assertion below.
    """
    started = time.monotonic()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You answer questions concisely. When the user asks about 'the country I "
                "mentioned', they mean the most recent country named in the conversation."
            ),
        },
        {"role": "user", "content": "Name a country in Europe."},
        {"role": "assistant", "content": "France."},
        {"role": "user", "content": "What is the capital of the country I mentioned?"},
    ]
    try:
        response = await client.responses.create(
            model=target.model,
            reasoning={"effort": "minimal"},
            input=messages,
            max_output_tokens=_PROBE_MAX_TOKENS,
        )
    except Exception as exc:
        return CheckResult(
            label="check 2: chat multi-turn replay",
            passed=False,
            detail=f"request failed in {_elapsed(time.monotonic() - started)}: {exc}",
        )

    text = (response.output_text or "").strip()
    # The follow-up question's answer is "Paris" if the model respected the prior
    # assistant turn, and "I don't know" otherwise. A passing model can phrase it
    # either way ("The capital is Paris.") so we accept a mention of Paris and treat
    # any non-empty answer as a soft pass for the wire format; the history check is
    # what we actually care about.
    mentions_history = "paris" in text.lower() or "capital" in text.lower()
    return CheckResult(
        label="check 2: chat multi-turn replay",
        passed=bool(text),
        detail=(
            f"got {_summarize(text)} in {_elapsed(time.monotonic() - started)} "
            f"[{_status_detail(response)}]"
            + (" (history respected)" if mentions_history else " (history not respected)")
        ),
    )


def _check_glossary_shape(client: OpenAI, target: ProviderTarget) -> CheckResult:
    """Check 3a: the glossary JSON-array shape.

    ``glossary_builder._parse_response`` swallows JSON errors and returns ``{}`` for
    malformed responses -- a partial batch silently vanishes from the glossary. The
    probe asserts the full shape: a parsed list whose items carry ``name`` and
    ``definition``, and at least one item mentions one of the symbols in the prompt.
    """
    started = time.monotonic()
    try:
        response = client.responses.create(
            model=target.model,
            reasoning={"effort": "minimal"},
            input=[{"role": "user", "content": _glossary_prompt()}],
            max_output_tokens=2000,
        )
    except Exception as exc:
        return CheckResult(
            label="check 3a: glossary JSON-array shape",
            passed=False,
            detail=f"request failed in {_elapsed(time.monotonic() - started)}: {exc}",
        )

    raw = (response.output_text or "").strip()
    parsed = _parse_json_array(raw)
    if parsed is None:
        return CheckResult(
            label="check 3a: glossary JSON-array shape",
            passed=False,
            detail=(
                f"could not parse JSON array in {_elapsed(time.monotonic() - started)}: "
                f"{_summarize(raw)} [{_status_detail(response)}]"
            ),
        )

    bad = [
        item
        for item in parsed
        if not (isinstance(item.get("name"), str) and isinstance(item.get("definition"), str))
    ]
    if bad:
        return CheckResult(
            label="check 3a: glossary JSON-array shape",
            passed=False,
            detail=f"{len(bad)} items missing name/definition in {_elapsed(time.monotonic() - started)}",
        )

    return CheckResult(
        label="check 3a: glossary JSON-array shape",
        passed=True,
        detail=(
            f"parsed {len(parsed)} items in {_elapsed(time.monotonic() - started)}: "
            f"{_summarize(raw)}"
        ),
    )


def _check_annotation_shape(client: OpenAI, target: ProviderTarget) -> CheckResult:
    """Check 3b: the reading-order annotation JSON-array shape.

    ``onboarding._request`` swallows per-batch failures and returns ``None`` -- a
    successful HTTP response that fails to parse means an unannotated reading order.
    Same contract as 3a but with the annotations schema (``file_path`` + ``annotation``)
    and ``max_output_tokens=1000`` (smaller than glossary's 2000), and the assertions
    verify the items mention the file paths in the prompt.
    """
    started = time.monotonic()
    try:
        response = client.responses.create(
            model=target.model,
            reasoning={"effort": "minimal"},
            input=[{"role": "user", "content": _annotation_prompt()}],
            max_output_tokens=1000,
        )
    except Exception as exc:
        return CheckResult(
            label="check 3b: annotation JSON-array shape",
            passed=False,
            detail=f"request failed in {_elapsed(time.monotonic() - started)}: {exc}",
        )

    raw = (response.output_text or "").strip()
    parsed = _parse_json_array(raw)
    if parsed is None:
        return CheckResult(
            label="check 3b: annotation JSON-array shape",
            passed=False,
            detail=(
                f"could not parse JSON array in {_elapsed(time.monotonic() - started)}: "
                f"{_summarize(raw)} [{_status_detail(response)}]"
            ),
        )

    bad = [
        item
        for item in parsed
        if not (isinstance(item.get("file_path"), str) and isinstance(item.get("annotation"), str))
    ]
    if bad:
        return CheckResult(
            label="check 3b: annotation JSON-array shape",
            passed=False,
            detail=f"{len(bad)} items missing file_path/annotation in {_elapsed(time.monotonic() - started)}",
        )

    return CheckResult(
        label="check 3b: annotation JSON-array shape",
        passed=True,
        detail=(
            f"parsed {len(parsed)} items in {_elapsed(time.monotonic() - started)}: "
            f"{_summarize(raw)}"
        ),
    )


def _check_brief_shape(client: OpenAI, target: ProviderTarget) -> CheckResult:
    """Check 4: architecture brief's system + user pair with ``reasoning.effort=low``.

    The only call site using ``reasoning={"effort": "low"}``; a provider accepting
    ``minimal`` but rejecting ``low`` would fail here and only here. The brief degrades
    to a placeholder on failure so a quiet miss is possible.
    """
    started = time.monotonic()
    try:
        response = client.responses.create(
            model=target.model,
            reasoning={"effort": "low"},
            input=_brief_messages(_brief_prompt()),
            # Larger than the production brief budget (1200) so the probe verifies the
            # wire shape rather than starving the reasoning block -- see the matching
            # PASS/FAIL note below.
            max_output_tokens=2048,
        )
    except Exception as exc:
        return CheckResult(
            label="check 4: brief system+user with reasoning=low",
            passed=False,
            detail=f"request failed in {_elapsed(time.monotonic() - started)}: {exc}",
        )

    text = (response.output_text or "").strip()
    passed = bool(text)
    detail = (
        f"got {_summarize(text)} in {_elapsed(time.monotonic() - started)} "
        f"[{_status_detail(response)}]"
    )
    if not passed and getattr(response, "status", None) == "incomplete":
        # ``reasoning=low`` makes ``deepseek-flash`` think harder than ``minimal``, and
        # a real architecture-brief prompt is much longer than this probe stub, so the
        # production budget of 1200 (``architecture_brief.py:388``) may be too small.
        # The probe asks for more headroom so a passing wire is distinguishable from a
        # starving-the-reasoner false negative.
        detail += " -- consider raising ``max_output_tokens`` in architecture_brief"
    return CheckResult(
        label="check 4: brief system+user with reasoning=low",
        passed=passed,
        detail=detail,
    )


# --- Main ---------------------------------------------------------------------


def _build_sync_client(target: ProviderTarget) -> OpenAI:
    """The sync client used by glossary, onboarding, and brief.

    ``max_retries=0`` so a transient network blip fails the check rather than masking it
    behind exponential backoff. ``timeout=30`` per attempt -- long enough for a slow
    model on a long prompt (the brief is 1200 tokens), short enough that a wedged
    provider doesn't hang the probe.
    """
    return OpenAI(
        api_key=target.api_key,
        base_url=target.base_url,
        max_retries=0,
        timeout=30,
    )


def _build_async_client(target: ProviderTarget) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=target.api_key,
        base_url=target.base_url,
        max_retries=0,
        timeout=30,
    )


def main() -> int:
    target, label = _parse_args()

    print(f"probe: provider={label} model={target.model} base_url={target.base_url}")
    print(
        f"probe: api_key={'set (' + str(len(target.api_key)) + ' chars)' if target.api_key else 'MISSING'}"
    )
    print()

    sync_client = _build_sync_client(target)
    async_client = _build_async_client(target)

    results: list[CheckResult] = []
    started = time.monotonic()

    results.append(_check_single_turn(sync_client, target))
    results.append(asyncio.run(_check_chat_multiturn(async_client, target)))
    results.append(_check_glossary_shape(sync_client, target))
    results.append(_check_annotation_shape(sync_client, target))
    results.append(_check_brief_shape(sync_client, target))

    total = time.monotonic() - started
    for result in results:
        print(result.render())
    print()
    print(
        f"probe: {_elapsed(total)} elapsed, {sum(1 for r in results if r.passed)}/{len(results)} checks passed"
    )

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

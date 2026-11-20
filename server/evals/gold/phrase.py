"""Turn question seeds into natural developer questions, once, with a leak re-check.

Change-set, rationale and structural items carry a seed and an empty question. A model that
is not the generator rewrites each seed; the result is checked again for anything that gives
the gold files away, retried once with a stricter prompt, and dropped if it still leaks.
Accepted phrasings are cached by item id, model and prompt version, so a re-run makes no
calls for them. Hand items keep their written question and are never sent to the model.

The leak re-check differs by family. A change-set seed names nothing of the gold, so the
check is the full ``leaked_terms`` one; the anchor file of an anchor item is named on
purpose and is not a gold file. Rationale and structural seeds name their subject files on
purpose (the file being asked about, or the two ends of an import chain), so those files are
allowed, and must still be present, while any other gold file, such as an importer or a
file in the middle of a chain, is a leak.
"""

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from evals.gold.changeset import IdentifierIndex, LeakContext, identifier_tokens, leaked_terms
from evals.gold.schema import GoldItem, canonical_json
from evals.models import PHRASER_MODEL

PROMPT_VERSION = "phrase-v1"
NEAR_DUPLICATE_JACCARD = 0.9
MAX_OUTPUT_TOKENS = 600
DEFAULT_CONCURRENCY = 1
EMPTY = "<empty>"

_PATH_SPAN = re.compile(r"`([^`\s]+)`")
_FILE_LIKE = re.compile(r"^[\w@.+-]+(?:/[\w@.+-]+)*\.\w+$")

_SYSTEM = (
    "You rewrite a rough note about a code change or a codebase question into the question "
    "a developer would type to a coding assistant that has the repository indexed. Rules: "
    "keep every technical requirement and detail in the note; do not invent files, "
    "functions or facts; do not add any file path that is not already in the note; write "
    "one or two sentences for a change request or a history question; never say that the "
    "text was rewritten. Reply with the question only."
)
_STRICT = (
    " Your earlier attempt revealed something it must not. Describe the work in general "
    "terms: no file names, no paths and no function, class or variable names beyond those "
    "that appear in the note itself."
)


@dataclass(frozen=True)
class PhraseDrop:
    """An item that did not survive phrasing.

    Attributes:
        item_id: The dropped item's id.
        reason: ``leak``, ``empty``, ``duplicate_exact`` or ``duplicate_near``.
        detail: The leaked terms, or the id of the item that was kept instead.
    """

    item_id: str
    reason: str
    detail: str = ""


@dataclass
class PhraseResult:
    """What phrasing produced.

    Attributes:
        items: The surviving items, ``question`` filled and ``id`` unchanged.
        drops: Every dropped item with its reason.
        calls: Model calls made.
        cached: Items served from the cache without a call.
    """

    items: list[GoldItem] = field(default_factory=list)
    drops: list[PhraseDrop] = field(default_factory=list)
    calls: int = 0
    cached: int = 0


ClientFactory = Callable[[], Any]
LeakContextFactory = Callable[[GoldItem], LeakContext]


def make_leak_context_factory(clone: Path, base_commit: str) -> LeakContextFactory:
    """Build the per-item leak context the way the change-set builder does.

    Args:
        clone: A clone containing ``base_commit``.
        base_commit: The commit the gold files are read at.

    Returns:
        A function from an item to its gold paths and gold-unique identifier test.
    """

    def factory(item: GoldItem) -> LeakContext:
        index = IdentifierIndex(clone, base_commit, item.gold_files)
        return LeakContext(gold_paths=item.gold_files, is_gold_unique=index.is_gold_unique)

    return factory


def named_files(item: GoldItem) -> tuple[str, ...]:
    """The files an item's seed names on purpose, which a phrasing must keep.

    Args:
        item: A gold item.

    Returns:
        The anchor file of an anchor item; the subject file of a rationale item; the files
        quoted in backticks in a structural seed. Empty for blind change-set and hand items.
    """
    if item.family == "changeset":
        return (item.anchor_file,) if item.anchor_file else ()
    if item.family == "rationale":
        return item.gold_files
    if item.family == "structural":
        return tuple(
            dict.fromkeys(
                span for span in _PATH_SPAN.findall(item.question_seed) if _FILE_LIKE.match(span)
            )
        )
    return ()


def _problems(item: GoldItem, text: str, context: LeakContext) -> list[str]:
    """Return what is wrong with a phrased question; empty means it is acceptable."""
    if not text.strip():
        return [EMPTY]
    named = named_files(item)
    named_basenames = {PurePosixPath(path).name for path in named}
    seed_tokens = set(identifier_tokens(item.question_seed))
    narrowed = LeakContext(
        gold_paths=tuple(
            path
            for path in context.gold_paths
            if path not in named and PurePosixPath(path).name not in named_basenames
        ),
        is_gold_unique=lambda token: token not in seed_tokens and context.is_gold_unique(token),
    )
    problems = leaked_terms(text, narrowed)
    problems.extend(f"<dropped {path}>" for path in named if path not in text)
    return problems


def _prompt(item: GoldItem, *, strict: bool, previous: list[str]) -> list[dict[str, str]]:
    """The messages sent for one item."""
    system = _SYSTEM + (_STRICT if strict else "")
    note = f"Note:\n{item.question_seed}"
    avoid = [term for term in previous if not term.startswith("<")]
    if strict and avoid:
        note += "\n\nDo not use any of these: " + ", ".join(avoid)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": note},
    ]


def _clean(text: str) -> str:
    """Trim whitespace and a pair of wrapping quotes from a model reply."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _cache_key(item_id: str, model: str) -> str:
    return f"{item_id}|{model}|{PROMPT_VERSION}"


def _read_cache(path: Path) -> dict[str, str]:
    """Read the phrasing cache; later lines win."""
    cache: dict[str, str] = {}
    if not path.exists():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            cache[record["key"]] = record["question"]
    return cache


def _append_cache(path: Path, *, item: GoldItem, model: str, question: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "item_id": item.id,
        "key": _cache_key(item.id, model),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "question": question,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(record) + "\n")


def normalise_question(text: str) -> str:
    """Lower-case, replace punctuation with spaces and collapse whitespace."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def dedupe_questions(items: list[GoldItem]) -> tuple[list[GoldItem], list[PhraseDrop]]:
    """Remove exact and near-duplicate questions within each repository.

    Two items of one cluster (the blind and anchor variants of a pull request) differ only
    by a sentence and are never compared with each other. Among duplicates the item with
    the smaller id is kept.

    Args:
        items: Items whose ``question`` is filled.

    Returns:
        The kept items, in id order, and a drop for each removed one.
    """
    kept: dict[str, list[tuple[GoldItem, str, set[str]]]] = defaultdict(list)
    drops: list[PhraseDrop] = []
    for item in sorted(items, key=lambda candidate: candidate.id):
        text = normalise_question(item.question)
        tokens = set(text.split())
        duplicate: tuple[str, str] | None = None
        for other, other_text, other_tokens in kept[item.repo]:
            if item.cluster is not None and item.cluster == other.cluster:
                continue
            if text == other_text:
                duplicate = ("duplicate_exact", other.id)
                break
            if _jaccard(tokens, other_tokens) >= NEAR_DUPLICATE_JACCARD:
                duplicate = ("duplicate_near", other.id)
                break
        if duplicate is None:
            kept[item.repo].append((item, text, tokens))
        else:
            drops.append(PhraseDrop(item.id, duplicate[0], duplicate[1]))
    survivors = sorted(
        (entry[0] for entries in kept.values() for entry in entries),
        key=lambda candidate: candidate.id,
    )
    return survivors, drops


async def _ask(
    client: Any, model: str, messages: list[dict[str, str]], api_style: str = "responses"
) -> str:
    """One call over the Responses API or chat completions; a failed call is an empty reply."""
    try:
        if api_style == "chat":
            response = await client.chat.completions.create(
                model=model, messages=messages, max_tokens=MAX_OUTPUT_TOKENS
            )
            choices = getattr(response, "choices", None) or []
            return _clean((choices[0].message.content if choices else "") or "")
        response = await client.responses.create(
            model=model, input=messages, max_output_tokens=MAX_OUTPUT_TOKENS
        )
        return _clean(response.output_text or "")
    except Exception:
        return ""


async def phrase_items(
    items: list[GoldItem],
    *,
    client_factory: ClientFactory,
    model: str = PHRASER_MODEL,
    cache_path: Path,
    leak_context: LeakContextFactory,
    concurrency: int = DEFAULT_CONCURRENCY,
    api_style: str = "responses",
) -> PhraseResult:
    """Phrase every seed as a developer question.

    Args:
        items: Items from a gold build; hand items keep their written question.
        client_factory: Builds the model client, called once.
        model: The phraser model id; part of the cache key.
        cache_path: The ``phrased.jsonl`` cache; accepted phrasings are appended as they
            are made, so an interrupted run resumes.
        leak_context: Builds an item's leak context (its gold paths and identifier test).
        concurrency: How many items are phrased at once.
        api_style: ``responses`` for the Responses API or ``chat`` for chat completions.

    Returns:
        The phrased items with the duplicates removed, and every drop with its reason.
    """
    result = PhraseResult()
    cache = _read_cache(cache_path)
    client = client_factory()
    gate = asyncio.Semaphore(max(1, concurrency))
    phrased: dict[str, GoldItem] = {}

    async def one(item: GoldItem) -> None:
        if item.family == "hand":
            phrased[item.id] = item
            return
        context = leak_context(item)
        cached = cache.get(_cache_key(item.id, model))
        if cached is not None and not _problems(item, cached, context):
            result.cached += 1
            phrased[item.id] = item.model_copy(update={"question": cached})
            return
        problems: list[str] = []
        async with gate:
            for strict in (False, True):
                text = await _ask(
                    client, model, _prompt(item, strict=strict, previous=problems), api_style
                )
                result.calls += 1
                problems = _problems(item, text, context)
                if not problems:
                    _append_cache(cache_path, item=item, model=model, question=text)
                    phrased[item.id] = item.model_copy(update={"question": text})
                    return
        reason = "empty" if problems == [EMPTY] else "leak"
        result.drops.append(PhraseDrop(item.id, reason, ", ".join(problems)))

    await asyncio.gather(*(one(item) for item in items))
    kept, duplicates = dedupe_questions(list(phrased.values()))
    result.items = kept
    result.drops.extend(duplicates)
    result.drops.sort(key=lambda drop: (drop.reason, drop.item_id))
    return result

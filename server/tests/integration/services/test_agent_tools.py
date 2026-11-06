"""The agent's tools against the retrieval fixture, plus the checks that cover every tool.

Two copies of the fixture repository are seeded once per module. The tests ask
about copy A; copy B has the same paths and names and a marker in its free text,
so a tool that reads the wrong repository shows the marker. Each tool has one
test with a known answer. The registry-wide tests at the bottom run over
whatever is registered, so a new tool is covered by them as soon as it has an
entry in ``EXAMPLES``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.services.agent.tools import REGISTRY, ToolContext, ToolResult
from app.services.agent.tools.output import ListOutput
from tests.factories import make_user
from tests.fixtures.agent_tools import (
    MARKER,
    SECURITY,
    ToolRepos,
    make_tool_context,
    seed_tool_repos,
    session_factory_for,
)
from tests.fixtures.retrieval import rolled_back_session

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SECURITY_SOURCE = "def verify_password(plain, hashed):\n    return bcrypt.checkpw(plain, hashed)\n"

# One working call per tool. The registry-wide tests at the bottom run these.
EXAMPLES: dict[str, dict[str, Any]] = {
    "search_code": {"query": "Where is `verify_password` defined?", "k": 5},
    "search_symbols": {"name": "verify_password"},
    "grep_code": {"pattern": "def verify_password"},
    "list_files": {"path_prefix": "app/auth/"},
    "list_symbols": {"path": SECURITY},
    "read_symbol": {"name": "verify_password"},
    "read_file": {"path": SECURITY},
    "get_importers": {"path": SECURITY},
    "get_importees": {"path": "app/users/service.py"},
    "find_path": {"source": "app/users/routes.py", "target": SECURITY},
    "get_cochanged": {"path": "app/jobs/retry.py"},
    "search_history": {"query": "why was password hashing switched to bcrypt"},
    "get_file_info": {"path": SECURITY},
    "get_glossary": {"term": "password"},
    "get_overview": {},
    "finish": {"answer": "It is in app/auth/security.py [F:app/auth/security.py]."},
}


@dataclass
class Env:
    factory: async_sessionmaker
    repos: ToolRepos


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env(engine):
    """Seeds both repositories once, on a session that is rolled back at the end."""
    with pytest.MonkeyPatch.context() as patch:
        # A key in a developer's environment must not turn on the model-backed stages.
        patch.setattr(settings, "OPENROUTER_API_KEY", "")
        patch.setattr(settings, "COHERE_API_KEY", "")
        async with rolled_back_session(engine) as db:
            repos = await seed_tool_repos(db, await make_user(db))
            yield Env(factory=session_factory_for(db.bind), repos=repos)


@pytest.fixture(autouse=True)
def github():
    """Every file request is answered with the same small Python file."""
    with respx.mock(assert_all_called=False) as router:
        router.get(url__regex=r"https://api\.github\.com/repos/.+/contents/.+").respond(
            200, content=SECURITY_SOURCE.encode()
        )
        yield router


@pytest.fixture
def ctx_a(env) -> ToolContext:
    return make_tool_context(env.factory, env.repos.a.repo)


def context_b(env) -> ToolContext:
    return make_tool_context(env.factory, env.repos.b.repo)


async def call(ctx: ToolContext, tool: str, /, **arguments: Any) -> ToolResult:
    return await REGISTRY.call(tool, arguments, ctx)


async def ok(ctx: ToolContext, tool: str, /, **arguments: Any) -> dict[str, Any]:
    """The JSON output of a call that must succeed."""
    result = await call(ctx, tool, **arguments)
    assert result.status == "ok", result.text
    assert result.data is not None
    return result.data


# --- one test per tool ----------------------------------------------------------


async def test_search_code_runs_the_preset_pipeline(ctx_a):
    data = await ok(ctx_a, "search_code", query="Where is `verify_password` defined?", k=5)

    top = data["items"][0]
    assert top["path"] == SECURITY
    assert top["key"].startswith(f"F:{SECURITY}:")
    assert top["symbol_id"] is not None
    assert len(data["items"]) <= 5

    history = await ok(
        ctx_a, "search_code", query="switch password hashing to bcrypt", source_types=["commit"]
    )
    assert history["items"]
    assert {hit["source_type"] for hit in history["items"]} == {"commit"}


async def test_search_symbols_finds_exact_and_near_names(ctx_a):
    exact = await ok(ctx_a, "search_symbols", name="verify_password")
    assert exact["items"][0]["path"] == SECURITY
    assert exact["items"][0]["start_line"] == 4

    camel = await ok(ctx_a, "search_symbols", name="getUserById", kind="function")
    assert [hit["path"] for hit in camel["items"]] == ["app/users/service.py"]

    classes = await ok(ctx_a, "search_symbols", name="verify_password", kind="class")
    assert {hit["kind"] for hit in classes["items"]} <= {"class"}
    assert "verify_password" not in {hit["name"] for hit in classes["items"]}


async def test_grep_code_reports_file_line_numbers_and_counts(ctx_a):
    data = await ok(ctx_a, "grep_code", pattern=r"bcrypt\.checkpw")
    (group,) = data["items"]
    assert group["symbol_name"] == "verify_password"
    assert (group["lines"][0]["line"], group["lines"][0]["text"]) == (
        6,
        "    return bcrypt.checkpw(plain.encode(), hashed)",
    )

    limited = await call(ctx_a, "grep_code", pattern="plain", max_results=1)
    assert (limited.data["returned"], limited.data["total"]) == (1, 2)
    assert "1 of 2 matching symbols" in limited.text

    scoped = await ok(ctx_a, "grep_code", pattern="plain", path_glob="app/users/*")
    assert scoped["items"] == []


async def test_grep_code_reaches_the_body_of_a_function_too_long_to_embed(ctx_a):
    data = await ok(ctx_a, "grep_code", pattern="LEGACY_PRORATION_CUTOFF")

    assert {line["path"] for g in data["items"] for line in g["lines"]} == {
        "app/billing/statements.py"
    }


async def test_list_files_browses_by_prefix_and_language(ctx_a):
    auth = await call(ctx_a, "list_files", path_prefix="app/auth/")
    paths = [item["path"] for item in auth.data["items"]]
    assert paths == sorted(paths)
    assert SECURITY in paths
    assert all(p.startswith("app/auth/") for p in paths)

    page = await call(ctx_a, "list_files", limit=3)
    assert (page.data["returned"], page.data["total"]) == (3, 30)
    assert "3 of 30 files" in page.text

    assert (await ok(ctx_a, "list_files", language="Python", limit=1))["total"] == 30


async def test_list_symbols_outlines_a_file(ctx_a):
    data = await ok(ctx_a, "list_symbols", path=SECURITY)
    names = {(s["kind"], s["name"]) for s in data["items"]}
    assert ("function", "verify_password") in names
    assert all(s["kind"] != "import" for s in data["items"])

    missing = await call(ctx_a, "list_symbols", path="app/nope.py")
    assert "No file at `app/nope.py`" in missing.text


async def test_read_symbol_returns_a_numbered_body_by_name_or_id(ctx_a):
    by_name = await ok(ctx_a, "read_symbol", name="verify_password")
    (symbol,) = by_name["items"]
    assert symbol["source"].splitlines()[2].lstrip().startswith("6  ")
    assert "bcrypt.checkpw" in symbol["source"]

    by_id = await ok(ctx_a, "read_symbol", symbol_id=symbol["symbol_id"])
    assert by_id["items"][0]["key"] == symbol["key"]

    for arguments in ({}, {"name": "verify_password", "symbol_id": symbol["symbol_id"]}):
        refused = await call(ctx_a, "read_symbol", **arguments)
        assert refused.status == "invalid_arguments"
        assert "exactly one of `name` and `symbol_id`" in refused.text


async def test_read_symbol_reads_a_function_the_index_skipped(ctx_a):
    data = await ok(ctx_a, "read_symbol", name="rebuild_monthly_statements")

    assert "LEGACY_PRORATION_CUTOFF" in data["items"][0]["source"]


async def test_get_importers_looks_through_the_barrel(ctx_a):
    data = await ok(ctx_a, "get_importers", path=SECURITY, limit=50)

    paths = {item["path"] for item in data["items"]}
    assert {"app/users/service.py", "app/deps.py", "tests/test_auth.py"} <= paths
    assert "app/auth/__init__.py" not in paths


async def test_get_importees_lists_what_a_file_imports(ctx_a):
    data = await ok(ctx_a, "get_importees", path="app/users/service.py")

    assert {item["path"] for item in data["items"]} == {
        "app/users/models.py",
        SECURITY,
        "app/utils/dates.py",
    }


async def test_find_path_tries_both_directions(ctx_a):
    forward = await ok(ctx_a, "find_path", source="app/users/routes.py", target=SECURITY)
    assert forward["hops"] == 2
    assert forward["path"] == ["app/users/routes.py", "app/users/service.py", SECURITY]

    backward = await ok(ctx_a, "find_path", source=SECURITY, target="app/users/routes.py")
    assert backward["direction"] == "target_imports_source"
    assert backward["path"] == forward["path"][::-1]

    none = await call(ctx_a, "find_path", source="tests/test_pricing.py", target=SECURITY)
    assert none.data["found"] is False
    assert "within 4 steps" in none.text

    short = await call(
        ctx_a, "find_path", source="app/users/routes.py", target=SECURITY, max_depth=1
    )
    assert short.data["found"] is False


async def test_get_cochanged_lists_partners_strongest_first(ctx_a):
    data = await ok(ctx_a, "get_cochanged", path="app/jobs/retry.py")

    assert [p["path"] for p in data["items"]] == ["app/billing/webhooks.py"]
    assert data["items"][0]["together"] == 2


async def test_search_history_filters_by_kind_and_path(ctx_a):
    both = await ok(ctx_a, "search_history", query="why was password hashing switched to bcrypt")
    assert {"PR:12"} <= {hit["key"] for hit in both["items"]}

    prs = await ok(ctx_a, "search_history", query="password hashing bcrypt", kind="pr")
    assert {hit["kind"] for hit in prs["items"]} == {"pull_request"}

    touching = await call(
        ctx_a, "search_history", query="password hashing bcrypt", path="app/users/service.py"
    )
    assert {hit["kind"] for hit in touching.data["items"]} == {"commit"}
    assert "pull requests were left out" in touching.text


async def test_get_file_info_merges_ownership_and_reading_order(ctx_a):
    data = await ok(ctx_a, "get_file_info", path=SECURITY)

    assert data["primary_owner"] == "Grace Hopper"
    assert data["bus_factor"] == 2
    assert data["reading_order_position"] == 1
    assert data["reading_note"] == "Start here: password hashing."
    assert data["fan_in"] > 0

    missing = await call(ctx_a, "get_file_info", path="app/nope.py")
    assert "No file at `app/nope.py`" in missing.text


async def test_get_glossary_matches_terms(ctx_a):
    data = await ok(ctx_a, "get_glossary", term="PASSWORD")

    assert [item["name"] for item in data["items"]] == ["password hashing"]
    assert (await ok(ctx_a, "get_glossary", term="zzz"))["total"] == 0


async def test_get_overview_reports_the_brief(ctx_a):
    result = await call(ctx_a, "get_overview")

    assert result.data["narrative"] == "A small web API with auth, billing and jobs."
    assert result.data["entry_points"] == ["app/main.py"]
    assert "1 of 1 critical files" in result.text


async def test_finish_returns_the_answer(ctx_a):
    data = await ok(ctx_a, "finish", answer="Done [C:a1b2c3d4].", confidence_note=None)

    assert data["answer"] == "Done [C:a1b2c3d4]."


async def test_a_tool_called_through_a_strict_schema_gets_nulls_for_omitted_arguments(ctx_a):
    data = await ok(ctx_a, "list_files", path_prefix="app/auth/", language=None, limit=None)

    assert data["total"] > 0


# --- every registered tool ------------------------------------------------------------


async def test_every_tool_has_an_example():
    assert set(EXAMPLES) == set(REGISTRY.names())


LIST_TOOLS = sorted(
    name for name in EXAMPLES if issubclass(REGISTRY.get(name).output_model, ListOutput)
)


def _duplicates(data: dict[str, Any]) -> bool:
    items = [json.dumps(item, sort_keys=True) for item in data.get("items", [])]
    return len(items) != len(set(items))


@pytest.mark.parametrize("name", sorted(EXAMPLES))
async def test_a_tool_asked_about_one_repository_never_returns_the_others_rows(name, ctx_a):
    result = await call(ctx_a, name, **EXAMPLES[name])

    assert result.status == "ok", result.text
    assert MARKER not in result.text
    assert MARKER not in json.dumps(result.data)
    # A join on path instead of repository would return each row twice.
    assert not _duplicates(result.data)


async def test_the_second_repository_really_holds_the_marker(env):
    """Without this, the isolation test above could pass on a fixture with nothing to leak."""
    ctx = context_b(env)
    carrying = ["search_code", "grep_code", "read_symbol", "search_history"]
    carrying += ["get_file_info", "get_glossary", "get_overview"]

    for name in carrying:
        result = await call(ctx, name, **EXAMPLES[name])
        assert MARKER in result.text, name


@pytest.mark.parametrize("name", sorted(EXAMPLES))
async def test_repository_text_is_fenced_and_every_block_is_closed(name, ctx_a):
    result = await call(ctx_a, name, **EXAMPLES[name])
    output = REGISTRY.get(name).output_model

    opened = re.findall(
        r'<source key="[^"]+" type="[^"]+" provenance="(repo|history)">', result.text
    )
    assert result.text.count("<source ") == len(opened)
    assert result.text.count("</source>") == len(opened)
    assert bool(opened) == output.carries_repo_text, name


@pytest.mark.parametrize("name", LIST_TOOLS)
async def test_a_list_result_says_how_many_of_how_many(name, ctx_a):
    result = await call(ctx_a, name, **EXAMPLES[name])

    assert re.search(r"\b\d+ of \d+\b", result.text), result.text


@pytest.mark.parametrize("name", sorted(EXAMPLES))
async def test_a_tool_names_its_nodes_or_none(name, ctx_a):
    from app.services.agent.tools import NodeEvent

    result = await call(ctx_a, name, **EXAMPLES[name])

    assert result.nodes is None or isinstance(result.nodes, NodeEvent)

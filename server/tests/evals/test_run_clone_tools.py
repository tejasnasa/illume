"""The clone-backed registry: ``read_file`` serves the clone at the base commit, offline."""

import pytest
import respx

from app.services.agent.tools import REGISTRY
from app.services.agent.tools.read_file import MAX_LINES_PER_CALL
from evals.run.clone_tools import READ_FILE, build_clone_registry
from tests.factories import make_file, make_repo, make_user
from tests.fixtures import sample_repo
from tests.fixtures.agent_tools import make_tool_context, session_factory_for

pytestmark = pytest.mark.integration

PATH = "src/app.py"
OTHER = "src/other.py"
GONE = "src/gone.py"
BASE_TEXT = "".join(f"base line {n}\n" for n in range(1, 6))
LATER_TEXT = "changed after the base commit\n"
CONTENTS = r"https://api\.github\.com/repos/example/example-repo/contents/.+"


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    """A tiny repository: ``src/app.py`` at the base commit and changed one commit later."""
    root = tmp_path_factory.mktemp("clone-tools")
    sample_repo._git(root, "init", "-q", "-b", "main")
    (root / "src").mkdir()
    (root / PATH).write_text(BASE_TEXT, encoding="utf-8")
    (root / OTHER).write_text("other\n", encoding="utf-8")
    sample_repo.commit_all(root, "base")
    base = sample_repo.head_sha(root)
    (root / PATH).write_text(LATER_TEXT, encoding="utf-8")
    sample_repo.commit_all(root, "later")
    return root, base


@pytest.fixture
async def repo(db_session):
    repo = await make_repo(db_session, await make_user(db_session))
    for path in (PATH, OTHER, GONE):
        await make_file(db_session, repo, path=path)
    return repo


@pytest.fixture
def ctx(db_session, repo):
    return make_tool_context(session_factory_for(db_session.bind), repo)


@pytest.fixture
def registry(clone):
    root, base = clone
    return build_clone_registry(root, base)


@pytest.fixture
def no_network():
    """Any HTTP request fails: the router has no routes and rejects unmocked calls."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


class TestRegistry:
    def test_every_product_tool_is_present_in_the_same_order(self, registry):
        assert registry.names() == REGISTRY.names()

    def test_read_file_keeps_its_name_schema_and_flags(self, registry):
        ours, product = registry.get(READ_FILE), REGISTRY.get(READ_FILE)
        assert ours.handler is not product.handler
        for field in (
            "name",
            "description",
            "input_model",
            "output_model",
            "cost",
            "timeout_s",
            "expose_to_agent",
            "emits_nodes",
        ):
            assert getattr(ours, field) == getattr(product, field), field
        assert registry.function_tools() == REGISTRY.function_tools()

    def test_the_other_tools_are_the_products_own(self, registry):
        for name in REGISTRY.names():
            if name != READ_FILE:
                assert registry.get(name) is REGISTRY.get(name)

    def test_the_products_registry_is_not_modified(self, registry):
        assert REGISTRY.get(READ_FILE).handler is not registry.get(READ_FILE).handler
        assert len(REGISTRY) == len(registry)


class TestReading:
    async def test_the_file_is_served_as_it_was_at_the_base_commit(self, registry, ctx, no_network):
        result = await registry.call(READ_FILE, {"path": PATH}, ctx)

        assert result.status == "ok"
        assert result.data["status"] == "ok"
        assert "base line 3" in result.text
        assert "changed after" not in result.text
        assert result.data["total_lines"] == 5
        assert no_network.calls.call_count == 0

    async def test_a_window_is_numbered_like_the_products(self, registry, ctx, no_network):
        result = await registry.call(READ_FILE, {"path": PATH, "start_line": 2, "end_line": 3}, ctx)

        assert result.data["start_line"] == 2 and result.data["end_line"] == 3
        assert result.text.startswith(f"{PATH} lines 2 to 3 of 5; call again with start_line=4")
        assert "2  base line 2" in result.text and "3  base line 3" in result.text

    async def test_a_start_past_the_end_is_out_of_range(self, registry, ctx, no_network):
        result = await registry.call(READ_FILE, {"path": PATH, "start_line": 9}, ctx)
        assert result.data["status"] == "out_of_range"

    async def test_at_most_one_window_of_lines_comes_back(self, repo, db_session, tmp_path):
        root = tmp_path / "big"
        root.mkdir()
        sample_repo._git(root, "init", "-q", "-b", "main")
        (root / "src").mkdir()
        (root / PATH).write_text("x\n" * (MAX_LINES_PER_CALL + 50), encoding="utf-8")
        sample_repo.commit_all(root, "big")
        registry = build_clone_registry(root, sample_repo.head_sha(root))
        ctx = make_tool_context(session_factory_for(db_session.bind), repo)

        result = await registry.call(READ_FILE, {"path": PATH}, ctx)

        assert result.data["end_line"] == MAX_LINES_PER_CALL
        assert result.data["total_lines"] == MAX_LINES_PER_CALL + 50

    @pytest.mark.parametrize("path", ["../etc/passwd", "src\\app.py", "/etc/passwd", "src//app.py"])
    async def test_an_unsafe_path_is_refused(self, registry, ctx, no_network, path):
        result = await registry.call(READ_FILE, {"path": path}, ctx)
        assert result.data["status"] == "refused_path"

    async def test_a_path_that_was_not_ingested_is_not_in_the_repository(
        self, registry, ctx, no_network
    ):
        result = await registry.call(READ_FILE, {"path": "src/never.py"}, ctx)
        assert result.data["status"] == "not_in_repository"
        assert "list_files" in result.text

    async def test_a_recorded_file_missing_from_the_clone_is_unavailable(
        self, registry, ctx, no_network
    ):
        result = await registry.call(READ_FILE, {"path": GONE}, ctx)
        assert result.status == "ok"
        assert result.data["status"] == "unavailable"
        assert no_network.calls.call_count == 0


class TestParityWithTheProduct:
    """The same arguments give the same output as the product's handler over the same text."""

    @pytest.mark.parametrize(
        "arguments",
        [
            {"path": PATH},
            {"path": PATH, "start_line": 2},
            {"path": PATH, "start_line": 2, "end_line": 4},
            {"path": PATH, "start_line": 40},
            {"path": "src/never.py"},
            {"path": "../x"},
        ],
    )
    async def test_outputs_match(self, registry, ctx, arguments):
        with respx.mock(assert_all_called=False) as github:
            github.get(url__regex=CONTENTS).respond(200, content=BASE_TEXT.encode())
            product = await REGISTRY.call(READ_FILE, arguments, ctx)
        ours = await registry.call(READ_FILE, arguments, ctx)

        assert ours.status == product.status
        assert ours.text == product.text
        assert ours.data == product.data

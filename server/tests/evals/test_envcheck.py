"""Unit tests for the eval isolation helpers."""

from pathlib import Path

import pytest

from evals.envcheck import (
    ENV_EVAL_KEYS,
    EVAL_SETTINGS_FIELDS,
    EvalIsolationError,
    assert_eval_url,
    eval_environment,
    mask_url,
    read_env_eval,
    uncovered_fields,
)

pytestmark = pytest.mark.unit


class TestAssertEvalUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://illume:eval@localhost:5432/illume_eval",
            "postgresql://illume:test@localhost:5433/illume_test",
            "postgresql+asyncpg://illume:test@localhost:5433/illume_test",
            "postgresql://illume:eval@localhost/illume_eval",
            "postgresql://illume:eval@db.example.com:5434/illume_eval",
            "postgresql://illume:eval@10.0.0.5:5434/illume_eval",
        ],
    )
    def test_rejects_database_urls_off_the_eval_stack(self, url):
        with pytest.raises(EvalIsolationError):
            assert_eval_url(url, kind="database")

    @pytest.mark.parametrize(
        "url",
        [
            "redis://localhost:6379/0",
            "redis://localhost:6380/0",
            "redis://localhost/0",
            "redis://cache.example.com:6381/0",
        ],
    )
    def test_rejects_redis_urls_off_the_eval_stack(self, url):
        with pytest.raises(EvalIsolationError):
            assert_eval_url(url, kind="redis")

    def test_rejects_a_redis_port_for_a_database(self):
        with pytest.raises(EvalIsolationError):
            assert_eval_url("postgresql://illume:eval@localhost:6381/x", kind="database")

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
    def test_accepts_the_eval_ports(self, host):
        assert_eval_url(f"postgresql://illume:eval@{host}:5434/illume_eval", kind="database")
        assert_eval_url(f"postgresql+asyncpg://u:p@{host}:5434/x", kind="database")
        assert_eval_url(f"redis://{host}:6381/0", kind="redis")


class TestEvalEnvironment:
    def test_covers_exactly_the_declared_fields(self):
        assert set(eval_environment({})) == set(EVAL_SETTINGS_FIELDS)

    def test_keys_come_from_the_mapping_and_default_to_empty(self):
        env = eval_environment({"OPENAI_API_KEY": "sk-x", "AI_BASE_URL": "http://h"})
        assert env["OPENAI_API_KEY"] == "sk-x"
        assert env["AI_BASE_URL"] == "http://h"
        assert env["AI_API_KEY"] == ""
        assert env["OPENROUTER_API_KEY"] == ""

    def test_github_token_is_never_exported(self):
        assert "GITHUB_TOKEN" not in eval_environment({"GITHUB_TOKEN": "ghp_x"})

    def test_uncovered_fields_reports_the_difference(self):
        assert uncovered_fields([*EVAL_SETTINGS_FIELDS, "NEW_FIELD"]) == {"NEW_FIELD"}
        assert uncovered_fields(EVAL_SETTINGS_FIELDS) == set()


class TestReadEnvEval:
    def test_missing_file_is_empty(self, tmp_path: Path):
        assert read_env_eval(tmp_path / "nope") == {}

    def test_parses_comments_blanks_quotes_and_export(self, tmp_path: Path):
        path = tmp_path / ".env.eval"
        path.write_text(
            "# comment\n"
            "\n"
            "OPENAI_API_KEY=plain\n"
            'AI_API_KEY="double quoted"\n'
            "AI_BASE_URL='single quoted'\n"
            "export OPENROUTER_API_KEY = spaced\n"
            "GITHUB_TOKEN=\n"
        )
        assert read_env_eval(path) == {
            "OPENAI_API_KEY": "plain",
            "AI_API_KEY": "double quoted",
            "AI_BASE_URL": "single quoted",
            "OPENROUTER_API_KEY": "spaced",
            "GITHUB_TOKEN": "",
        }

    def test_value_may_contain_equals(self, tmp_path: Path):
        path = tmp_path / ".env.eval"
        path.write_text("AI_BASE_URL=http://h/?a=b\n")
        assert read_env_eval(path) == {"AI_BASE_URL": "http://h/?a=b"}

    def test_unknown_key_raises(self, tmp_path: Path):
        path = tmp_path / ".env.eval"
        path.write_text("OPENAI_API_KY=typo\n")
        with pytest.raises(EvalIsolationError, match="unknown key"):
            read_env_eval(path)

    def test_line_without_equals_raises(self, tmp_path: Path):
        path = tmp_path / ".env.eval"
        path.write_text("OPENAI_API_KEY\n")
        with pytest.raises(EvalIsolationError, match="KEY=VALUE"):
            read_env_eval(path)

    def test_the_example_file_parses_and_lists_every_key(self):
        example = Path(__file__).resolve().parents[2] / "evals" / ".env.eval.example"
        assert read_env_eval(example) == dict.fromkeys(ENV_EVAL_KEYS, "")


class TestMaskUrl:
    def test_masks_the_password(self):
        masked = mask_url("postgresql://illume:s3cret@localhost:5434/illume_eval")
        assert masked == "postgresql://illume:***@localhost:5434/illume_eval"

    def test_url_without_a_password_is_unchanged(self):
        assert mask_url("redis://localhost:6381/0") == "redis://localhost:6381/0"

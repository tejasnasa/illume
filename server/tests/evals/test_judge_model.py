"""The DeepEval judge adapter: structured output, metering and the pieces DeepEval relies on."""

import asyncio

import pytest
import respx
from deepeval.metrics.faithfulness.schema import Claims, Verdicts

from evals.run.judge_model import (
    JudgeModelError,
    JudgeOutputError,
    MeteredJudgeModel,
    strict_schema,
)
from tests.evals.judge_helpers import FakeJudge, endpoint

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_network():
    with respx.mock(assert_all_mocked=True, assert_all_called=False):
        yield


def ask(model, prompt="p", schema=Claims):
    return asyncio.run(model.a_generate(prompt, schema=schema))


class TestStructuredOutput:
    def test_a_reply_becomes_a_validated_instance_of_the_schema(self):
        client = FakeJudge({"Claims": {"claims": ["a", "b"]}})

        result = ask(MeteredJudgeModel(client, endpoint()))

        assert isinstance(result, Claims) and result.claims == ["a", "b"]
        request = client.requests[0]
        assert request["text"]["format"]["type"] == "json_schema"
        assert request["text"]["format"]["name"] == "Claims"
        assert request["text"]["format"]["strict"] is True
        assert request["input"] == [{"role": "user", "content": "p"}]

    def test_fenced_json_is_accepted(self):
        client = FakeJudge({"Claims": '```json\n{"claims": ["x"]}\n```'})

        assert ask(MeteredJudgeModel(client, endpoint())).claims == ["x"]

    @pytest.mark.parametrize("reply", ["not json", '{"claims": "nope"}', "{}", ""])
    def test_output_that_does_not_fit_the_schema_is_an_error(self, reply):
        model = MeteredJudgeModel(FakeJudge({"Claims": reply}), endpoint())

        with pytest.raises(JudgeOutputError, match="unusable for Claims"):
            ask(model)

    def test_no_schema_means_plain_text(self):
        client = FakeJudge({"reply": "hello"})

        text = asyncio.run(MeteredJudgeModel(client, endpoint()).a_generate("p"))

        assert text == "hello" and "text" not in client.requests[0]

    def test_the_chat_transport_asks_for_a_json_object_with_the_schema_in_the_prompt(self):
        client = FakeJudge({"Claims": {"claims": ["c"]}})
        model = MeteredJudgeModel(client, endpoint(api_style="chat"))

        result = ask(model)

        assert result.claims == ["c"]
        request = client.requests[0]
        assert request["response_format"] == {"type": "json_object"}
        assert '"title": "Claims"' in request["messages"][0]["content"]


class TestMetering:
    def test_every_call_that_reports_usage_is_kept_in_order_under_the_requested_model(self):
        client = FakeJudge()
        model = MeteredJudgeModel(client, endpoint())

        ask(model)
        ask(model, schema=Verdicts)

        assert model.calls == 2 and len(model.usages) == 2 and model.unmetered == 0
        for usage in model.usages:
            assert (usage.kind, usage.provider, usage.model) == ("judge", "openai", "gpt-6-luna")
            assert (usage.input_tokens, usage.output_tokens) == (1000, 50)
        assert model.reported_models == {"reported-judge-model"}

    def test_chat_usage_is_read_from_prompt_and_completion_tokens(self):
        model = MeteredJudgeModel(
            FakeJudge(), endpoint("m", "https://api.example.org/v1", api_style="chat")
        )

        ask(model)

        (usage,) = model.usages
        assert (usage.input_tokens, usage.output_tokens, usage.provider) == (
            1000,
            50,
            "api.example.org",
        )
        assert model.reported_models == {"reported-chat-model"}

    def test_a_call_without_usage_is_counted_as_unmetered(self):
        model = MeteredJudgeModel(FakeJudge(report_usage=False), endpoint())

        ask(model)

        assert model.usages == [] and model.unmetered == 1 and model.calls == 1

    def test_a_call_that_fails_still_counts_and_the_error_propagates(self):
        model = MeteredJudgeModel(FakeJudge(error=RuntimeError("down")), endpoint())

        with pytest.raises(RuntimeError, match="down"):
            ask(model)

        assert model.calls == 1 and model.usages == []

    def test_a_provider_that_rejects_structured_output_is_asked_again_and_metered_once(self):
        client = FakeJudge(reject_structured=True)
        model = MeteredJudgeModel(client, endpoint())

        result = ask(model)

        assert isinstance(result, Claims) and client.calls == 2
        assert len(model.usages) == 1


class TestWhatDeepEvalRelies:
    def test_the_synchronous_call_fails_loudly(self):
        model = MeteredJudgeModel(FakeJudge(), endpoint())

        with pytest.raises(JudgeModelError, match="async only"):
            model.generate("p")

    def test_there_is_no_raw_response_call_so_g_eval_uses_structured_output(self):
        model = MeteredJudgeModel(FakeJudge(), endpoint())

        assert not hasattr(model, "a_generate_raw_response")
        assert not hasattr(model, "generate_raw_response")

    def test_the_model_reports_the_requested_name(self):
        model = MeteredJudgeModel(FakeJudge(), endpoint("qwen/qwen4-max:free"))

        assert model.get_model_name() == "qwen/qwen4-max:free"


class TestStrictSchema:
    def test_objects_are_closed_and_fully_required_and_defaults_dropped(self):
        original = Verdicts.model_json_schema()

        closed = strict_schema(original)

        assert closed["additionalProperties"] is False
        assert closed["required"] == ["verdicts"]
        item = closed["$defs"]["FaithfulnessVerdict"]
        assert item["additionalProperties"] is False
        assert item["required"] == ["verdict", "reason"]
        assert "default" not in item["properties"]["reason"]
        assert "default" in original["$defs"]["FaithfulnessVerdict"]["properties"]["reason"]

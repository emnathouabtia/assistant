import json

from app.contracts import Intent, ResourceSpec
from app.nlp.parser import (
    ASK_WHAT,
    FAILED,
    MIXED,
    QUESTIONS,
    RawIntent,
    RawResource,
    build_system,
    current_for_prompt,
    norm_region,
    norm_runtime,
    norm_sku,
    parse,
    slug,
    to_intent,
)


class FakeLLM:
    """Stands in for A3's client: records calls and returns a fixed RawIntent."""

    def __init__(self, raw=None, error=None):
        self.raw = raw
        self.error = error
        self.calls = []

    def __call__(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        return self.raw


def make(resources, kind="action", **kwargs):
    return RawIntent(kind=kind, resources=resources, **kwargs)


# ---------------------------------------------------------------- normalisation helpers


def test_slug_normalises_case_and_separators():
    assert slug("My Shop!") == "my-shop"


def test_slug_strips_accents():
    assert slug("Café") == "cafe"


def test_slug_rejects_too_short():
    assert slug("ab") is None
    assert slug("") is None
    assert slug(None) is None


def test_slug_truncates_to_24_chars():
    assert len(slug("a" * 30)) == 24


def test_norm_region_collapses_spaces():
    assert norm_region("West Europe") == "westeurope"
    assert norm_region("East US") == "eastus"


def test_norm_region_maps_known_aliases():
    assert norm_region("europedelouest") == "westeurope"
    assert norm_region("France Centrale") == "francecentral"


def test_norm_region_returns_none_for_empty():
    assert norm_region(None) is None
    assert norm_region("") is None


def test_norm_sku_matches_case_insensitively():
    assert norm_sku("webapp", "f1") == "F1"
    assert norm_sku("webapp", "b1") == "B1"


def test_norm_sku_normalises_separators():
    assert norm_sku("storage", "standard lrs") == "Standard_LRS"


def test_norm_sku_keeps_unknown_value_for_a3_to_reject():
    assert norm_sku("storage", "Premium_LRS") == "Premium_LRS"


def test_norm_runtime_accepts_aliases():
    assert norm_runtime("Node.js") == "node"
    assert norm_runtime("Python 3") == "python"
    assert norm_runtime("js") == "node"


def test_norm_runtime_lowercases_unknown_value():
    assert norm_runtime("Go") == "go"


# ---------------------------------------------------------------- raw -> strict Intent


def test_confirm_and_cancel_have_no_resources():
    assert to_intent(make([], kind="confirm")).model_dump()["resources"] == []
    assert to_intent(make([], kind="cancel")).kind == "cancel"


def test_question_gets_default_answer_when_model_gives_none():
    intent = to_intent(make([], kind="question"))
    assert intent.answer == ASK_WHAT


def test_action_without_resources_becomes_chitchat():
    intent = to_intent(make([]))
    assert intent.kind == "chitchat"
    assert intent.answer == ASK_WHAT


def test_unsupported_type_is_refused():
    intent = to_intent(make([RawResource(type="vm")]))
    assert intent.kind == "chitchat"
    assert "vm" in intent.answer


def test_infrastructure_and_pipeline_together_is_refused():
    intent = to_intent(make([
        RawResource(type="webapp", name="shop", region="West Europe"),
        RawResource(type="pipeline", name="shop-ci"),
    ]))
    assert intent.kind == "chitchat"
    assert intent.answer == MIXED


def test_missing_fields_ask_for_name_before_region():
    intent = to_intent(make([RawResource(type="sql")]))
    assert intent.missing_fields == ["name", "region"]
    assert intent.clarifying_question == QUESTIONS["name"]


def test_missing_fields_use_placeholders_that_pass_the_contract():
    intent = to_intent(make([RawResource(type="sql")]))
    spec = intent.resources[0]
    assert spec.name == "my-sql"
    assert spec.region == "spaincentral"


def test_missing_region_only_asks_for_region():
    intent = to_intent(make([RawResource(type="webapp", name="shop")]))
    assert intent.missing_fields == ["region"]
    assert intent.clarifying_question == QUESTIONS["region"]


def test_pipeline_needs_no_region():
    intent = to_intent(make([RawResource(type="pipeline", name="shop-ci")]))
    assert intent.missing_fields == []
    assert intent.clarifying_question is None


def test_model_question_is_kept_when_provided():
    intent = to_intent(make(
        [RawResource(type="storage", region="West Europe")],
        clarifying_question="What should the storage account be called?",
    ))
    assert intent.clarifying_question == "What should the storage account be called?"


def test_complete_request_is_normalised():
    intent = to_intent(make([RawResource(
        type="storage", name="Archive", region="West Europe", sku="standard lrs",
    )]))
    spec = intent.resources[0]
    assert intent.missing_fields == []
    assert (spec.name, spec.region, spec.sku) == ("archive", "westeurope", "Standard_LRS")


def test_params_are_preserved_for_pipelines():
    intent = to_intent(make([RawResource(
        type="pipeline", name="shop-ci", runtime="Node.js",
        params={"branch": "main", "app_name": "shop-web"},
    )]))
    spec = intent.resources[0]
    assert spec.runtime == "node"
    assert spec.params == {"branch": "main", "app_name": "shop-web"}


# ---------------------------------------------------------------- parse() with a fake LLM


def test_parse_sends_intent_history_and_message_as_json():
    fake = FakeLLM(make([RawResource(type="sql", name="shop-db", region="West Europe")]))
    parse([("user", "I need a database"), ("assistant", "What name?")],
          None, "shop-db", llm=fake)

    payload = json.loads(fake.calls[0]["user"])
    assert payload["message"] == "shop-db"
    assert payload["current_intent"] is None
    assert payload["history"] == [["user", "I need a database"], ["assistant", "What name?"]]


def test_parse_keeps_only_the_last_six_history_turns():
    history = [("user", f"turn {i}") for i in range(10)]
    fake = FakeLLM(make([RawResource(type="sql", name="shop-db", region="West Europe")]))
    parse(history, None, "shop-db", llm=fake)

    payload = json.loads(fake.calls[0]["user"])
    assert len(payload["history"]) == 6
    assert payload["history"][0] == ["user", "turn 4"]


def test_parse_returns_the_strict_intent():
    fake = FakeLLM(make([RawResource(type="webapp", name="shop", region="West Europe",
                                    runtime="python")]))
    intent = parse([], None, "create a python web app called shop", llm=fake)

    assert intent.kind == "action"
    assert intent.missing_fields == []
    assert intent.resources[0].type.value == "webapp"


def test_parse_returns_a_friendly_message_when_the_llm_fails():
    fake = FakeLLM(error=RuntimeError("provider down"))
    intent = parse([], None, "create a web app", llm=fake)

    assert intent.kind == "chitchat"
    assert intent.answer == FAILED


def test_parse_puts_no_placeholder_values_back_into_the_prompt():
    current = Intent(
        kind="action",
        resources=[ResourceSpec(type="sql", name="my-sql", region="westeurope")],
        missing_fields=["name"],
    )
    fake = FakeLLM(make([RawResource(type="sql", name="shop-db", region="West Europe")]))
    parse([], current, "shop-db", llm=fake)

    payload = json.loads(fake.calls[0]["user"])
    assert payload["current_intent"]["resources"][0]["name"] is None
    assert payload["current_intent"]["resources"][0]["region"] == "westeurope"


def test_current_for_prompt_ignores_non_action_intents():
    assert current_for_prompt(Intent(kind="question", answer="hello")) is None


# ---------------------------------------------------------------- prompt


def test_build_system_injects_all_examples():
    system = build_system()
    assert "{{EXAMPLES}}" not in system
    assert "Example 1" in system
    assert "Example 11" in system

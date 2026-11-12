import json
from pathlib import Path

from app.contracts import Intent
from app.llm.guardrails import check_intent

ROOT = Path(__file__).parents[1]
SAMPLES_DIR = ROOT / "app" / "nlp" / "samples"
EVAL_SET = ROOT / "app" / "nlp" / "eval_set.json"
ALLOWED_RESOURCE_KEYS = {"type", "name", "region", "sku", "runtime", "params"}


def test_samples_pass_guardrails():
    sample_files = sorted(SAMPLES_DIR.glob("*.json"))
    assert sample_files

    for path in sample_files:
        intent = Intent.model_validate(json.loads(path.read_text(encoding="utf-8")))
        assert check_intent(intent) == [], f"{path.name} violates A3 guardrails"


def test_complete_eval_cases_pass_guardrails():
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))

    for case in cases:
        expected = case["expected"]
        if expected.get("kind") != "action" or expected.get("missing_fields"):
            continue

        intent = Intent.model_validate(expected)
        assert check_intent(intent) == [], f"{case['name']} violates A3 guardrails"

def test_sample_resources_only_use_contract_fields():
    for path in sorted(SAMPLES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for resource in data["resources"]:
            extra = set(resource) - ALLOWED_RESOURCE_KEYS
            assert not extra, f"{path.name} has unknown keys: {sorted(extra)}"
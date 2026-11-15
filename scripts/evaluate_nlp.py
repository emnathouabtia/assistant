import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contracts import Intent
from app.nlp.parser import parse


EVAL_SET = ROOT / "app" / "nlp" / "eval_set.json"


def check_case(actual: dict, expected: dict) -> list[str]:
    errors = []

    for field in ("kind", "missing_fields"):
        if field in expected and actual.get(field) != expected[field]:
            errors.append(
                f"{field}: expected {expected[field]!r}, got {actual.get(field)!r}"
            )

    if "resources" in expected:
        actual_resources = actual.get("resources", [])
        expected_resources = expected["resources"]

        if len(actual_resources) != len(expected_resources):
            errors.append(
                f"resources: expected {len(expected_resources)}, got {len(actual_resources)}"
            )
        else:
            for index, expected_resource in enumerate(expected_resources):
                for field, expected_value in expected_resource.items():
                    actual_value = actual_resources[index].get(field)
                    if actual_value != expected_value:
                        errors.append(
                            f"resources[{index}].{field}: "
                            f"expected {expected_value!r}, got {actual_value!r}"
                        )

    for field in ("answer", "clarifying_question"):
        flag = f"{field}_nonempty"
        if flag in expected:
            is_nonempty = bool((actual.get(field) or "").strip())
            if is_nonempty != expected[flag]:
                errors.append(f"{field}: expected nonempty={expected[flag]}")

    answer = (actual.get("answer") or "").casefold()
    for phrase in expected.get("answer_must_not_contain", []):
        if phrase.casefold() in answer:
            errors.append(f"answer contains disallowed text: {phrase!r}")

    return errors


def main() -> int:
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    passed = 0

    for index, case in enumerate(cases, start=1):
        try:
            input_data = case["input"]
            current_data = input_data.get("current_intent")
            current = Intent.model_validate(current_data) if current_data else None

            result = parse(
                input_data.get("history", []),
                current,
                input_data["message"],
            )
            errors = check_case(result.model_dump(mode="json"), case["expected"])
        except Exception as exc:
            errors = [f"evaluation error: {type(exc).__name__}: {exc}"]

        label = case.get("name", f"case {index}")
        if errors:
            print(f"FAIL {label}: {'; '.join(errors)}")
        else:
            passed += 1
            print(f"PASS {label}")

    total = len(cases)
    rate = (passed / total * 100) if total else 0
    print(f"\nPass rate: {passed}/{total} ({rate:.1f}%)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
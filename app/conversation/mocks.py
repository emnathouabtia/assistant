import uuid
from types import SimpleNamespace


def mock_parse(history, current, text):
    if text.strip().endswith("?"):
        return SimpleNamespace(kind="question", missing_fields=[], clarifying_question=None,
                               answer="(mock) I will answer questions once A1 is ready.")
    return SimpleNamespace(kind="action", missing_fields=[], clarifying_question=None, answer=None)


def mock_plan(intent):
    return {
        "plan_id": "p_" + uuid.uuid4().hex[:6],
        "summary": [{"change": "Create", "resource": "Microsoft.Web/sites", "name": "demo-x7k2"}],
        "estimated_monthly_cost_usd": 13.1,
        "warnings": ["Mock plan: nothing is real yet."],
    }


_polls = {}


def mock_deploy(plan_id):
    dep_id = "d_" + uuid.uuid4().hex[:6]
    _polls[dep_id] = 0
    return {"deployment_id": dep_id, "state": "pending", "message": "Mock deployment started"}


def mock_status(deployment_id):
    _polls[deployment_id] = _polls.get(deployment_id, 0) + 1
    n = _polls[deployment_id]
    state = "running" if n < 3 else "succeeded"
    return {"deployment_id": deployment_id, "state": state, "message": f"Mock poll {n}"}
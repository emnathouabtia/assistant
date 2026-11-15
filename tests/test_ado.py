import pytest

from app.devops import ado_client
from app.devops.ado_client import ZERO, AdoError


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = "x" if data else ""

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setenv("ADO_ORG", "org")
    monkeypatch.setenv("ADO_PROJECT", "proj")
    monkeypatch.setenv("ADO_REPO", "demo-app")
    monkeypatch.setenv("ADO_PAT", "fake-token")


def fake_requests(monkeypatch, response):
    monkeypatch.setattr(ado_client.requests, "request", lambda *a, **kw: response)


def test_repo_id(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"id": "abc-123"}))
    assert ado_client.repo_id() == "abc-123"


def test_branch_head_returns_commit(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"value": [{"objectId": "f" * 40}]}))
    assert ado_client.branch_head() == "f" * 40


def test_branch_head_empty_repo_returns_zero(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"value": []}))
    assert ado_client.branch_head() == ZERO


def test_error_raises_ado_error(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(status_code=401, data={"message": "unauthorized"}))
    with pytest.raises(AdoError):
        ado_client.repo_id()

def fake_sequence(monkeypatch, responses):
    calls = []
    it = iter(responses)

    def fake(method, url, **kw):
        calls.append({"method": method, "url": url, **kw})
        return next(it)

    monkeypatch.setattr(ado_client.requests, "request", fake)
    return calls

def test_file_exists_false_on_404(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(status_code=404, data={"message": "not found"}))
    assert ado_client.file_exists("/azure-pipelines.yml") is False


def test_push_file_uses_add_when_file_is_missing(monkeypatch):
    calls = fake_sequence(monkeypatch, [
        FakeResponse(status_code=404, data={"message": "not found"}),   # 1. file_exists -> no
        FakeResponse(data={"value": [{"objectId": "a" * 40}]}),         # 2. branch_head
        FakeResponse(data={"pushId": 1}),                               # 3. the push
    ])
    ado_client.push_file("/azure-pipelines.yml", "steps: []", "test")
    body = calls[2]["json"]
    assert body["commits"][0]["changes"][0]["changeType"] == "add"
    assert body["refUpdates"][0]["oldObjectId"] == "a" * 40


def test_push_file_uses_edit_when_file_exists(monkeypatch):
    calls = fake_sequence(monkeypatch, [
        FakeResponse(data={"path": "/azure-pipelines.yml"}),            # 1. file_exists -> yes
        FakeResponse(data={"value": [{"objectId": "b" * 40}]}),
        FakeResponse(data={"pushId": 2}),
    ])
    ado_client.push_file("/azure-pipelines.yml", "steps: []", "test")
    assert calls[2]["json"]["commits"][0]["changes"][0]["changeType"] == "edit"



@pytest.mark.parametrize("state, result, expected", [
    ("inProgress", None, "running"),
    ("completed", "succeeded", "succeeded"),
    ("completed", "failed", "failed"),
    ("completed", "canceled", "failed"),
    ("notStarted", None, "pending"),
])
def test_run_status_translation(monkeypatch, state, result, expected):
    data = {"state": state, "_links": {"web": {"href": "https://link"}}}
    if result:
        data["result"] = result
    fake_requests(monkeypatch, FakeResponse(data=data))
    assert ado_client.run_status(1, 2)["state"] == expected

def test_pat_never_appears_in_error(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(status_code=403, data={"message": "forbidden"}))
    with pytest.raises(AdoError) as err:
        ado_client.repo_id()
    assert "fake-token" not in str(err.value)

def test_publish_pipeline_chains_the_steps(monkeypatch):
    steps = []
    monkeypatch.setattr(ado_client, "push_file", lambda path, content, msg: steps.append("push"))
    monkeypatch.setattr(ado_client, "create_pipeline", lambda name: steps.append("create") or {"id": 7})
    monkeypatch.setattr(ado_client, "run_pipeline", lambda pid: steps.append("run") or {"id": 42})
    r = ado_client.publish_pipeline("steps: []", "shop-ci")
    assert steps == ["push", "create", "run"]
    assert r["deployment_id"] == "7:42"
    assert r["state"] == "running"


def test_pipeline_status_splits_the_id(monkeypatch):
    monkeypatch.setattr(ado_client, "run_status",
                        lambda pid, rid: {"state": "succeeded", "message": f"{pid}/{rid}"})
    r = ado_client.pipeline_status("7:42")
    assert r["message"] == "7/42"
    assert r["deployment_id"] == "7:42"
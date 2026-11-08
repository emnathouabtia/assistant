from app.conversation.states import State, can_move
from app.conversation.orchestrator import Session
import pytest
from app.conversation.orchestrator import Orchestrator
from types import SimpleNamespace 



def test_idle_can_go_to_parsing():
    assert can_move(State.IDLE, State.PARSING) 


def test_cannot_jump_to_deploying():
    assert not can_move(State.PLANNING, State.DEPLOYING)
    assert not can_move(State.IDLE, State.DEPLOYING)


def test_new_session_starts_idle():
    s = Session("abc")
    assert s.state == State.IDLE
    assert s.plan is None


def test_sessions_do_not_share_history():
    a = Session("a")
    b = Session("b")
    a.history.append("hello")
    assert b.history == []

    
def test_only_confirmation_leads_to_deploying():
    sources = [s for s in State if can_move(s, State.DEPLOYING)]
    assert sources == [State.AWAITING_CONFIRMATION]

def test_new_message_during_review_goes_back_to_parsing():
    assert can_move(State.AWAITING_CONFIRMATION, State.PARSING)


def test_deploying_cannot_be_cancelled():
    assert not can_move(State.DEPLOYING, State.CANCELLED)

def fake(*args, **kwargs):
    return None


def make_orch():
    return Orchestrator(parse=fake, plan=fake, deploy=fake, status=fake)


def test_go_allows_legal_move():
    o = make_orch()
    s = o._s("abc")
    o._go(s, State.PARSING)
    assert s.state == State.PARSING


def test_go_refuses_illegal_move():
    o = make_orch()
    s = o._s("abc")
    with pytest.raises(ValueError):
        o._go(s, State.DEPLOYING)



def intent(kind="action", missing=None, question=None, answer=None, resources=None):
    return SimpleNamespace(kind=kind, missing_fields=missing or [],
                           clarifying_question=question, answer=answer,
                           resources=resources or [])

FAKE_PLAN = {"plan_id": "p_1", "summary": [], "estimated_monthly_cost_usd": 5, "warnings": []}


def test_happy_path_returns_plan():
    o = Orchestrator(parse=lambda h, c, t: intent(), plan=lambda i: FAKE_PLAN,
                     deploy=fake, status=fake)
    r = o.handle_chat("s1", "create a web app")
    assert r["type"] == "plan"
    assert o.sessions["s1"].state == State.AWAITING_CONFIRMATION


def test_missing_info_asks_question():
    o = Orchestrator(parse=lambda h, c, t: intent(missing=["region"], question="Which region?"),
                     plan=fake, deploy=fake, status=fake)
    r = o.handle_chat("s1", "create a web app")
    assert r == {"type": "question", "text": "Which region?"}
    assert o.sessions["s1"].state == State.NEEDS_INFO


def test_guardrails_block_request():
    o = Orchestrator(parse=lambda h, c, t: intent(), plan=fake, deploy=fake, status=fake,
                     check=lambda i: ["SKU P3 not allowed"])
    r = o.handle_chat("s1", "create a huge server")
    assert r["type"] == "error"
    assert o.sessions["s1"].state == State.IDLE

def test_question_is_answered_without_plan():
    o = Orchestrator(parse=lambda h, c, t: intent(kind="question", answer="A resource group is a folder."),
                     plan=fake, deploy=fake, status=fake)
    r = o.handle_chat("s1", "what is a resource group?")
    assert r == {"type": "info", "text": "A resource group is a folder."}
    assert o.sessions["s1"].state == State.IDLE

def ready_orch(deploy=lambda pid: {"deployment_id": "d_1", "state": "pending", "message": ""}):
    o = Orchestrator(parse=lambda h, c, t: intent(), plan=lambda i: FAKE_PLAN,
                     deploy=deploy, status=fake)
    o.handle_chat("s1", "create a web app")
    return o


def test_confirm_deploys():
    o = ready_orch()
    r = o.handle_confirm("s1", "p_1", True)
    assert r["type"] == "status"
    assert o.sessions["s1"].state == State.DEPLOYING


def test_cancel_changes_nothing():
    o = ready_orch()
    r = o.handle_confirm("s1", "p_1", False)
    assert r["type"] == "info"
    assert o.sessions["s1"].state == State.CANCELLED


def test_wrong_plan_id_is_refused():
    o = ready_orch()
    r = o.handle_confirm("s1", "p_OLD", True)
    assert r["type"] == "error"


def test_double_confirm_deploys_only_once():
    calls = []
    o = ready_orch(deploy=lambda pid: calls.append(pid) or {"deployment_id": "d_1", "state": "pending", "message": ""})
    o.handle_confirm("s1", "p_1", True)
    second = o.handle_confirm("s1", "p_1", True)
    assert second["type"] == "error"
    assert len(calls) == 1
def test_expired_plan_is_refused():
    o = ready_orch()
    o.sessions["s1"].updated -= 601
    r = o.handle_confirm("s1", "p_1", True)
    assert r["type"] == "error"
    assert o.sessions["s1"].state == State.CANCELLED
def test_status_moves_to_done():
    o = ready_orch()
    o.status = lambda dep_id: {"deployment_id": dep_id, "state": "succeeded", "message": "Done"}
    o.handle_confirm("s1", "p_1", True)
    r = o.handle_status("s1")
    assert r["state"] == "succeeded"
    assert o.sessions["s1"].state == State.DONE


def test_status_when_nothing_running():
    o = ready_orch()
    r = o.handle_status("s1")
    assert r["type"] == "info"

def test_typed_yes_confirms_the_plan():
    replies = iter([intent(), intent(kind="confirm")])
    o = Orchestrator(parse=lambda h, c, t: next(replies), plan=lambda i: FAKE_PLAN,
                     deploy=lambda pid: {"deployment_id": "d_1", "state": "pending", "message": ""},
                     status=fake)
    o.handle_chat("s1", "create a web app")
    r = o.handle_chat("s1", "yes go ahead")
    assert r["type"] == "status"
    assert o.sessions["s1"].state == State.DEPLOYING


def test_typed_yes_without_plan_deploys_nothing():
    calls = []
    o = Orchestrator(parse=lambda h, c, t: intent(kind="confirm"), plan=fake,
                     deploy=lambda pid: calls.append(pid), status=fake)
    o.handle_chat("s1", "yes")
    assert calls == []
    assert o.sessions["s1"].state == State.IDLE
def test_typed_cancel_cancels_the_plan():
    replies = iter([intent(), intent(kind="cancel")])
    o = Orchestrator(parse=lambda h, c, t: next(replies), plan=lambda i: FAKE_PLAN,
                     deploy=fake, status=fake)
    o.handle_chat("s1", "create a web app")
    r = o.handle_chat("s1", "no, cancel")
    assert r["type"] == "info"
    assert o.sessions["s1"].state == State.CANCELLED
from app.conversation.orchestrator import apply_defaults


def test_apply_defaults_fills_region_and_sku():
    i = intent(missing=["region"], resources=[SimpleNamespace(type="webapp", region=None, sku=None)])
    used = apply_defaults(i)
    assert i.resources[0].region == "westeurope"
    assert i.resources[0].sku == "B1"
    assert i.missing_fields == []
    assert len(used) == 2


def test_after_three_questions_defaults_are_used():
    o = Orchestrator(
        parse=lambda h, c, t: intent(missing=["region"], question="Which region?",
                                     resources=[SimpleNamespace(type="webapp", region=None, sku=None)]),
        plan=lambda i: dict(FAKE_PLAN), deploy=fake, status=fake)
    for _ in range(3):
        r = o.handle_chat("s1", "a web app")
        assert r["type"] == "question"
    r = o.handle_chat("s1", "a web app")
    assert r["type"] == "plan"
    assert any("Defaults used" in w for w in r["warnings"])
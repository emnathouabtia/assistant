from fastapi import FastAPI
from pydantic import BaseModel

from app.conversation.mocks import mock_deploy, mock_parse, mock_plan, mock_status
from app.conversation.orchestrator import Orchestrator

app = FastAPI(title="Azure AI Provisioning Assistant")

orch = Orchestrator(parse=mock_parse, plan=mock_plan, deploy=mock_deploy, status=mock_status)


class ChatIn(BaseModel):
    session_id: str
    message: str


class ConfirmIn(BaseModel):
    session_id: str
    plan_id: str
    approve: bool
    accept_cost: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: ChatIn):
    return orch.handle_chat(body.session_id, body.message)


@app.post("/confirm")
def confirm(body: ConfirmIn):
    return orch.handle_confirm(body.session_id, body.plan_id, body.approve)


@app.get("/status/{session_id}")
def status(session_id: str):
    return orch.handle_status(session_id)
@app.post("/confirm")
def confirm(body: ConfirmIn):
    return orch.handle_confirm(body.session_id, body.plan_id, body.approve, body.accept_cost)
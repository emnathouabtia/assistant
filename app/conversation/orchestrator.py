import time
from dataclasses import dataclass, field
from threading import RLock

from app.conversation.states import ALLOWED, TERMINAL, State

PLAN_TTL = 600  # seconds = 10 minutes
MAX_CLARIFICATIONS = 3
DEFAULT_REGION = "spaincentral"
DEFAULT_SKUS = {"webapp": "B1", "storage": "Standard_LRS", "sql": "Basic", "keyvault": "standard"}

def apply_defaults(intent):
        used = []
        for r in intent.resources:
            rtype = getattr(r.type, "value", r.type)
            if not r.region:
             r.region = DEFAULT_REGION
             used.append(f"region {DEFAULT_REGION}")
            if not r.sku and rtype in DEFAULT_SKUS:
             r.sku = DEFAULT_SKUS[rtype]
             used.append(f"{rtype} tier {r.sku}")
        intent.missing_fields = []
        return used 

@dataclass
class Session:
    sid: str
    state: State = State.IDLE
    history: list = field(default_factory=list)
    intent: object = None
    plan: dict | None = None
    deployment_id: str | None = None
    updated: float = field(default_factory=time.time)
    clarifications: int = 0
    cost_warned: bool = False


class Orchestrator:
    def __init__(self, parse, plan, deploy, status, check=lambda intent: [], cost_limit=30):
        self.parse = parse
        self.plan = plan
        self.deploy = deploy
        self.status = status
        self.check = check
        self.sessions: dict[str, Session] = {}
        self.lock = RLock()
        self.cost_limit = cost_limit

    def _s(self, sid):
        return self.sessions.setdefault(sid, Session(sid))

    def _go(self, s, new):
        if new not in ALLOWED[s.state]:
            raise ValueError(f"illegal transition {s.state} -> {new}")
        s.state = new
        s.updated = time.time()

    def handle_chat(self, sid, text):
        with self.lock:
            s = self._s(sid)

            if s.state == State.DEPLOYING:
                return {"type": "info", "text": "A deployment is running. Please wait."}

            if s.state in TERMINAL:
                self._go(s, State.IDLE)
            if s.state == State.IDLE:
                s.clarifications = 0
            result = self.parse(s.history, s.intent, text)
            s.history.append(("user", text))

            if s.state == State.AWAITING_CONFIRMATION:
                if result.kind == "confirm":
                    return self.handle_confirm(sid, s.plan["plan_id"], True, accept_cost=s.cost_warned)
                if result.kind == "cancel":
                    return self.handle_confirm(sid, s.plan["plan_id"], False)
                s.plan = None  # anything else = the request changed, old plan is invalid

            self._go(s, State.PARSING)

            if result.kind != "action":
                self._go(s, State.IDLE)
                return {"type": "info", "text": result.answer or "Okay."}

            s.intent = result

            defaults_used = []
            if result.missing_fields:
                s.clarifications += 1
                if s.clarifications <= MAX_CLARIFICATIONS:
                    self._go(s, State.NEEDS_INFO)
                    return {"type": "question", "text": result.clarifying_question}
                defaults_used = apply_defaults(result)

            problems = self.check(result)
            if problems:
                self._go(s, State.IDLE)
                return {"type": "error", "text": "; ".join(problems)}

            self._go(s, State.PLANNING)
            try:
                s.plan = self.plan(result)
                s.cost_warned = False
            except Exception as e:
                self._go(s, State.FAILED)
                return {"type": "error", "text": f"Planning failed: {e}"}
            if defaults_used:
                note = "Defaults used: " + ", ".join(defaults_used) + ". Is that okay?"
                s.plan = {**s.plan, "warnings": s.plan.get("warnings", []) + [note]}
            self._go(s, State.AWAITING_CONFIRMATION)
            return {"type": "plan", **s.plan}

    def handle_confirm(self, sid, plan_id, approve, accept_cost=False):
        with self.lock:
            s = self._s(sid)

            if (s.state != State.AWAITING_CONFIRMATION or not s.plan
                    or s.plan["plan_id"] != plan_id):
                return {"type": "error", "text": "This plan is no longer valid. Please ask again."}

            if time.time() - s.updated > PLAN_TTL:
                self._go(s, State.CANCELLED)
                return {"type": "error", "text": "The plan expired. Please start again."}

            if not approve:
                self._go(s, State.CANCELLED)
                return {"type": "info", "text": "Cancelled. Nothing was changed."}
            cost = s.plan.get("estimated_monthly_cost_usd", 0)
            if cost > self.cost_limit and not accept_cost:
                s.cost_warned = True
                return {"type": "cost_warning",
                        "text": f"This plan costs about ${cost}/month, above the ${self.cost_limit} limit. "
                                "Click 'I accept the cost' (or type yes) to deploy anyway."}
            self._go(s, State.DEPLOYING)  # BEFORE deploying: blocks a double confirm
            dep = self.deploy(plan_id)
            s.deployment_id = dep["deployment_id"]
            return {"type": "status", **dep}

    def handle_status(self, sid):
        with self.lock:
            s = self._s(sid)

            if not s.deployment_id:
                return {"type": "info", "text": "Nothing is running."}

            st = self.status(s.deployment_id)

            if st["state"] == "succeeded" and s.state == State.DEPLOYING:
                self._go(s, State.DONE)
            elif st["state"] == "failed" and s.state == State.DEPLOYING:
                self._go(s, State.FAILED)

            return {"type": "status", **st}

    
# A2 — Conversation and confirmation workflow

Owner: Arij

## What it does

A2 is the traffic controller of the assistant. It remembers where each conversation is (its state), decides what happens next for each message, and makes sure nothing is deployed without a valid, explicit confirmation.

It contains no AI and no Azure code, only logic, so it is fully testable with mocks. A lock makes sure requests are handled one at a time, so a double click cannot deploy twice.

Files:
- `app/conversation/states.py` — the states and the allowed transitions
- `app/conversation/orchestrator.py` — `Session`, `Orchestrator`, the handlers
- `app/conversation/mocks.py` — fake A1/B3 functions used until integration
- `tests/test_conversation.py` — unit and scripted-conversation tests

## States

| State | Meaning |
| --- | --- |
| IDLE | Waiting for a new request |
| PARSING | A1 is reading the message |
| NEEDS_INFO | A clarifying question was asked, waiting for the answer |
| PLANNING | B3 validates the template and runs what-if |
| AWAITING_CONFIRMATION | Plan shown, waiting for yes or no |
| DEPLOYING | B3 (or C2 for a pipeline) is creating the resources |
| DONE | Deployment succeeded |
| FAILED | Planning or deployment failed |
| CANCELLED | The user said no, or the plan expired |

The allowed moves are stored as data (`ALLOWED` in `states.py`). Every state change goes through `_go()`, which refuses any move not in the table. The only way to reach DEPLOYING is from AWAITING_CONFIRMATION, and a test proves it.

## Confirmation rules

1. **A real approval event is required.** Either the Confirm button (`POST /confirm`) or a typed "yes" that A1 returns as `kind = "confirm"` while a plan is shown. Outside that state, a "yes" deploys nothing.
2. **Confirmation is bound to a `plan_id`**, so the user approves exactly the plan they saw.
3. **A new message during review invalidates the plan.** The request may have changed, so it is parsed again and a new plan (new `plan_id`) is built.
4. **Plans expire after 10 minutes**, because the state of Azure may have changed.
5. **The session moves to DEPLOYING before B3 is called.** A second click finds the wrong state and is refused, so a double click cannot deploy twice.
6. **Extra confirmation above the cost limit.** If the estimated monthly cost is above the limit from A3, the user gets a `cost_warning` and must send `accept_cost: true` (or type "yes" after the warning). Clicking Confirm twice is not enough.
7. **At most 3 clarifying questions.** After that, the cheapest allowed defaults are used (for example region `westeurope`, web app tier `B1`) and a note "Defaults used: … Is that okay?" is added to the plan's warnings. The user still has to confirm.

## Endpoints

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /chat` | `session_id`, `message` | `question`, `info`, `plan` or `error` |
| `POST /confirm` | `session_id`, `plan_id`, `approve`, `accept_cost` (optional, default `false`) | `status`, `info`, `cost_warning` or `error` |
| `GET /status/{session_id}` | none | `status` (`pending`, `running`, `succeeded`, `failed`) or `info` |

Response types:
- `question` — a clarifying question to show
- `info` — a simple message (an answer, "Cancelled", "A deployment is running")
- `plan` — `plan_id`, `summary`, `estimated_monthly_cost_usd`, `warnings`
- `cost_warning` — the plan is above the cost limit; show an "I accept the cost" button
- `status` — `deployment_id`, `state`, `message`
- `error` — something was refused or failed

## Dependencies (injected)

The `Orchestrator` receives these functions as parameters instead of importing them. Tests pass mocks; `main.py` will pass the real functions at integration.

| Parameter | Provided by | Purpose |
| --- | --- | --- |
| `parse(history, current_intent, text)` | A1 (Nour) | Turns the message into an intent |
| `plan(intent)` | B3 (Emna) | Validates, runs what-if, returns the plan |
| `deploy(plan_id)` | B3 (Emna) | Starts the deployment, returns a status with `deployment_id` |
| `status(deployment_id)` | B3 (Emna) / C2 | Returns the current deployment status |
| `check(intent)` | A3 (Emna) | Guardrails: returns a list of violations (empty = OK) |
| `cost_limit` | A3 (Emna) | Monthly cost above which an extra confirmation is required |

Until integration, `mocks.py` provides fake `parse`, `plan`, `deploy` and `status`. The mock status goes `running`, `running`, then `succeeded`.

## How to test

```bash
pytest -v
```

Run the API locally:

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs and try a full scenario: `/chat` → copy the `plan_id` → `/confirm` → `/status` three times → `/confirm` again (refused).

## Known limits

- Sessions are kept in memory: a server restart loses them. SQLite would be the next step.
- The lock protects one server process. Running several workers would need a shared store.
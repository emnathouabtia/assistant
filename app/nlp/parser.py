#A1: turn free text into a validated Intent.
#
#   parse(history, current_intent, text) -> Intent
#
# Design:
#   * The model fills a LENIENT schema (RawIntent). It never has to produce
#     perfect names or a missing_fields list.
#   * Plain Python then normalises values, computes missing_fields itself
#     (the model cannot forget one) and builds the strict Intent from contracts.py.
#   * Everything the user wrote is passed as JSON data, never mixed into the rules.
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel, Field

from app.contracts import Intent, ResourceSpec, ResourceType
from app.nlp.prompts import EXAMPLES, SYSTEM_PROMPT

log = logging.getLogger(__name__)

SUPPORTED = {t.value for t in ResourceType}
HISTORY_TURNS = 6
DEFAULT_REGION = "spaincentral"     # placeholder only; used while "region" is in missing_fields

# ---------------------------------------------------------------- lenient model schema


class RawResource(BaseModel):
    type: str
    name: Optional[str] = None
    region: Optional[str] = None
    sku: Optional[str] = None
    runtime: Optional[str] = None
    params: dict = Field(default_factory=dict)


class RawIntent(BaseModel):
    kind: Literal["action", "question", "confirm", "cancel", "chitchat"]
    resources: List[RawResource] = Field(default_factory=list)
    clarifying_question: Optional[str] = None
    answer: Optional[str] = None


# ---------------------------------------------------------------- user-facing fallback texts

CAPABILITIES = ("web apps, storage accounts, SQL databases and Key Vaults, "
                "and create CI/CD pipelines")
ASK_WHAT = f"I can deploy {CAPABILITIES}. What would you like to do?"
MIXED = "Please ask for the infrastructure and the pipeline in separate requests. Which one first?"
FAILED = "Sorry, I could not understand that right now. Could you rephrase it?"
QUESTIONS = {
    "name": "What name would you like to use?",
    "region": "Which Azure region should I use?",
}

# ---------------------------------------------------------------- normalisation helpers

KNOWN_SKUS = {
    "webapp": ["F1", "B1"],
    "storage": ["Standard_LRS", "Standard_GRS"],
    "sql": ["Basic", "S0"],
    "keyvault": ["standard"],
}
RUNTIMES = {"python": "python", "python3": "python", "py": "python",
            "node": "node", "nodejs": "node", "javascript": "node", "js": "node"}
REGION_ALIASES = {"europedelouest": "westeurope", "francecentre": "francecentral",
                  "francecentrale": "francecentral", "espagnecentrale": "spaincentral",
                  "espagnecentre": "spaincentral"}


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def slug(value: Optional[str]) -> Optional[str]:
    """Lowercase letters, digits and hyphens, 3 to 24 chars, or None."""
    if not value:
        return None
    s = re.sub(r"[^a-z0-9]+", "-", _ascii(value).strip().lower()).strip("-")
    s = s[:24].strip("-")
    return s if len(s) >= 3 else None


def norm_region(value: Optional[str]) -> Optional[str]:
    """'West Europe' -> 'westeurope'."""
    if not value:
        return None
    s = re.sub(r"[^a-z0-9]", "", _ascii(value).lower())
    return REGION_ALIASES.get(s, s) or None


def norm_sku(rtype: str, value: Optional[str]) -> Optional[str]:
    """Match case-insensitively against known SKUs; keep unknown values so A3 rejects them."""
    if not value:
        return None
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    for known in KNOWN_SKUS.get(rtype, []):
        if known.lower() == key:
            return known
    return value.strip()


def norm_runtime(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = re.sub(r"[\s.\-_]+", "", value.lower())
    return RUNTIMES.get(key, value.strip().lower())


def _required(rtype: str) -> tuple:
    return ("name",) if rtype == "pipeline" else ("name", "region")


# ---------------------------------------------------------------- raw -> strict Intent


def to_intent(raw: RawIntent) -> Intent:
    if raw.kind in ("confirm", "cancel"):
        return Intent(kind=raw.kind)
    if raw.kind in ("question", "chitchat"):
        return Intent(kind=raw.kind, answer=raw.answer or ASK_WHAT)

    # kind == "action"
    if not raw.resources:
        return Intent(kind="chitchat", answer=raw.answer or ASK_WHAT)

    types = [r.type.strip().lower() for r in raw.resources]
    unsupported = [t for t in types if t not in SUPPORTED]
    if unsupported:
        return Intent(kind="chitchat", answer=raw.answer or
                      f"I can't create '{unsupported[0]}'. I can deploy {CAPABILITIES}.")
    if "pipeline" in types and any(t != "pipeline" for t in types):
        return Intent(kind="chitchat", answer=MIXED)

    specs: List[ResourceSpec] = []
    missing: List[str] = []
    for r, t in zip(raw.resources, types):
        name, region = slug(r.name), norm_region(r.region)
        found = {"name": name, "region": region}
        for field in _required(t):
            if not found[field] and field not in missing:
                missing.append(field)
        params = r.params if isinstance(r.params, dict) else {}
        specs.append(ResourceSpec(
            type=ResourceType(t),
            name=name or f"my-{t}",                 # valid placeholder while name is missing
            region=region or DEFAULT_REGION,        # valid placeholder while region is missing
            sku=norm_sku(t, r.sku),
            runtime=norm_runtime(r.runtime),
            params=params,
        ))

    missing.sort(key=["name", "region"].index)      # always ask for the name first
    question = None
    if missing:
        question = (raw.clarifying_question or "").strip() or QUESTIONS[missing[0]]
    return Intent(kind="action", resources=specs, missing_fields=missing,
                  clarifying_question=question)


# ---------------------------------------------------------------- prompt building


def build_system() -> str:
    blocks = []
    for i, ex in enumerate(EXAMPLES, 1):
        blocks.append(
            f"Example {i}\n"
            f"Input: {json.dumps({'current_intent': ex['current_intent'], 'message': ex['message']}, ensure_ascii=False)}\n"
            f"Output: {json.dumps(ex['output'], ensure_ascii=False)}"
        )
    return SYSTEM_PROMPT.replace("{{EXAMPLES}}", "Examples:\n\n" + "\n\n".join(blocks))


def current_for_prompt(current: Optional[Intent]) -> Optional[dict]:
    """What we show the model: placeholders for missing values are turned back into null."""
    if current is None or current.kind != "action":
        return None
    out = []
    for r in current.resources:
        d = r.model_dump(mode="json")
        if "name" in current.missing_fields:
            d["name"] = None
        if "region" in current.missing_fields:
            d["region"] = None
        out.append(d)
    return {"resources": out}


def _default_llm() -> Callable:
    try:
        from app.llm.client import complete      # A3
    except ImportError as e:                      # A3 not merged yet
        raise RuntimeError("app.llm.client (A3) is not available. "
                           "Pass llm=<function> to parse() until it is.") from e
    return complete


# ---------------------------------------------------------------- public API


def parse(history: list, current: Optional[Intent], text: str,
          llm: Optional[Callable] = None) -> Intent:
    """Understand one user message. `llm(system, user, schema)` returns a validated schema object."""
    llm = llm or _default_llm()
    user = json.dumps({
        "current_intent": current_for_prompt(current),
        "history": [list(turn) for turn in (history or [])][-HISTORY_TURNS:],
        "message": text,
    }, ensure_ascii=False)
    try:
        raw = llm(build_system(), user, RawIntent)
    except Exception:                             # provider failure after A3's retries
        log.exception("A1: model call failed")
        return Intent(kind="chitchat", answer=FAILED)
    return to_intent(raw)


if __name__ == "__main__":                        # python -m app.nlp.parser "create a storage account"
    import sys
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    print(parse([], None, " ".join(sys.argv[1:])).model_dump_json(indent=2))
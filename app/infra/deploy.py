# app/infra/deploy.py
import json
import logging
import os
import secrets
import shutil
import string
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.infra.registry import REGISTRY
from app.llm.guardrails import MAX_MONTHLY_COST_USD, check_intent

logger = logging.getLogger(__name__)

BASE = Path(__file__).parent
AZ_TIMEOUT_SECONDS = 600

PLANS: dict[str, dict] = {}
DEPLOYMENTS: dict[str, dict] = {}

# Rough monthly estimates in USD. Label as estimates; verify with the pricing calculator.
COST = {"B1": 13, "F1": 0, "Basic": 5, "S0": 15, "Standard_LRS": 1, "standard": 0}
DEFAULT_SKU = {"webapp": "B1", "storage": "Standard_LRS", "sql": "Basic", "keyvault": "standard"}


class AzError(Exception):
    pass


def _rg() -> str:
    """The only resource group this module may touch. From config, never from the model."""
    return os.environ.get("AZ_RESOURCE_GROUP", "rg-ai-sandbox")


def friendly(stderr: str) -> str:
    """Translate raw Azure CLI errors into one plain sentence."""
    s = (stderr or "").lower()
    if "not registered for resource provider" in s or "missingsubscriptionregistration" in s:
        return "A required Azure resource provider is not registered yet."
    if "already in use" in s or "already taken" in s or "alreadytaken" in s:
        return "That name is already taken. Choose another one."
    if "quota" in s:
        return "Azure quota exceeded. Try a smaller size or another region."
    if "not accepting" in s:
        return "That region is not accepting new servers. Try another region."
    if "skunotavailable" in s or "sku is not available" in s:
        return "That SKU is not available here. Try another size or region."
    if "resourcegroupnotfound" in s:
        return "The sandbox resource group does not exist. Create it first."
    if "az login" in s:
        return "You are not signed in to Azure. Run az login first."
    lines = (stderr or "").strip().splitlines()
    return lines[-1] if lines else "Azure returned an error."


def run_az(args: list[str]):
    """Run the Azure CLI, parse its JSON output, raise AzError with a plain message."""
    az = shutil.which("az") or "az"  # resolves az.cmd on Windows
    try:
        p = subprocess.run([az, *args, "--output", "json"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=AZ_TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise AzError("The Azure CLI (az) is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        raise AzError("The Azure CLI took too long to answer.")
    if p.returncode != 0:
        raise AzError(friendly(p.stderr))
    if not p.stdout.strip():
        return {}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise AzError("The Azure CLI returned an unexpected answer.")


def _params_file(params: dict) -> str:
    body = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {k: {"value": v} for k, v in params.items()},
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.chmod(path, 0o600)
    return path


def _remove(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _az_with_params(args: list[str], params: dict):
    """Run az with a temporary parameters file, always deleted afterwards."""
    pf = _params_file(params)
    try:
        return run_az([*args, "-p", f"@{pf}"])
    finally:
        _remove(pf)


def _new_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "Aa1!" + "".join(secrets.choice(alphabet) for _ in range(20))


def _split_resource_id(rid: str) -> tuple[str, str]:
    """'/.../providers/Microsoft.Sql/servers/x/databases/y' -> ('Microsoft.Sql/servers/databases', 'y')"""
    parts = rid.split("/")
    lower = [p.lower() for p in parts]
    if "providers" not in lower:
        return rid, parts[-1]
    tail = parts[lower.index("providers") + 1:]
    namespace, rest = tail[0], tail[1:]
    types, names = rest[0::2], rest[1::2]
    return namespace + "/" + "/".join(types), (names[-1] if names else "")


def _what_if(file: str, params: dict) -> list[dict]:
    out = _az_with_params(["deployment", "group", "what-if", "-g", _rg(),
                           "-f", str(BASE / file), "--no-pretty-print"], params)
    return out.get("changes", [])


def plan(intent) -> dict:
    """Validate, preview with what-if, and store a plan. Nothing is created."""
    problems = check_intent(intent)  # second line of defence
    if problems:
        raise AzError("; ".join(problems))

    summary, warnings, cost = [], [], 0
    types = {r.type.value for r in intent.resources}
    for r in intent.resources:
        spec = REGISTRY.get(r.type)
        if spec is None:
            raise AzError(f"No template is registered for {r.type.value}.")
        params = spec.to_params(r)
        if r.type.value == "sql":
            params["adminPassword"] = "Placeholder1!"  # what-if only, never deployed
        for ch in _what_if(spec.file, params):
            if ch.get("changeType") == "Ignore":
                continue
            rtype, name = _split_resource_id(ch.get("resourceId", ""))
            summary.append({"change": ch.get("changeType"), "resource": rtype, "name": name})
        cost += COST.get(r.sku or DEFAULT_SKU.get(r.type.value, ""), 0)

    if "sql" in types:
        warnings.append("SQL server allows Azure public access; use it only in the sandbox.")
    if {"webapp", "sql"} <= types:
        warnings.append("The web app and the database are deployed separately, "
                        "so the app has no connection string.")
    if any(s["change"] == "Delete" for s in summary):
        warnings.append("This plan deletes existing resources.")
    if cost > MAX_MONTHLY_COST_USD:
        warnings.append(f"Estimated cost ${cost}/month is above the ${MAX_MONTHLY_COST_USD} limit.")

    plan_id = "p_" + uuid.uuid4().hex[:6]
    result = {"type": "plan", "plan_id": plan_id, "summary": summary,
              "estimated_monthly_cost_usd": cost, "warnings": warnings}
    PLANS[plan_id] = {"intent": intent, "result": result, "deployed": False}
    logger.info("plan %s created with %d changes", plan_id, len(summary))
    return result


def deploy(plan_id: str) -> dict:
    """Start the deployments of a stored plan (incremental, asynchronous)."""
    p = PLANS.get(plan_id)
    if p is None:
        raise AzError("This plan does not exist. Please ask again.")
    if p["deployed"]:
        raise AzError("This plan was already deployed.")
    p["deployed"] = True

    dep_id = "d_" + uuid.uuid4().hex[:6]
    names, secrets_out = [], {}
    for i, r in enumerate(p["intent"].resources):
        spec = REGISTRY[r.type]
        params = spec.to_params(r)
        if r.type.value == "sql":
            pw = _new_password()
            params["adminPassword"] = pw
            secrets_out["sql_admin_password"] = pw  # shown once, never logged
        name = f"{dep_id}-{i}"
        try:
            _az_with_params(["deployment", "group", "create", "-g", _rg(), "-n", name,
                             "-f", str(BASE / spec.file), "--mode", "Incremental", "--no-wait"],
                            params)
        except AzError as e:
            DEPLOYMENTS[dep_id] = {"names": names, "secrets": {}, "error": str(e)}
            return {"deployment_id": dep_id, "state": "failed", "message": str(e)}
        names.append(name)

    DEPLOYMENTS[dep_id] = {"names": names, "secrets": secrets_out, "error": None}
    logger.info("deployment %s started with %d resources", dep_id, len(names))
    return {"deployment_id": dep_id, "state": "running", "message": "Deployment started"}


def status(dep_id: str) -> dict:
    d = DEPLOYMENTS.get(dep_id)
    if d is None:
        raise AzError("Unknown deployment.")
    if d["error"]:
        return {"deployment_id": dep_id, "state": "failed", "message": d["error"]}

    states, outputs = [], {}
    for n in d["names"]:
        info = run_az(["deployment", "group", "show", "-g", _rg(), "-n", n])
        props = info.get("properties", {})
        state = props.get("provisioningState")
        if state in ("Failed", "Canceled"):
            err = (props.get("error") or {}).get("message", "")
            return {"deployment_id": dep_id, "state": "failed",
                    "message": friendly(err) if err else "A deployment failed."}
        states.append(state)
        for k, v in (props.get("outputs") or {}).items():
            outputs[k] = v.get("value")

    if states and all(s == "Succeeded" for s in states):
        message = "Done"
        if d["secrets"]:
            outputs.update(d["secrets"])
            d["secrets"] = {}  # handed out once
            message = "Done. Save the SQL admin password now: it is shown only once."
        return {"deployment_id": dep_id, "state": "succeeded", "message": message,
                "outputs": outputs}
    return {"deployment_id": dep_id, "state": "running", "message": "Working"}


def cleanup(resource_group: str | None = None):
    """Delete the sandbox group (tests only). Any other group is refused."""
    rg = resource_group or _rg()
    if rg != _rg():
        raise AzError("Only the configured sandbox resource group can be deleted.")
    run_az(["group", "delete", "-n", rg, "--yes", "--no-wait"])
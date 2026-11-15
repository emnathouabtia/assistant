import json
import logging
import os
from types import SimpleNamespace

import pytest

from app.contracts import Intent, ResourceType
from app.infra import deploy
from app.infra.registry import REGISTRY, TemplateSpec

PREFIX = "/subscriptions/s/resourceGroups/rg-test/providers/"
RID_STORAGE = PREFIX + "Microsoft.Storage/storageAccounts/stshopx7k2"
RID_SQL_SERVER = PREFIX + "Microsoft.Sql/servers/sql-shop-x7k2"
RID_SQL_DB = PREFIX + "Microsoft.Sql/servers/sql-shop-x7k2/databases/shop-db"

STORAGE = {"type": "storage", "name": "shop", "region": "spaincentral", "sku": "Standard_LRS"}
SQL = {"type": "sql", "name": "shop", "region": "spaincentral", "sku": "Basic"}
WEBAPP = {"type": "webapp", "name": "shop", "region": "spaincentral", "sku": None,
          "runtime": "python"}


def make_intent(resources):
    return Intent.model_validate({"kind": "action", "resources": resources})


def what_if_reply(*items):
    changes = [{"changeType": c, "resourceId": rid} for c, rid in items]
    return (0, json.dumps({"status": "Succeeded", "changes": changes}), "")


def show_reply(state, outputs=None, error=None):
    props = {"provisioningState": state}
    if outputs:
        props["outputs"] = {k: {"value": v} for k, v in outputs.items()}
    if error:
        props["error"] = {"message": error}
    return (0, json.dumps({"properties": props}), "")


class FakeAz:
    def __init__(self):
        self.calls, self.replies, self.paths, self.bodies = [], [], [], []

    def run(self, cmd, **kwargs):
        args = list(cmd[1:])
        self.calls.append(args)
        for a in args:
            if a.startswith("@"):
                self.paths.append(a[1:])
                with open(a[1:], encoding="utf-8") as f:
                    self.bodies.append(json.load(f))
        code, out, err = self.replies.pop(0) if self.replies else (0, "{}", "")
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def params(r):
        return {"baseName": r.name, "location": r.region}

    for t in (ResourceType.storage, ResourceType.sql, ResourceType.webapp):
        monkeypatch.setitem(REGISTRY, t, TemplateSpec(f"modules/{t.value}.bicep", params))
    monkeypatch.setenv("AZ_RESOURCE_GROUP", "rg-test")
    monkeypatch.setattr(deploy, "PLANS", {})
    monkeypatch.setattr(deploy, "DEPLOYMENTS", {})


@pytest.fixture
def az(monkeypatch):
    fake = FakeAz()
    monkeypatch.setattr(deploy.subprocess, "run", fake.run)
    return fake


# ---------- plan ----------

def test_plan_reports_resource_level_changes(az):
    az.replies = [what_if_reply(("Create", RID_STORAGE))]
    result = deploy.plan(make_intent([STORAGE]))
    assert result["plan_id"].startswith("p_")
    assert result["summary"] == [{"change": "Create",
                                  "resource": "Microsoft.Storage/storageAccounts",
                                  "name": "stshopx7k2"}]
    assert result["estimated_monthly_cost_usd"] == 1
    assert result["plan_id"] in deploy.PLANS


def test_plan_handles_nested_resource_ids_and_sql_warning(az):
    az.replies = [what_if_reply(("Create", RID_SQL_SERVER), ("Create", RID_SQL_DB))]
    result = deploy.plan(make_intent([SQL]))
    assert [s["resource"] for s in result["summary"]] == [
        "Microsoft.Sql/servers", "Microsoft.Sql/servers/databases"]
    assert [s["name"] for s in result["summary"]] == ["sql-shop-x7k2", "shop-db"]
    assert any("public access" in w for w in result["warnings"])


def test_plan_skips_ignored_changes(az):
    az.replies = [what_if_reply(("Ignore", RID_STORAGE), ("Create", RID_STORAGE))]
    result = deploy.plan(make_intent([STORAGE]))
    assert len(result["summary"]) == 1


def test_plan_rejects_guardrail_violations_without_calling_azure(az):
    with pytest.raises(deploy.AzError, match="Region eastus"):
        deploy.plan(make_intent([{**STORAGE, "region": "eastus"}]))
    assert az.calls == []


def test_plan_fails_when_no_template_is_registered(az, monkeypatch):
    monkeypatch.delitem(REGISTRY, ResourceType.storage)
    with pytest.raises(deploy.AzError, match="No template"):
        deploy.plan(make_intent([STORAGE]))


def test_plan_never_contains_the_placeholder_password(az):
    az.replies = [what_if_reply(("Create", RID_SQL_SERVER))]
    result = deploy.plan(make_intent([SQL]))
    assert az.bodies[0]["parameters"]["adminPassword"]["value"] == "Placeholder1!"
    assert "Placeholder1" not in json.dumps(result)


def test_plan_cost_uses_default_sku_when_missing(az):
    result = deploy.plan(make_intent([WEBAPP]))
    assert result["estimated_monthly_cost_usd"] == 13


def test_plan_warns_when_cost_is_above_limit(az, monkeypatch):
    monkeypatch.setattr(deploy, "MAX_MONTHLY_COST_USD", 1)
    result = deploy.plan(make_intent([SQL]))
    assert any("limit" in w for w in result["warnings"])


def test_plan_warns_that_webapp_and_sql_are_not_linked(az):
    result = deploy.plan(make_intent([WEBAPP, SQL]))
    assert any("connection string" in w for w in result["warnings"])


# ---------- parameters file ----------

def test_params_file_is_removed_after_success(az):
    az.replies = [what_if_reply(("Create", RID_STORAGE))]
    deploy.plan(make_intent([STORAGE]))
    assert az.paths and not any(os.path.exists(p) for p in az.paths)


def test_params_file_is_removed_even_when_az_fails(az):
    az.replies = [(1, "", "ERROR: quota exceeded")]
    with pytest.raises(deploy.AzError, match="quota"):
        deploy.plan(make_intent([STORAGE]))
    assert az.paths and not any(os.path.exists(p) for p in az.paths)


# ---------- errors ----------

@pytest.mark.parametrize("stderr, expected", [
    ("The subscription is not registered for resource provider Microsoft.Web", "not registered"),
    ("StorageAccountAlreadyTaken: the name is already taken", "already taken"),
    ("QuotaExceeded", "quota"),
    ("Location is not accepting creation of new Windows Azure SQL Database servers",
     "not accepting"),
    ("SkuNotAvailable", "sku"),
    ("ResourceGroupNotFound", "resource group"),
    ("Please run 'az login' to setup account.", "az login"),
])
def test_friendly_messages(stderr, expected):
    assert expected in deploy.friendly(stderr).lower()


def test_friendly_falls_back_to_last_line_or_default():
    assert deploy.friendly("line one\nthe real problem") == "the real problem"
    assert deploy.friendly("") == "Azure returned an error."


def test_missing_az_cli_gives_a_clear_error(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(deploy.subprocess, "run", boom)
    with pytest.raises(deploy.AzError, match="not installed"):
        deploy.run_az(["account", "show"])


def test_split_resource_id_without_providers():
    assert deploy._split_resource_id("/foo/bar") == ("/foo/bar", "bar")


# ---------- deploy ----------

def test_deploy_is_incremental_asynchronous_and_sandbox_only(az):
    az.replies = [what_if_reply(("Create", RID_STORAGE))]
    plan = deploy.plan(make_intent([STORAGE]))
    dep = deploy.deploy(plan["plan_id"])
    assert dep["state"] == "running" and dep["deployment_id"].startswith("d_")

    creates = [c for c in az.calls if c[:3] == ["deployment", "group", "create"]]
    assert len(creates) == 1
    args = creates[0]
    assert args[args.index("--mode") + 1] == "Incremental"
    assert "--no-wait" in args
    assert "Complete" not in sum(az.calls, [])
    for call in az.calls:
        if "-g" in call:
            assert call[call.index("-g") + 1] == "rg-test"


def test_deploy_unknown_plan_is_rejected(az):
    with pytest.raises(deploy.AzError, match="does not exist"):
        deploy.deploy("p_nope")


def test_deploy_twice_is_rejected(az):
    plan = deploy.plan(make_intent([STORAGE]))
    deploy.deploy(plan["plan_id"])
    with pytest.raises(deploy.AzError, match="already deployed"):
        deploy.deploy(plan["plan_id"])


def test_deploy_start_failure_returns_failed(az):
    az.replies = [what_if_reply(("Create", RID_STORAGE)),
                  (1, "", "ERROR: The storage account name is already taken.")]
    plan = deploy.plan(make_intent([STORAGE]))
    dep = deploy.deploy(plan["plan_id"])
    assert dep["state"] == "failed" and "already taken" in dep["message"]
    assert deploy.status(dep["deployment_id"])["state"] == "failed"


def test_sql_password_is_generated_at_deploy_and_shown_once(az, caplog):
    caplog.set_level(logging.DEBUG)
    outputs = {"serverFqdn": "x.database.windows.net"}
    az.replies = [what_if_reply(("Create", RID_SQL_SERVER)),   # plan
                  (0, "{}", ""),                               # create --no-wait
                  show_reply("Succeeded", outputs),
                  show_reply("Succeeded", outputs)]
    plan = deploy.plan(make_intent([SQL]))
    dep = deploy.deploy(plan["plan_id"])

    pw = az.bodies[-1]["parameters"]["adminPassword"]["value"]
    assert pw != "Placeholder1!" and len(pw) >= 20
    assert pw not in json.dumps(plan)

    first = deploy.status(dep["deployment_id"])
    assert first["state"] == "succeeded"
    assert first["outputs"]["sql_admin_password"] == pw
    assert first["outputs"]["serverFqdn"] == "x.database.windows.net"
    assert "password" in first["message"].lower()

    second = deploy.status(dep["deployment_id"])
    assert "sql_admin_password" not in second.get("outputs", {})
    assert pw not in caplog.text


# ---------- status ----------

def test_status_running_while_deployment_is_in_progress(az):
    plan = deploy.plan(make_intent([STORAGE]))
    dep = deploy.deploy(plan["plan_id"])
    az.replies = [show_reply("Running")]
    assert deploy.status(dep["deployment_id"])["state"] == "running"


def test_status_failed_uses_a_friendly_message(az):
    plan = deploy.plan(make_intent([STORAGE]))
    dep = deploy.deploy(plan["plan_id"])
    az.replies = [show_reply("Failed", error="QuotaExceeded for this region")]
    result = deploy.status(dep["deployment_id"])
    assert result["state"] == "failed" and "quota" in result["message"].lower()


def test_status_unknown_deployment(az):
    with pytest.raises(deploy.AzError, match="Unknown deployment"):
        deploy.status("d_nope")


# ---------- cleanup ----------

def test_cleanup_only_deletes_the_sandbox_group(az):
    with pytest.raises(deploy.AzError, match="Only the configured"):
        deploy.cleanup("some-other-group")
    assert az.calls == []
    deploy.cleanup()
    assert az.calls[0][:4] == ["group", "delete", "-n", "rg-test"]
    assert "--yes" in az.calls[0]
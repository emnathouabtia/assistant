import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.contracts import ResourceSpec, ResourceType
from app.infra import data_registry  # noqa: F401  (registers the templates)
from app.infra.data_registry import base_name, keyvault_params, sql_params, storage_params
from app.infra.registry import REGISTRY, clean
from app.llm.guardrails import ALLOWED_SKUS

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "app" / "infra" / "modules"

# template name -> the parameter that carries the SKU
SKU_PARAM = {
    ResourceType.storage: ("storage", "skuName"),
    ResourceType.keyvault: ("keyvault", "skuName"),
    ResourceType.sql: ("sql", "dbSku"),
}

# The output names B3 reads after a successful deployment.
B3_OUTPUTS = {
    "storage": {"storageAccountName", "blobEndpoint"},
    "sql": {"serverFqdn", "databaseName"},
    "keyvault": {"vaultName", "vaultUri"},
}


# ---------- parameter mapping (no Azure needed) ----------

def test_storage_params_use_the_allowed_defaults():
    p = storage_params(ResourceSpec(type="storage", name="demo"))
    assert p == {
        "baseName": "demo",
        "location": "spaincentral",
        "skuName": "Standard_LRS",
        "tags": {"createdBy": "ai-assistant"},
    }


def test_storage_params_keep_the_requested_sku_and_region():
    p = storage_params(ResourceSpec(type="storage", name="demo", region="spaincentral",
                                    sku="Standard_LRS"))
    assert p["skuName"] == "Standard_LRS"
    assert p["location"] == "spaincentral"


def test_storage_base_name_is_at_most_eight_characters():
    p = storage_params(ResourceSpec(type="storage", name="long-storage-name"))
    assert p["baseName"] == "longstor"
    assert len("st" + p["baseName"]) + 13 <= 24


def test_keyvault_base_name_is_at_most_six_characters():
    p = keyvault_params(ResourceSpec(type="keyvault", name="long-vault-name"))
    assert p["baseName"] == "longva"
    assert p["skuName"] == "standard"
    assert len("kv-" + p["baseName"] + "-") + 13 <= 24


def test_sql_params_never_contain_the_password():
    p = sql_params(ResourceSpec(type="sql", name="shop"))
    assert "adminPassword" not in p
    assert not [k for k in p if "password" in k.lower()]
    assert p["dbSku"] == "Basic"
    assert p["baseName"] == "shop"


def test_sql_server_name_stays_within_the_azure_limit():
    p = sql_params(ResourceSpec(type="sql", name="a" * 24))
    assert len(p["baseName"]) == 20
    assert len("sql-" + p["baseName"] + "-") + 13 <= 63

def test_clean_drops_non_ascii_letters():
    # Azure names are ASCII only, so an accented letter must not survive.
    assert clean("Café") == "caf"


@pytest.mark.parametrize("raw", ["a-b", "cafe", "123", "My-Shop_01", "x",
                                "verylongname-that-exceeds-eight"])
def test_base_name_always_satisfies_the_templates(raw):
    for limit in (8, 6, 20):
        b = base_name(raw, limit)
        assert 3 <= len(b) <= limit
        assert b == b.lower()
        assert b.isascii() and b.isalnum()


def test_base_name_pads_names_that_are_too_short():
    assert base_name("a-b", 8) == "abx"


def test_base_name_truncates_before_padding():
    assert base_name("my-shop-store", 8) == "myshopst"


# ---------- registration ----------

def test_data_templates_are_registered_on_import():
    for rtype in (ResourceType.storage, ResourceType.sql, ResourceType.keyvault):
        assert rtype in REGISTRY
        assert (MODULES.parent / REGISTRY[rtype].file).is_file()


def test_importing_the_deploy_module_populates_the_registry():
    """The production bug: B3 imported REGISTRY but nothing registered templates."""
    code = ("import app.infra.deploy\n"
            "from app.infra.registry import REGISTRY\n"
            "print(sorted(t.value for t in REGISTRY))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "['keyvault', 'sql', 'storage', 'webapp']" in result.stdout


# ---------- compiled templates (needs the Azure CLI) ----------

@pytest.fixture(scope="module")
def arm():
    if shutil.which("az") is None:
        pytest.skip("Azure CLI not installed")
    compiled = {}
    for name in ("storage", "sql", "keyvault"):
        result = subprocess.run(
            ["az", "bicep", "build", "--file", str(MODULES / f"{name}.bicep"), "--stdout"],
            capture_output=True, text=True, shell=True,
        )
        assert result.returncode == 0, result.stderr
        compiled[name] = json.loads(result.stdout)
    return compiled


@pytest.mark.parametrize("template", ["storage", "sql", "keyvault"])
def test_templates_compile(arm, template):
    assert arm[template]["resources"]
    assert arm[template]["$schema"].endswith("deploymentTemplate.json#")


@pytest.mark.parametrize("template,expected", B3_OUTPUTS.items())
def test_outputs_match_the_b3_contract(arm, template, expected):
    assert set(arm[template]["outputs"]) == expected


def test_sql_password_is_secure_and_has_no_default(arm):
    param = arm["sql"]["parameters"]["adminPassword"]
    assert param["type"].lower() == "securestring"
    assert "defaultValue" not in param


@pytest.mark.parametrize("rtype", list(SKU_PARAM))
def test_the_registry_sku_is_allowed_by_the_template(arm, rtype):
    template, param = SKU_PARAM[rtype]
    allowed = set(arm[template]["parameters"][param]["allowedValues"])
    value = REGISTRY[rtype].to_params(ResourceSpec(type=rtype, name="demo"))[param]
    assert value in allowed


@pytest.mark.parametrize("rtype", list(SKU_PARAM))
def test_every_guardrail_sku_is_allowed_by_the_template(arm, rtype):
    template, param = SKU_PARAM[rtype]
    allowed = set(arm[template]["parameters"][param]["allowedValues"])
    assert ALLOWED_SKUS[rtype.value] <= allowed


@pytest.mark.parametrize("template", ["storage", "sql", "keyvault"])
def test_base_name_limits_are_enforced_by_the_templates(arm, template):
    param = arm[template]["parameters"]["baseName"]
    assert param["minLength"] == 3
    assert param["maxLength"] == {"storage": 8, "sql": 20, "keyvault": 6}[template]
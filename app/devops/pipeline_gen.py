# app/devops/pipeline_gen.py
import re
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    keep_trailing_newline=True,
    undefined=StrictUndefined,  # a missing value is an error, never an empty string
)

DEFAULTS = {
    "python": {"template": "python.yml.j2", "python_version": "3.12", "test_command": "pytest"},
    "node": {"template": "node.yml.j2", "node_version": "20.x", "test_command": "npm test"},
}

# Values come from the language model, so they are checked in code before reaching the YAML.
ALLOWED_TEST_COMMANDS = {
    "python": {"pytest", "python -m pytest", "python -m unittest"},
    "node": {"npm test"},
}
APP_NAME = re.compile(r"[A-Za-z0-9-]{2,60}")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,100}")
SERVICE_CONNECTION = re.compile(r"[A-Za-z0-9._-]{1,100}")


def _check(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def generate_pipeline(spec, app_name: str, service_connection: str = "sc-azure") -> str:
    """Return azure-pipelines.yml text for a pipeline ResourceSpec.

    app_name must be the real web app name (the siteName output of the webapp deployment).
    """
    runtime = (spec.runtime or "python").lower()
    if runtime not in DEFAULTS:
        raise ValueError(f"Unsupported runtime: {runtime}. Supported: {sorted(DEFAULTS)}")
    cfg = dict(DEFAULTS[runtime])

    test_command = spec.params.get("test_command", cfg["test_command"])
    if test_command not in ALLOWED_TEST_COMMANDS[runtime]:
        raise ValueError(f"Invalid test command: {test_command!r}. "
                         f"Allowed: {sorted(ALLOWED_TEST_COMMANDS[runtime])}")
    cfg["test_command"] = test_command

    template = cfg.pop("template")
    text = env.get_template(template).render(
        branch=_check(spec.params.get("branch", "main"), BRANCH, "branch"),
        app_name=_check(app_name, APP_NAME, "app name"),
        service_connection=_check(service_connection, SERVICE_CONNECTION, "service connection"),
        **cfg,
    )
    validate_yaml(text)
    return text


def validate_yaml(text: str):
    """Raise ValueError if the pipeline text is not usable. Run before anything is pushed."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Pipeline YAML is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ValueError("Pipeline YAML must be a mapping.")
    for key in ("trigger", "pool", "stages"):
        if key not in data:
            raise ValueError(f"Pipeline YAML is missing '{key}'")
    if not data["stages"]:
        raise ValueError("Pipeline YAML has no stages")
    for stage in data["stages"]:
        if not isinstance(stage, dict) or not stage.get("jobs"):
            raise ValueError("Every stage needs at least one job.")
    if "${{" in text:  # would collide with Azure template expressions
        raise ValueError("Azure template expressions are not allowed in generated pipelines.")
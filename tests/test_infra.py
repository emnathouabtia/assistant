from app.contracts import ResourceSpec
from app.infra.webapp_registry import webapp_params


def test_defaults():
    p = webapp_params(ResourceSpec(type="webapp", name="demo"))
    assert p["skuName"] == "B1"
    assert p["linuxFxVersion"] == "PYTHON|3.12"
    assert p["appName"] == "demo"


def test_node_runtime():
    p = webapp_params(ResourceSpec(type="webapp", name="demo", runtime="node"))
    assert p["linuxFxVersion"] == "NODE|20-lts"


def test_uppercase_runtime():
    p = webapp_params(ResourceSpec(type="webapp", name="demo", runtime="Python"))
    assert p["linuxFxVersion"] == "PYTHON|3.12"


def test_tags_are_set():
    p = webapp_params(ResourceSpec(type="webapp", name="demo"))
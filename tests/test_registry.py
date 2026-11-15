from app.infra.registry import TemplateSpec, REGISTRY, register, clean, COMMON_TAGS
from app.contracts import ResourceType


def test_clean():
    assert clean("My-Shop_01") == "myshop01"


def test_register():
    spec = TemplateSpec("modules/x.bicep", lambda r: {})
    register(ResourceType.webapp, spec)
    assert REGISTRY[ResourceType.webapp] is spec


def test_common_tags():
    assert COMMON_TAGS["createdBy"] == "ai-assistant"
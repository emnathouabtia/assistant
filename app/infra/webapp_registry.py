from app.contracts import ResourceSpec, ResourceType
from app.infra.registry import COMMON_TAGS, TemplateSpec, register
RUNTIMES = {"python": "PYTHON|3.12", "node": "NODE|20-lts"}
def webapp_params(r:ResourceSpec) -> dict:
    return {
        "appName": r.name,
        "location": r.region,
        "skuName": r.sku or "B1",
        "linuxFxVersion": RUNTIMES.get((r.runtime or "python").lower(), "PYTHON|3.12"),
        "tags": COMMON_TAGS,
    }

register(ResourceType.webapp, TemplateSpec("modules/webapp.bicep", webapp_params))
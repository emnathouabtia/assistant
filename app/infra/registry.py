# app/infra/registry.py
from dataclasses import dataclass
from typing import Callable

from app.contracts import ResourceSpec, ResourceType


@dataclass
class TemplateSpec:
    file: str                                   # relative to app/infra/
    to_params: Callable[[ResourceSpec], dict]   # ResourceSpec -> Bicep parameters


REGISTRY: dict[ResourceType, TemplateSpec] = {}


def register(rtype: ResourceType, spec: TemplateSpec):
    REGISTRY[rtype] = spec


def clean(name: str) -> str:
    """Letters and digits only, lowercase (for storage account names)."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


COMMON_TAGS = {"createdBy": "ai-assistant"}
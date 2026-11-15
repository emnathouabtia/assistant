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
    """ASCII letters and digits only, lowercase (for storage account names).

    Azure names are restricted to ASCII, so accented letters must be dropped:
    `clean("Café")` returns "caf", not "café".
    """
    return "".join(ch for ch in name.lower() if ch.isascii() and ch.isalnum())


COMMON_TAGS = {"createdBy": "ai-assistant"}
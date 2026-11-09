from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
class ResourceType(str, Enum):
    webapp = "webapp"
    storage = "storage"
    sql = "sql"
    keyvault = "keyvault"
    pipeline = "pipeline"
    
class ResourceSpec(BaseModel):
    type: ResourceType
    name: str = Field(min_length=3, max_length=24, pattern=r"^[a-z0-9-]+$")
    region: str = "spaincentral"
    sku: Optional[str] = None # e.g. "B1", "Standard_LRS", "Basic"
    runtime: Optional[str] = None # webapp / pipeline: "python", "node"
    params: dict = Field(default_factory=dict) # type-specific extras

class Intent(BaseModel):
    kind: Literal["action", "question", "confirm", "cancel", "chitchat"]
    resources: List[ResourceSpec] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    clarifying_question: Optional[str] = None
    answer: Optional[str] = None # for kind == "question" or "chitchat"
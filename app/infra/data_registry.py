"""B2 registry entries: Storage, Azure SQL and Key Vault.

Each entry maps a `ResourceSpec` from the intent to the parameters of one Bicep
template, and registers it so B3 (`app.infra.deploy`) can find it in `REGISTRY`.
"""
from app.contracts import ResourceSpec, ResourceType
from app.infra.registry import COMMON_TAGS, TemplateSpec, clean, register

# The templates add a prefix and a 13-character uniqueString, so the base name
# has to stay short enough for Azure's own name limits:
#   storage:  'st' + 8 + 13          = 23  (max 24)
#   keyvault: 'kv-' + 6 + '-' + 13   = 23  (max 24)
#   sql:      'sql-' + 20 + '-' + 13 = 38  (max 63)
STORAGE_BASE = 8
KEYVAULT_BASE = 6
SQL_BASE = 20

MIN_BASE = 3


def base_name(name: str, limit: int) -> str:
    """Turn a resource name into a base name the templates accept.

    Lowercase letters and digits only (`clean`), at most `limit` characters,
    and at least 3 characters because every template has `@minLength(3)`.
    A degenerate name such as "a-b" is padded with "x" so validation still passes.
    """
    cleaned = clean(name) or "app"
    return cleaned[:limit].ljust(MIN_BASE, "x")


def storage_params(r: ResourceSpec) -> dict:
    return {
        "baseName": base_name(r.name, STORAGE_BASE),
        "location": r.region,
        "skuName": r.sku or "Standard_LRS",
        "tags": COMMON_TAGS,
    }


def keyvault_params(r: ResourceSpec) -> dict:
    return {
        "baseName": base_name(r.name, KEYVAULT_BASE),
        "location": r.region,
        "skuName": r.sku or "standard",
        "tags": COMMON_TAGS,
    }


def sql_params(r: ResourceSpec) -> dict:
    # adminPassword is deliberately absent. B3 generates it at deploy time and
    # passes it only through a temporary parameters file, so no secret is ever
    # stored in the registry, the plan or the logs.
    return {
        "baseName": base_name(r.name, SQL_BASE),
        "location": r.region,
        "dbSku": r.sku or "Basic",
        "tags": COMMON_TAGS,
    }


register(ResourceType.storage, TemplateSpec("modules/storage.bicep", storage_params))
register(ResourceType.keyvault, TemplateSpec("modules/keyvault.bicep", keyvault_params))
register(ResourceType.sql, TemplateSpec("modules/sql.bicep", sql_params))
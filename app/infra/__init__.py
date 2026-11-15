"""Infrastructure templates and their registry.

Importing this package registers every Bicep template, so B3 (`app.infra.deploy`)
finds all of them in `REGISTRY` without the caller importing each registry module.
"""

from . import data_registry, webapp_registry  # noqa: F401  (imported for register())
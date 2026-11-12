# app/llm/guardrails.py
ALLOWED_TYPES = {"webapp", "storage", "sql", "keyvault", "pipeline"}
ALLOWED_SKUS = {
    "webapp": {"F1", "B1"},
    "storage": {"Standard_LRS"},
    "sql": {"Basic"},
    "keyvault": {"standard"},
}
# One region for the whole project. Keep in sync with the default region in
# app/contracts.py, AZ_DEFAULT_REGION in .env.example and the Bicep templates.
ALLOWED_REGIONS = {"spaincentral"}
MAX_RESOURCES = 5
MAX_MONTHLY_COST_USD = 30


def check_intent(intent) -> list[str]:
    """Return a list of violations. An empty list means the intent is allowed."""
    problems = []
    if len(intent.resources) > MAX_RESOURCES:
        problems.append(f"Too many resources (max {MAX_RESOURCES}).")
    for r in intent.resources:
        t = r.type.value
        if t not in ALLOWED_TYPES:
            problems.append(f"Resource type {t} is not supported.")
        if r.region not in ALLOWED_REGIONS:
            problems.append(f"Region {r.region} is not allowed.")
        allowed = ALLOWED_SKUS.get(t)
        if allowed and r.sku and r.sku not in allowed:
            problems.append(f"SKU {r.sku} not allowed for {t}. Allowed: {sorted(allowed)}.")
    return problems
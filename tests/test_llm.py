from app.contracts import Intent
from app.llm.guardrails import check_intent, MAX_RESOURCES


def make(resources):
    return Intent.model_validate({"kind": "action", "resources": resources})


def res(type_="webapp", name="shop", region="spaincentral", sku=None):
    return {"type": type_, "name": name, "region": region, "sku": sku}


def test_valid_intent_has_no_problems():
    intent = make([res("storage", sku="Standard_LRS"), res("sql", sku="Basic")])
    assert check_intent(intent) == []


def test_default_region_of_contract_is_allowed():
    intent = make([{"type": "storage", "name": "shop"}])  # uses the contract's default region
    assert check_intent(intent) == []


def test_region_not_allowed():
    problems = check_intent(make([res(region="eastus")]))
    assert any("Region eastus" in p for p in problems)


def test_old_default_region_is_now_rejected():
    problems = check_intent(make([res(region="westeurope")]))
    assert any("Region westeurope" in p for p in problems)


def test_sku_not_allowed():
    problems = check_intent(make([res("webapp", sku="P3v3")]))
    assert any("SKU P3v3" in p for p in problems)


def test_sku_none_is_accepted():
    assert check_intent(make([res("webapp", sku=None)])) == []


def test_too_many_resources():
    many = [res(name=f"app{i}") for i in range(MAX_RESOURCES + 1)]
    problems = check_intent(make(many))
    assert any("Too many resources" in p for p in problems)


def test_hundred_large_servers_rejected():
    many = [res(name=f"srv{i}", sku="P3v3") for i in range(100)]
    assert check_intent(make(many)) != []
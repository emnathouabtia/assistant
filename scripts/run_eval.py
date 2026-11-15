import json
from app.nlp.parser import parse
cases = json.load(open("app/nlp/eval_set.json"))
passed = 0
for c in cases:
    got = parse([], None, c["input"])
    ok = got.kind == c["expected"]["kind"] and \
        [r.type.value for r in got.resources] == \
        [r["type"] for r in c["expected"].get("resources", [])]
    passed += ok
    if not ok:
        print("FAIL:", c["input"], "->", got.model_dump())
print(f"{passed}/{len(cases)} passed")

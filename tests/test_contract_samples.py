import json
from pathlib import Path

from app.contracts import Intent


SAMPLES_DIR = Path(__file__).parents[1] / "app" / "nlp" / "samples"


def test_all_sample_intents_match_contract():
    sample_files = sorted(SAMPLES_DIR.glob("*.json"))
    assert sample_files, f"No sample JSON files found in {SAMPLES_DIR}"

    for sample_file in sample_files:
        data = json.loads(sample_file.read_text(encoding="utf-8"))
        intent = Intent.model_validate(data)
        assert intent.resources, f"{sample_file.name} has no resources"
"""Contract tests — adapters vs recorded real-Backend responses (§10.3 rule 1,
§21.5).

"Every adapter MUST have a contract test using recorded real responses (stored
under `tests/contract/fixtures/<backend>/<version>/`). If no recording exists,
the adapter is incomplete."

NO RECORDINGS EXIST YET: the sandbox has no real LM Studio / Ollama to capture
(docs/fixtures/CAPTURE.md holds the capture commands; owner action — see
docs/fixtures/CAPTURE.md and the M1 blocker list). These tests therefore run
as an *announced skip* until fixtures land, then become hard gates: they feed
each recorded response through the adapter's pure parse functions and assert
the normalized §13.5 output (schema-drift tolerance included).
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

# backend -> (relative fixture file, parse callable name)
LMSTUDIO_FILES = ("api-v1-models.json", "v1-models.json")
OLLAMA_FILES = ("api-tags.json", "api-ps.json")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _recorded(backend: str) -> bool:
    base = FIXTURE_ROOT / backend
    return base.is_dir() and any(base.rglob("*.json"))


@pytest.mark.skipif(
    not _recorded("lmstudio"),
    reason=(
        "No recorded LM Studio fixtures — run docs/fixtures/CAPTURE.md on a real "
        "PC and commit under agent/tests/contract/fixtures/lmstudio/<version>/ "
        "(blocks contract coverage; §10.3 rule 1). Fakes do NOT substitute."
    ),
)
def test_lmstudio_native_models_vs_fixtures() -> None:
    from localmesh_agent.adapters.backends.lmstudio import parse_native_model_list

    for path in sorted((FIXTURE_ROOT / "lmstudio").rglob("api-v1-models.json")):
        payload = _load(path)
        data = payload.get("data")
        assert isinstance(data, list)
        models, drift = parse_native_model_list(data)
        assert models, f"{path}: no models parsed from recorded response"
        for model in models:
            assert model.backend_model_id
            assert model.display_name is None or isinstance(model.display_name, str)


@pytest.mark.skipif(
    not _recorded("ollama"),
    reason=(
        "No recorded Ollama fixtures — run docs/fixtures/CAPTURE.md on a real "
        "PC and commit under agent/tests/contract/fixtures/ollama/<version>/ "
        "(blocks contract coverage; §10.3 rule 1). Fakes do NOT substitute."
    ),
)
def test_ollama_tags_vs_fixtures() -> None:
    from localmesh_agent.adapters.backends.ollama import parse_ps_names, parse_tag_entry

    for tags_path in sorted((FIXTURE_ROOT / "ollama").rglob("api-tags.json")):
        tags = _load(tags_path)
        ps_dir = tags_path.parent
        ps = _load(ps_dir / "api-ps.json") if (ps_dir / "api-ps.json").is_file() else None
        loaded = parse_ps_names(ps)
        entries = tags.get("models")
        assert isinstance(entries, list) and entries
        for item in entries:
            model = parse_tag_entry(item, item.get("name") in loaded, None)
            assert model is not None and model.backend_model_id

"""Repo-root-level conftest for the Agent package (QA fix, CI parity).

Existence alone is the feature: pytest's `prepend` import mode inserts this
file's directory (`agent/`) into `sys.path` while collecting it, so the
cross-module test doubles imported as

    from tests.unit.fake_store import FakeClock, FakeStore   # test_pairing.py
    from tests.unit.test_pairing import FakeClock, FakeStore # test_tokens.py

resolve identically under every supported invocation style:

    bash scripts/pytest_layer.sh agent/tests/unit   # CI (repo-root cwd, §21.4)
    cd agent && python -m pytest tests/unit         # local workflow

Without this anchor the CI-style invocation fails at collection with
`ModuleNotFoundError: No module named 'tests'`, because the `pytest` console
script does not add the working directory to `sys.path` the way
`python -m pytest` does.

No fixtures live here on purpose: layer-specific fixtures stay in
`tests/unit/conftest.py` (§21.5 layer isolation).
"""

"""Gate 7 least-privilege OpenAPI contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _generator_module():
    path = Path(__file__).resolve().parents[2] / "agents" / "generate_tool_openapi.py"
    spec = importlib.util.spec_from_file_location("sentineliq_tool_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_tool_contract_contains_only_approved_gets() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")

    assert contract["servers"] == [{"url": "https://sentineliq.example.test"}]
    assert set(contract["paths"]) == set(module.APPROVED_OPERATIONS)
    assert all(set(path_item) == {"get"} for path_item in contract["paths"].values())

    operations = {
        path_item["get"]["operationId"] for path_item in contract["paths"].values()
    }
    assert operations == module.EXPECTED_OPERATION_IDS


def test_every_generated_tool_requires_authentication() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")
    for path, path_item in contract["paths"].items():
        assert path_item["get"].get("security"), f"Tool route lacks auth: {path}"


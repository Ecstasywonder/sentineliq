"""Gate 7 least-privilege OpenAPI contract tests."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import yaml


def _generator_module():
    path = Path(__file__).resolve().parents[2] / "agents" / "generate_tool_openapi.py"
    spec = importlib.util.spec_from_file_location("sentineliq_tool_generator", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_tool_contract_contains_only_approved_gets() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")

    assert contract["servers"] == [{"url": "https://sentineliq.example.test"}]
    assert set(contract["paths"]) == set(module.APPROVED_OPERATIONS)
    assert all(set(path_item) == {"get"} for path_item in contract["paths"].values())

    operations = {path_item["get"]["operationId"] for path_item in contract["paths"].values()}
    assert operations == module.EXPECTED_OPERATION_IDS


def test_every_generated_tool_has_a_non_empty_description() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")

    for path, path_item in contract["paths"].items():
        description = path_item["get"].get("description")
        assert isinstance(description, str), f"Tool route description is not text: {path}"
        assert description.strip(), f"Tool route lacks an Orchestrate description: {path}"


def test_description_fallback_is_deterministic_and_includes_operation_identity() -> None:
    module = _generator_module()
    operation = {"operationId": "get_example"}

    assert module._tool_description("/api/v1/tools/example", "get", operation) == (
        "Read-only SentinelIQ tool for GET /api/v1/tools/example (operation ID: get_example)."
    )


def test_authored_tool_description_is_preserved_and_trimmed() -> None:
    module = _generator_module()
    operation = {
        "operationId": "get_example",
        "description": "  Authored explanation for this tool.  ",
        "summary": "This summary must not replace the authored description",
    }

    assert module._tool_description("/api/v1/tools/example", "get", operation) == (
        "Authored explanation for this tool."
    )


def test_summary_description_fallback_is_deterministic() -> None:
    module = _generator_module()
    operation = {"operationId": "get_example", "summary": "  Retrieve example evidence.  "}

    assert module._tool_description("/api/v1/tools/example", "get", operation) == (
        "Read-only SentinelIQ tool: Retrieve example evidence."
    )


def test_build_tool_spec_does_not_mutate_fastapi_cached_operations() -> None:
    from app.main import app

    module = _generator_module()
    cached_operation = app.openapi()["paths"]["/api/v1/tools/access-events"]["get"]
    original_operation = deepcopy(cached_operation)

    module.build_tool_spec("https://sentineliq.example.test")

    assert cached_operation == original_operation


def test_every_generated_tool_requires_authentication() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")
    for path, path_item in contract["paths"].items():
        assert path_item["get"].get("security"), f"Tool route lacks auth: {path}"


def test_connection_contract_configures_draft_and_live_runtime_environments() -> None:
    connection_path = (
        Path(__file__).resolve().parents[2] / "agents" / "connections" / "sentineliq-api.yaml"
    )
    connection = yaml.safe_load(connection_path.read_text(encoding="utf-8"))

    assert set(connection["environments"]) == {"draft", "live"}
    for environment in connection["environments"].values():
        assert environment == {
            "security_scheme": "bearer_token",
            "type": "team",
            "server_url": "__SENTINELIQ_API_BASE_URL__",
        }

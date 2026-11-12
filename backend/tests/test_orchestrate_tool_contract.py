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
    cached_operation = app.openapi()["paths"]["/api/v1/tools/agent/access-events"]["get"]
    original_operation = deepcopy(cached_operation)

    module.build_tool_spec("https://sentineliq.example.test")

    assert cached_operation == original_operation


def test_every_generated_tool_requires_authentication() -> None:
    module = _generator_module()
    contract = module.build_tool_spec("https://sentineliq.example.test")
    for path, path_item in contract["paths"].items():
        assert path_item["get"].get("security") == [{module.OAUTH_SCHEME_NAME: ["tools:read"]}], (
            f"Tool route has the wrong auth scope: {path}"
        )

        parameters = path_item["get"].get("parameters", [])
        assert [parameter["name"] for parameter in parameters] == ["event_id"]

    assert contract["components"]["securitySchemes"] == {
        module.OAUTH_SCHEME_NAME: {
            "type": "oauth2",
            "description": (
                "OAuth2 client credentials for the purpose-bound SentinelIQ "
                "Orchestrate tool identity."
            ),
            "flows": {
                "clientCredentials": {
                    "tokenUrl": ("https://sentineliq.example.test/api/v1/auth/service-token"),
                    "scopes": {"tools:read": "Read redacted, event-bound evidence"},
                }
            },
        }
    }


def test_connection_contract_configures_draft_and_live_runtime_environments() -> None:
    connection_path = (
        Path(__file__).resolve().parents[2] / "agents" / "connections" / "sentineliq-api.yaml"
    )
    connection = yaml.safe_load(connection_path.read_text(encoding="utf-8"))

    assert set(connection["environments"]) == {"draft", "live"}
    for environment in connection["environments"].values():
        assert environment == {
            "security_scheme": "oauth2",
            "auth_type": "oauth2_client_creds",
            "type": "team",
            "server_url": "__SENTINELIQ_API_BASE_URL__",
        }


def _agent_contract(agent_directory: str) -> dict[str, object]:
    agent_path = Path(__file__).resolve().parents[2] / "agents" / agent_directory / "agent.yaml"
    contract = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
    assert isinstance(contract, dict)
    return contract


def test_context_agent_has_least_privilege_read_only_tool_contract() -> None:
    context = _agent_contract("context")

    assert context["style"] == "react_intrinsic"
    assert context["collaborators"] == []
    assert context["tools"] == [
        "get_agent_event_detail",
        "get_agent_camera_metadata",
        "get_agent_access_events",
        "get_agent_schedule",
        "get_agent_work_orders",
        "get_agent_delivery",
        "get_agent_location_policy",
        "get_agent_incident_history",
        "get_agent_integration_health",
    ]
    assert set(context["tools"]).issubset(_generator_module().EXPECTED_OPERATION_IDS)
    assert "get_agent_assessment" not in context["tools"]


def test_context_agent_structured_output_is_narrow_and_strict() -> None:
    context = _agent_contract("context")

    assert context["structured_output"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["event_id", "context_summary"],
        "properties": {
            "event_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "context_summary": {"type": "string", "maxLength": 1024},
        },
    }


def test_coordinator_agent_contract_uses_intrinsic_collaboration_and_schema() -> None:
    coordinator = _agent_contract("coordinator")

    assert coordinator["style"] == "react_intrinsic"
    assert coordinator["collaborators"] == [
        "sentinel_triage_agent",
        "sentinel_context_agent",
        "sentinel_explanation_agent",
    ]
    assert coordinator["tools"] == ["get_agent_event_detail", "get_agent_assessment"]
    assert set(coordinator["tools"]).issubset(_generator_module().EXPECTED_OPERATION_IDS)

    assert coordinator["structured_output"] == {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "event_id",
            "assessment_ready",
            "summary",
            "missing_evidence",
            "human_review_required",
        ],
        "properties": {
            "event_id": {"type": "string"},
            "assessment_ready": {"type": "boolean"},
            "summary": {"type": "string", "maxLength": 1024},
            "missing_evidence": {"type": "array", "items": {"type": "string"}},
            "human_review_required": {"type": "boolean", "const": True},
        },
    }

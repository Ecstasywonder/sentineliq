"""Generate the least-privilege Orchestrate OpenAPI tool bundle.

The checked-in FastAPI application is the API contract source of truth. This
script selects only approved GET operations, so stale handwritten schemas
cannot drift and write endpoints can never be imported as agent tools.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

APPROVED_OPERATIONS = {
    "/api/v1/events/{event_id}": "get",
    "/api/v1/tools/access-events": "get",
    "/api/v1/tools/schedule": "get",
    "/api/v1/tools/work-orders": "get",
    "/api/v1/tools/delivery": "get",
    "/api/v1/tools/location-policy": "get",
    "/api/v1/tools/incident-history": "get",
    "/api/v1/tools/knowledge-search": "get",
    "/api/v1/tools/integration-health": "get",
    "/api/v1/tools/assessment-bundle": "get",
}

EXPECTED_OPERATION_IDS = {
    "get_event_detail",
    "get_access_events",
    "get_schedule",
    "get_work_orders",
    "get_delivery",
    "get_location_policy",
    "get_incident_history",
    "search_knowledge",
    "get_integration_health",
    "get_assessment_bundle",
}


def _tool_description(path: str, method: str, operation: dict[str, Any]) -> str:
    """Return an Orchestrate-compatible description for an approved operation.

    FastAPI only emits an OpenAPI ``description`` when the route author supplies
    one.  Orchestrate rejects operations without it, so derive a stable,
    human-readable description from the route summary when necessary.  The
    route and operation ID remain in the final fallback so a future route that
    loses both its prose fields is still importable and diagnosable.
    """

    description = operation.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()

    summary = operation.get("summary")
    if isinstance(summary, str) and summary.strip():
        summary_text = summary.strip().rstrip(".")
        return f"Read-only SentinelIQ tool: {summary_text}."

    operation_id = operation["operationId"]
    return (
        "Read-only SentinelIQ tool for "
        f"{method.upper()} {path} (operation ID: {operation_id})."
    )


def build_tool_spec(api_base_url: str) -> dict[str, Any]:
    from app.main import app

    full = app.openapi()
    selected_paths: dict[str, Any] = {}
    operation_ids: set[str] = set()

    for path, method in APPROVED_OPERATIONS.items():
        operation = (full.get("paths", {}).get(path) or {}).get(method)
        if operation is None:
            raise RuntimeError(f"Required read-only tool route is missing: {method.upper()} {path}")
        if method != "get":
            raise RuntimeError(f"Refusing to expose a non-GET agent operation: {path}")
        operation_id = operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError(f"Tool route has no stable operationId: {path}")
        operation_ids.add(operation_id)
        # Do not mutate FastAPI's cached OpenAPI schema.  It is reused by the
        # application and may be generated more than once in tests/processes.
        selected_operation = dict(operation)
        selected_operation["description"] = _tool_description(path, method, selected_operation)
        selected_paths[path] = {method: selected_operation}

    if operation_ids != EXPECTED_OPERATION_IDS:
        raise RuntimeError(
            "Tool operation IDs drifted: "
            f"expected={sorted(EXPECTED_OPERATION_IDS)} actual={sorted(operation_ids)}"
        )

    return {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "SentinelIQ approved read-only agent tools",
            "version": full.get("info", {}).get("version", "0.1.0"),
            "description": (
                "Generated from the FastAPI source of truth. Contains only approved, "
                "authenticated GET operations; no agent write capability is exposed."
            ),
        },
        "servers": [{"url": api_base_url.rstrip("/")}],
        "paths": selected_paths,
        "components": full.get("components", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("SENTINELIQ_API_BASE_URL", "http://localhost:8000"),
    )
    args = parser.parse_args()
    spec = build_tool_spec(args.api_base_url)
    args.output.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Generated {len(spec['paths'])} approved GET tools at {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


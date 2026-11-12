"""Quick test: verify Orchestrate Path B triage works end-to-end."""
import asyncio
import json
import logging

logging.basicConfig(level=logging.WARNING)

TEST_PAYLOAD = {
    "event_id": "test-gate14-verify-3",
    "event_type": "person_detected",
    "event_timestamp": "2026-11-09T22:30:00Z",
    "location_id": "loc-003",
    "zone": "LOADING_DOCK_3",
    "detector_confidence": 0.85,
    "camera_id": "cam-003",
    "facility_id": "fac-001",
}


async def test():
    from app.services.orchestrate_client import OrchestrateClient
    from app.services.triage_service import _TRIAGE_SYSTEM_PROMPT
    from app.config import get_settings

    s = get_settings()
    print("orchestrate_active:", s.orchestrate_active)
    print("URL:", s.orchestrate_url)
    print("Agent ID:", s.orchestrate_triage_agent_id)

    client = OrchestrateClient(
        base_url=s.orchestrate_url,
        api_key=s.effective_orchestrate_api_key,
        timeout=45.0,
        api_version=s.orchestrate_api_version,
    )
    print("\nCalling Orchestrate triage agent (no structured_output)...")
    content, _ = await client.chat(
        agent_id=s.orchestrate_triage_agent_id,
        system_prompt=_TRIAGE_SYSTEM_PROMPT,
        input_payload=TEST_PAYLOAD,
    )
    print("RAW:", repr(content[:800]))
    text = content.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        print("\nPARSED OK:")
        print("  category:        ", parsed.get("category"))
        print("  urgency_signals: ", parsed.get("urgency_signals"))
        print("  required_context:", parsed.get("required_context"))
        print("\n  source = orchestrate (PATH B working!)")
    except Exception as e:
        print("PARSE FAIL:", e)


asyncio.run(test())

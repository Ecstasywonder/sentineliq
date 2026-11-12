#!/usr/bin/env bash
# SentinelIQ — Gate 23 demo scenario runner.
#
# Seeds the five canonical MVP usability scenarios (A–E) via the API and
# verifies each produces the expected outcome documented in §51 of the Master
# Build Prompt. Designed to run on the provisioned EC2 server against a seeded
# database.
#
# Usage:
#   E2E_ALLOW_PERSISTENT_WRITES=yes \
#   E2E_EMAIL=admin@example.com \
#   E2E_PASSWORD=yourpassword \
#   bash scripts/run_demo_scenarios.sh
#
# Optional overrides (same contract as e2e_smoke.sh):
#   E2E_BASE_URL              default: http://localhost:8000
#   E2E_ACCESS_TOKEN          skip login; use this bearer token directly
#   E2E_CONNECT_TIMEOUT_SECONDS  default: 5
#   E2E_MAX_TIME_SECONDS         default: 120
#   E2E_PYTHON                   default: backend/.venv/bin/python

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
BASE_URL="${E2E_BASE_URL:-http://localhost:8000}"
CONNECT_TIMEOUT="${E2E_CONNECT_TIMEOUT_SECONDS:-5}"
MAX_TIME="${E2E_MAX_TIME_SECONDS:-120}"
PYTHON="${E2E_PYTHON:-$REPO_ROOT/backend/.venv/bin/python}"
PASS=0
FAIL=0
BODY=""
HTTP_STATUS="000"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

pass() { printf '  ✅ %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  ❌ %s\n' "$1"; FAIL=$((FAIL + 1)); }
info() { printf '  ℹ  %s\n' "$1"; }
die()  { printf 'ERROR: %s\n' "$1" >&2; exit 2; }

[[ "${E2E_ALLOW_PERSISTENT_WRITES:-}" == "yes" ]] || die \
  "this script seeds demo events that create immutable audit records; set E2E_ALLOW_PERSISTENT_WRITES=yes"
[[ -x "$PYTHON" ]] || die \
  "set E2E_PYTHON to the EC2 backend virtualenv Python (default: backend/.venv/bin/python)"

# ---------------------------------------------------------------------------
# Shared HTTP helpers (copied from e2e_smoke.sh for standalone execution)
# ---------------------------------------------------------------------------

api_request() {
  local method="$1" url="$2" payload="${3:-}" authenticated="${4:-yes}"
  local response_file="$TMP_DIR/response.json" error_file="$TMP_DIR/curl-error.txt"
  local -a args=(--silent --show-error --connect-timeout "$CONNECT_TIMEOUT"
    --max-time "$MAX_TIME" --request "$method" --output "$response_file"
    --write-out '%{http_code}')
  [[ "$authenticated" == yes ]] && args+=(--header "Authorization: Bearer $TOKEN")
  [[ -n "$payload" ]] && args+=(--header 'Content-Type: application/json' --data "$payload")
  if HTTP_STATUS="$(curl "${args[@]}" "$url" 2>"$error_file")"; then
    BODY="$(<"$response_file")"
  else
    HTTP_STATUS=000
    BODY=""
    fail "$method $url failed: $(<"$error_file")"
  fi
}

check_status() {
  local label="$1" codes="$2" code
  for code in $codes; do
    if [[ "$HTTP_STATUS" == "$code" ]]; then pass "$label (HTTP $code)"; return; fi
  done
  fail "$label (expected HTTP $codes, got $HTTP_STATUS)"
}

json_assert() {
  local label="$1" operation="$2" path="$3" expected="${4:-}"
  local json_file="$TMP_DIR/assert.json"
  printf '%s' "$BODY" >"$json_file"
  if "$PYTHON" - "$json_file" "$operation" "$path" "$expected" <<'PY'
import json, sys
filename, operation, path, expected = sys.argv[1:5]
try:
    with open(filename, encoding="utf-8") as stream:
        value = json.load(stream)
    for part in filter(None, path.split(".")):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    checks = {
        "has": lambda: value is not None,
        "nonempty": lambda: isinstance(value, (str, list, dict)) and len(value) > 0,
        "list": lambda: isinstance(value, list),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "true": lambda: value is True,
        "false": lambda: value is False,
        "eq": lambda: str(value).lower() == expected.lower(),
        "in": lambda: str(value).lower() in expected.lower().split(","),
        "not_eq": lambda: str(value).lower() != expected.lower(),
        "len_ge": lambda: isinstance(value, (list, dict, str)) and len(value) >= int(expected),
        "lte": lambda: isinstance(value, (int, float)) and value <= float(expected),
        "gte": lambda: isinstance(value, (int, float)) and value >= float(expected),
        "keys_include": lambda: isinstance(value, dict) and set(filter(None, expected.split(","))) <= set(value),
        "list_contains_text": lambda: isinstance(value, list) and any(
            expected.lower() in str(item).lower() for item in value
        ),
        "list_lacks_text": lambda: isinstance(value, list) and all(
            expected.lower() not in str(item).lower() for item in value
        ),
        "list_has_reason": lambda: isinstance(value, list) and any(
            isinstance(item, dict) and str(item.get("reason", "")).lower() == expected.lower()
            for item in value
        ),
    }
    ok = checks[operation]()
except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
    ok = False
raise SystemExit(0 if ok else 1)
PY
  then pass "$label"; else fail "$label (JSON contract mismatch)"; fi
}

json_value() {
  local path="$1" json_file="$TMP_DIR/value.json"
  printf '%s' "$BODY" >"$json_file"
  "$PYTHON" - "$json_file" "$path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
for part in filter(None, sys.argv[2].split(".")):
    value = value[part]
if not isinstance(value, (str, int, float)) or isinstance(value, bool):
    raise SystemExit(1)
print(value)
PY
}

make_json() {
  "$PYTHON" - "$@" <<'PY'
import json, sys
if len(sys.argv[1:]) % 2:
    raise SystemExit("make_json requires key/value pairs")
print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2])), separators=(",", ":")))
PY
}

simulator_payload() {
  local scenario_id="$1" persist="${2:-true}"
  "$PYTHON" - "$scenario_id" "$persist" "$RUN_INSTANCE" <<'PY'
import json, sys
scenario_id, persist, instance_id = sys.argv[1:]
print(json.dumps({
    "scenario_ids": [scenario_id],
    "persist": persist.lower() == "true",
    "instance_id": instance_id,
}, separators=(",", ":")))
PY
}

persisted_event_id() {
  "$PYTHON" - "$TMP_DIR/response.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)
events = data.get("events", []) if isinstance(data, dict) else []
if not events or not events[0].get("persisted_event_id"):
    raise SystemExit(1)
print(events[0]["persisted_event_id"])
PY
}

# ---------------------------------------------------------------------------
# Authenticate
# ---------------------------------------------------------------------------

if [[ -n "${E2E_ACCESS_TOKEN:-}" ]]; then
  TOKEN="$E2E_ACCESS_TOKEN"
elif [[ -n "${E2E_EMAIL:-}" && -n "${E2E_PASSWORD:-}" ]]; then
  LOGIN_JSON="$(make_json email "$E2E_EMAIL" password "$E2E_PASSWORD")"
  api_request POST "$BASE_URL/api/v1/auth/token" "$LOGIN_JSON" no
  check_status "Authenticate" 200
  TOKEN="$(json_value access_token 2>/dev/null || true)"
  [[ -n "$TOKEN" ]] || die "authentication response has no access_token"
else
  die "set E2E_ACCESS_TOKEN, or both E2E_EMAIL and E2E_PASSWORD"
fi

RUN_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
RUN_INSTANCE="gate23-$(date -u +'%Y%m%dT%H%M%SZ')-$$"

printf '\n============================================================\n'
printf ' SentinelIQ — Gate 23 Demo Scenario Validation\n'
printf ' %s\n' "$RUN_TIMESTAMP"
printf ' Five canonical scenarios from Master Build Prompt §51\n'
printf '============================================================\n'

# ---------------------------------------------------------------------------
# Helper: seed a demo scenario via the simulator, assess it, return event ID
# ---------------------------------------------------------------------------

seed_and_assess() {
  local scenario_id="$1"
  local PAYLOAD
  PAYLOAD="$(simulator_payload "$scenario_id")"
  # Simulator persist endpoint
  api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD"
  check_status "Seed $scenario_id via simulator" 200
  # The simulator returns events with persisted_event_id.
  local EVENT_ID
  EVENT_ID="$(persisted_event_id)"
  [[ -n "$EVENT_ID" ]] || die "simulator did not return event_id for $scenario_id"
  # Trigger deterministic assessment (AI fallback always available)
  api_request POST "$BASE_URL/api/v1/events/$EVENT_ID/assess" '{}'
  check_status "Assess $scenario_id" 200
  printf '%s' "$EVENT_ID"
}

# ---------------------------------------------------------------------------
# Scenario A — Authorized activity (low risk)
# §51 expected: low risk, high confidence, operator can dismiss/confirm
# ---------------------------------------------------------------------------

printf '\n--- Scenario A: Authorized activity (low risk) ---\n'
info "Valid badge, scheduled activity, permitted policy — expect low risk + high confidence"

PAYLOAD_A="$(simulator_payload demo-scenario-a)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD_A"
check_status "Seed Scenario A" 200
EVENT_A="$(persisted_event_id)"
[[ -n "$EVENT_A" ]] || die "Scenario A: no event_id returned"

api_request POST "$BASE_URL/api/v1/events/$EVENT_A/assess" '{}'
check_status "Assess Scenario A" 200
json_assert "Scenario A: risk level is low" eq risk_level low
json_assert "Scenario A: human review required in recommendation" true recommendation.requires_human_review
json_assert "Scenario A: confidence level is high" eq confidence_level high

# Operator journey: verify event is in awaiting_review state
api_request GET "$BASE_URL/api/v1/events/$EVENT_A"
check_status "Scenario A: event accessible in queue" 200
json_assert "Scenario A: event awaits review" eq status awaiting_review

# Simulate operator confirm/dismiss
DECISION_A="$(make_json decision dismiss rationale "Demo Scenario A: authorized activity, dismissed after review")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_A/decision" "$DECISION_A"
check_status "Scenario A: operator can dismiss" 201
json_assert "Scenario A: dismiss closes event" eq event_status dismissed

# ---------------------------------------------------------------------------
# Scenario B — Unverified after-hours event (high risk)
# §51 expected: high/critical risk, high confidence, human review required
# ---------------------------------------------------------------------------

printf '\n--- Scenario B: Unverified after-hours event (high risk) ---\n'
info "No badge, no schedule, restricted area, prior incidents — expect high/critical risk"

PAYLOAD_B="$(simulator_payload demo-scenario-b)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD_B"
check_status "Seed Scenario B" 200
EVENT_B="$(persisted_event_id)"
[[ -n "$EVENT_B" ]] || die "Scenario B: no event_id returned"

api_request POST "$BASE_URL/api/v1/events/$EVENT_B/assess" '{}'
check_status "Assess Scenario B" 200
json_assert "Scenario B: risk level is high or critical" in risk_level "high,critical"
json_assert "Scenario B: human review required" true recommendation.requires_human_review
json_assert "Scenario B: risk score elevated" gte risk_score 50
json_assert "Scenario B: confidence level is high" eq confidence_level high

api_request GET "$BASE_URL/api/v1/events/$EVENT_B"
check_status "Scenario B: event accessible in queue" 200
json_assert "Scenario B: event awaits review" eq status awaiting_review

# Operator escalates
DECISION_B="$(make_json decision escalate rationale "Demo Scenario B: high-risk unverified access, escalating to supervisor")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_B/decision" "$DECISION_B"
check_status "Scenario B: operator can escalate" 201
json_assert "Scenario B: escalate changes event status" eq event_status escalated

api_request GET "$BASE_URL/api/v1/events/$EVENT_B/escalation"
check_status "Scenario B: escalation record created" 200
json_assert "Scenario B: escalation is event-bound" eq event_id "$EVENT_B"

# ---------------------------------------------------------------------------
# Scenario C — Missing evidence (degraded confidence)
# §51 expected: sources marked unavailable, confidence reduced, no assertion
#               that "no badge exists", human review requested
# ---------------------------------------------------------------------------

printf '\n--- Scenario C: Missing evidence (degraded confidence) ---\n'
info "Badge and schedule services unavailable — expect reduced confidence, no false assertions"

PAYLOAD_C="$(simulator_payload demo-scenario-c)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD_C"
check_status "Seed Scenario C" 200
EVENT_C="$(persisted_event_id)"
[[ -n "$EVENT_C" ]] || die "Scenario C: no event_id returned"

api_request POST "$BASE_URL/api/v1/events/$EVENT_C/assess" \
  '{"unavailable_source_ids":["mock_access_control","mock_schedule"]}'
check_status "Assess Scenario C" 200
json_assert "Scenario C: risk level is medium" eq risk_level medium
json_assert "Scenario C: human review required" true recommendation.requires_human_review
json_assert "Scenario C: confidence score present" number confidence_score
json_assert "Scenario C: confidence reductions present" list confidence_reductions

api_request GET "$BASE_URL/api/v1/events/$EVENT_C/assessment"
check_status "Scenario C: assessment retrievable" 200
json_assert "Scenario C: both unavailable sources recorded" keys_include evidence_errors \
  "mock_access_control,mock_schedule"
json_assert "Scenario C: badge source is marked unavailable" list_contains_text \
  explanation.missing_evidence "mock_access_control status unavailable"
json_assert "Scenario C: schedule source is marked unavailable" list_contains_text \
  explanation.missing_evidence "mock_schedule status unavailable"

# Verify the explanation does not falsely claim "no badge exists"
# (It must say evidence unavailable, not that badge was absent)
json_assert "Scenario C: explanation does not claim badge absence" list_lacks_text \
  explanation.why "no verified badge"

# Operator requests more context before deciding
DECISION_C="$(make_json decision request_context rationale "Demo Scenario C: evidence unavailable, requesting additional context")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_C/decision" "$DECISION_C"
check_status "Scenario C: operator can request context" 201

# ---------------------------------------------------------------------------
# Scenario D — Conflicting evidence
# §51 expected: conflict explicitly shown, confidence reflects uncertainty,
#               human review required
# ---------------------------------------------------------------------------

printf '\n--- Scenario D: Conflicting evidence ---\n'
info "Valid badge but not scheduled, restricted area — expect conflict shown, uncertain confidence"

PAYLOAD_D="$(simulator_payload demo-scenario-d)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD_D"
check_status "Seed Scenario D" 200
EVENT_D="$(persisted_event_id)"
[[ -n "$EVENT_D" ]] || die "Scenario D: no event_id returned"

api_request POST "$BASE_URL/api/v1/events/$EVENT_D/assess" '{}'
check_status "Assess Scenario D" 200
json_assert "Scenario D: risk level is high" in risk_level "high,critical"
json_assert "Scenario D: human review required" true recommendation.requires_human_review
json_assert "Scenario D: risk factors present" list risk_factors

api_request GET "$BASE_URL/api/v1/events/$EVENT_D/assessment"
check_status "Scenario D: assessment retrievable" 200
# Context summary should reflect conflict — check it has conflicts or missing sources
json_assert "Scenario D: confidence reductions present" list confidence_reductions
json_assert "Scenario D: evidence conflict is explicit" true context.has_conflicts
json_assert "Scenario D: conflict details are present" len_ge context.conflicts 1
json_assert "Scenario D: confidence records the conflict" list_has_reason \
  confidence_reductions contradictory_evidence
json_assert "Scenario D: confidence is reduced" lte confidence_score 0.85

DECISION_D="$(make_json decision accept rationale "Demo Scenario D: conflict reviewed, access verified by operator on-site")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_D/decision" "$DECISION_D"
check_status "Scenario D: operator can record decision after reviewing conflict" 201

# ---------------------------------------------------------------------------
# Scenario E — AI unavailable (deterministic fallback)
# §51 expected: event remains accessible, deterministic risk available,
#               AI explanation marked unavailable, operator can manually review
# ---------------------------------------------------------------------------

printf '\n--- Scenario E: AI unavailable (deterministic fallback) ---\n'
info "AI pipeline simulated as unavailable — deterministic risk/evidence must remain accessible"

PAYLOAD_E="$(simulator_payload demo-scenario-e)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PAYLOAD_E"
check_status "Seed Scenario E" 200
EVENT_E="$(persisted_event_id)"
[[ -n "$EVENT_E" ]] || die "Scenario E: no event_id returned"

# Assessment always completes deterministically (AI is fallback by design)
api_request POST "$BASE_URL/api/v1/events/$EVENT_E/assess" '{}'
check_status "Scenario E: deterministic assessment succeeds even without AI" 200
json_assert "Scenario E: risk score is numeric" number risk_score
json_assert "Scenario E: risk level is medium" eq risk_level medium
json_assert "Scenario E: human review required" true recommendation.requires_human_review
json_assert "Scenario E: explanation uses deterministic fallback" eq explanation.source deterministic_fallback
json_assert "Scenario E: AI unavailability reduces confidence" list_has_reason \
  confidence_reductions llm_unavailable

# Event must remain accessible in queue
api_request GET "$BASE_URL/api/v1/events/$EVENT_E"
check_status "Scenario E: event accessible in queue without AI" 200
json_assert "Scenario E: event has risk data" nonempty risk.level

# Coordinator review uses deterministic fallback when AI unavailable
api_request GET "$BASE_URL/api/v1/events/$EVENT_E/review"
check_status "Scenario E: coordinator review available via fallback" 200
json_assert "Scenario E: fallback review is event-bound" eq event_id "$EVENT_E"
json_assert "Scenario E: human review remains required" true human_review_required
json_assert "Scenario E: source declares deterministic fallback" eq source deterministic_fallback

# Operator can still manually record a decision
DECISION_E="$(make_json decision reject rationale "Demo Scenario E: reviewed manually without AI; activity unauthorized")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_E/decision" "$DECISION_E"
check_status "Scenario E: operator can decide manually without AI" 201

# ---------------------------------------------------------------------------
# Verify all five events appear in audit trail
# ---------------------------------------------------------------------------

printf '\n--- Audit trail integrity across all five scenarios ---\n'

for EVENT_ID in "$EVENT_A" "$EVENT_B" "$EVENT_C" "$EVENT_D" "$EVENT_E"; do
  api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/audit"
  check_status "Audit trail exists for event $EVENT_ID" 200
  json_assert "Audit trail has entries for $EVENT_ID" len_ge items 1
done

# ---------------------------------------------------------------------------
# Dashboard usability: simulator preview endpoint (no persistent writes)
# ---------------------------------------------------------------------------

printf '\n--- Simulator preview (usability check) ---\n'

PREVIEW_PAYLOAD="$($PYTHON - "$RUN_INSTANCE" <<'PY'
import json, sys
print(json.dumps({
    "scenario_ids": [
        "demo-scenario-a", "demo-scenario-b", "demo-scenario-c",
        "demo-scenario-d", "demo-scenario-e",
    ],
    "persist": False,
    "instance_id": sys.argv[1],
}, separators=(",", ":")))
PY
)"
api_request POST "$BASE_URL/api/v1/simulator/generate" "$PREVIEW_PAYLOAD"
check_status "POST /simulator/generate previews scenario catalogue" 200
json_assert "Scenario catalogue is a non-empty list" nonempty events

# Confirm the five Gate 23 scenarios appear in the catalogue
"$PYTHON" - "$TMP_DIR/response.json" <<'PY' && pass "All 5 Gate 23 scenarios present in catalogue" || fail "Not all Gate 23 scenarios in catalogue"
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
scenarios = data.get("events", []) if isinstance(data, dict) else []
ids = {s.get("scenario_id") for s in scenarios}
required = {"demo-scenario-a", "demo-scenario-b", "demo-scenario-c", "demo-scenario-d", "demo-scenario-e"}
raise SystemExit(0 if required <= ids else 1)
PY

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

printf '\n============================================================\n'
printf ' Gate 23 Demo Scenario Results\n'
printf '  Passed: %d\n  Failed: %d\n  Total:  %d\n' "$PASS" "$FAIL" "$((PASS + FAIL))"
printf '  Scenarios validated: A (authorized), B (high-risk),\n'
printf '                       C (missing evidence), D (conflicting),\n'
printf '                       E (AI unavailable)\n'
printf '============================================================\n'
(( FAIL == 0 )) || exit 1

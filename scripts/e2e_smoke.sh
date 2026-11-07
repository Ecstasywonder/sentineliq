#!/usr/bin/env bash
# Destructive SentinelIQ API smoke test. This creates immutable audit records.

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
die() { printf 'ERROR: %s\n' "$1" >&2; exit 2; }

[[ "${E2E_ALLOW_PERSISTENT_WRITES:-}" == "yes" ]] || die \
  "this test writes immutable audit data; set E2E_ALLOW_PERSISTENT_WRITES=yes"
[[ -x "$PYTHON" ]] || die \
  "set E2E_PYTHON to the EC2 backend virtualenv Python (default: backend/.venv/bin/python)"
[[ "$CONNECT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "connect timeout must be a positive integer"
[[ "$MAX_TIME" =~ ^[1-9][0-9]*$ ]] || die "max time must be a positive integer"

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
        "eq": lambda: str(value).lower() == expected.lower(),
        "len_ge": lambda: isinstance(value, (list, dict, str)) and len(value) >= int(expected),
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

require_file() {
  if [[ -s "$2" ]]; then pass "$1"; else fail "$1 (missing or empty: $2)"; fi
}

RUN_ID="$("$PYTHON" -c 'import uuid; print(uuid.uuid4().hex)')"
RUN_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

if [[ -n "${E2E_ACCESS_TOKEN:-}" ]]; then
  TOKEN="$E2E_ACCESS_TOKEN"
elif [[ -n "${E2E_EMAIL:-}" && -n "${E2E_PASSWORD:-}" ]]; then
  LOGIN_JSON="$(make_json email "$E2E_EMAIL" password "$E2E_PASSWORD")"
  api_request POST "$BASE_URL/api/v1/auth/token" "$LOGIN_JSON" no
  check_status "Authenticate with JSON email/password" 200
  TOKEN="$(json_value access_token 2>/dev/null || true)"
  [[ -n "$TOKEN" ]] || die "authentication response has no access_token"
else
  die "set E2E_ACCESS_TOKEN, or both E2E_EMAIL and E2E_PASSWORD; no credentials are built in"
fi

printf '\n========================================\n'
printf ' SentinelIQ API Smoke Test\n Run ID: %s\n' "$RUN_ID"
printf ' Coverage: API contracts and deterministic safety invariants\n'
printf ' Excluded: proof of live watsonx Orchestrate execution\n'
printf '========================================\n'

printf '\n--- Health and authentication ---\n'
api_request GET "$BASE_URL/health" "" no
check_status "GET /health" 200
json_assert "Health status is ok" eq status ok
json_assert "Health identifies SentinelIQ" eq service SentinelIQ
api_request GET "$BASE_URL/api/v1/auth/me"
check_status "GET /auth/me" 200
json_assert "Identity has an email" nonempty email
json_assert "Identity has roles" list roles
api_request GET "$BASE_URL/api/v1/events" "" no
check_status "Unauthenticated event access is rejected" "401 403"

printf '\n--- Event ingestion and deduplication ---\n'
EVENT_PROVIDER_ID="e2e-event-$RUN_ID"
EVENT_JSON="$(make_json provider_event_id "$EVENT_PROVIDER_ID" source_adapter e2e_smoke \
  event_type person_detected event_timestamp "$RUN_TIMESTAMP" location_id "e2e-location-$RUN_ID")"
api_request POST "$BASE_URL/api/v1/events" "$EVENT_JSON"
check_status "Create primary event" 201
json_assert "Created event has an ID" nonempty id
json_assert "Provider event ID is preserved" eq provider_event_id "$EVENT_PROVIDER_ID"
EVENT_ID="$(json_value id 2>/dev/null || true)"
[[ -n "$EVENT_ID" ]] || die "event creation response has no id"
api_request POST "$BASE_URL/api/v1/events" "$EVENT_JSON"
check_status "Duplicate event does not create another row" 200
json_assert "Duplicate resolves to original event" eq id "$EVENT_ID"
api_request GET "$BASE_URL/api/v1/events?page=1&page_size=5"
check_status "List event queue" 200
json_assert "Event queue returns items" list items
json_assert "Event queue returns a numeric total" number total
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID"
check_status "Retrieve event detail tool contract" 200
json_assert "Event detail is event-bound" eq id "$EVENT_ID"

printf '\n--- Read-only evidence tools ---\n'
for tool in access-events schedule work-orders delivery location-policy incident-history; do
  api_request GET "$BASE_URL/api/v1/tools/$tool?location_id=e2e-location-$RUN_ID"
  check_status "GET /tools/$tool" 200
  json_assert "$tool reports its source" nonempty meta.source
  json_assert "$tool returns records" list records
done
api_request GET "$BASE_URL/api/v1/tools/integration-health"
check_status "GET /tools/integration-health" 200
json_assert "integration-health reports its source" nonempty meta.source
json_assert "integration-health returns records" list records

printf '\n--- Assessment and provider-neutral coordinator review ---\n'
api_request POST "$BASE_URL/api/v1/events/$EVENT_ID/assess" '{}'
check_status "Assess event through configured pipeline" 200
json_assert "Assessment is event-bound" eq event_id "$EVENT_ID"
json_assert "Assessment reaches human review" eq event_status awaiting_review
json_assert "Risk score is numeric" number risk_score
json_assert "Risk level is present" nonempty risk_level
json_assert "Confidence score is numeric" number confidence_score
json_assert "Confidence level is present" nonempty confidence_level
json_assert "Recommendation requires human review" true recommendation.requires_human_review
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/assessment"
check_status "Retrieve persisted assessment" 200
json_assert "Assessment returns risk factors" list risk_factors
json_assert "Assessment returns confidence reductions" list confidence_reductions
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/assessment/factors"
check_status "Retrieve factor breakdown" 200
json_assert "Factor breakdown returns factors" list factors
api_request GET "$BASE_URL/api/v1/tools/assessment-bundle?event_id=$EVENT_ID"
check_status "Retrieve assessment-bundle tool contract" 200
json_assert "Assessment bundle is event-bound" eq event_id "$EVENT_ID"
json_assert "Assessment bundle returns workflow state" has workflow_state
api_request GET "$BASE_URL/api/v1/tools/knowledge-search?q=security&location_id=e2e-location-$RUN_ID"
check_status "Search knowledge tool contract" 200
json_assert "Knowledge search reports its query" eq meta.query security
json_assert "Knowledge search returns results" list results
api_request GET "$BASE_URL/api/v1/risk-policies"
check_status "List risk policies" 200
json_assert "Risk policies return items" list items
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/review"
check_status "Request read-only coordinator review" 200
json_assert "Coordinator review is event-bound" eq event_id "$EVENT_ID"
json_assert "Coordinator preserves human review" true human_review_required
json_assert "Coordinator declares runtime source" nonempty source

printf '\n--- Decision, feedback, escalation, and audit ---\n'
DECISION_JSON="$(make_json decision accept rationale "E2E smoke $RUN_ID: accept")"
api_request POST "$BASE_URL/api/v1/events/$EVENT_ID/decision" "$DECISION_JSON"
check_status "Record accept decision" 201
json_assert "Decision returns decision_id" nonempty decision_id
json_assert "Decision contract uses decision" eq decision accept
json_assert "Accept decision closes event" eq event_status closed
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/decisions"
check_status "Retrieve decision history" 200
json_assert "Decision history has an item" len_ge items 1
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/decision"
check_status "Retrieve latest decision" 200
json_assert "Latest decision is accept" eq decision accept

FEEDBACK_JSON="$("$PYTHON" - "$RUN_ID" <<'PY'
import json, sys
print(json.dumps({"recommendation_useful": True, "recommendation_accurate": True,
                  "outcome": "confirmed_incident", "notes": f"E2E smoke {sys.argv[1]}"},
                 separators=(",", ":")))
PY
)"
api_request POST "$BASE_URL/api/v1/events/$EVENT_ID/feedback" "$FEEDBACK_JSON"
check_status "Submit operator feedback" 201
json_assert "Feedback returns feedback_id" nonempty feedback_id
json_assert "Feedback uses supported outcome" eq outcome confirmed_incident
api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/feedback"
check_status "Retrieve operator feedback" 200
json_assert "Feedback history has an item" len_ge items 1

ESC_EVENT_JSON="$(make_json provider_event_id "e2e-escalation-$RUN_ID" source_adapter e2e_smoke \
  event_type alarm_triggered event_timestamp "$RUN_TIMESTAMP" location_id "e2e-escalation-$RUN_ID")"
api_request POST "$BASE_URL/api/v1/events" "$ESC_EVENT_JSON"
check_status "Create escalation-path event" 201
ESC_EVENT_ID="$(json_value id 2>/dev/null || true)"
[[ -n "$ESC_EVENT_ID" ]] || die "escalation event response has no id"
api_request POST "$BASE_URL/api/v1/events/$ESC_EVENT_ID/assess" '{}'
check_status "Assess escalation-path event" 200
ESC_DECISION_JSON="$(make_json decision escalate rationale "E2E smoke $RUN_ID: escalate")"
api_request POST "$BASE_URL/api/v1/events/$ESC_EVENT_ID/decision" "$ESC_DECISION_JSON"
check_status "Escalate through operator decision contract" 201
json_assert "Escalate decision changes event status" eq event_status escalated
api_request GET "$BASE_URL/api/v1/events/$ESC_EVENT_ID/escalation"
check_status "Retrieve auto-created escalation" 200
json_assert "Escalation returns escalation_id" nonempty escalation_id
json_assert "Escalation is pending acknowledgement" eq status pending_acknowledgement
json_assert "Escalation is event-bound" eq event_id "$ESC_EVENT_ID"

api_request GET "$BASE_URL/api/v1/events/$EVENT_ID/audit"
check_status "Retrieve event audit trail" 200
json_assert "Event audit has immutable entries" len_ge items 1
api_request GET "$BASE_URL/api/v1/audit?page=1&page_size=5"
check_status "Retrieve global audit trail" 200
json_assert "Global audit returns items" list items
json_assert "Global audit returns numeric total" number total

printf '\n--- Admin API and RBAC ---\n'
api_request GET "$BASE_URL/api/v1/admin/users"
check_status "List users (token needs admin:users)" 200
json_assert "Admin users return items" list items
api_request GET "$BASE_URL/api/v1/admin/roles"
check_status "List roles with embedded permissions" 200
json_assert "Admin roles return roles" list roles

printf '\n--- Safe degradation ---\n'
MISSING_JSON="$(make_json provider_event_id "e2e-missing-$RUN_ID" source_adapter e2e_smoke \
  event_type person_detected event_timestamp "$RUN_TIMESTAMP" location_id "nonexistent-$RUN_ID")"
api_request POST "$BASE_URL/api/v1/events" "$MISSING_JSON"
check_status "Create unknown-location event" 201
MISSING_ID="$(json_value id 2>/dev/null || true)"
[[ -n "$MISSING_ID" ]] || die "unknown-location event response has no id"
api_request POST "$BASE_URL/api/v1/events/$MISSING_ID/assess" '{}'
check_status "Unknown-location assessment degrades safely" 200
json_assert "Degraded assessment returns risk level" nonempty risk_level
json_assert "Degraded assessment requires human review" true recommendation.requires_human_review

printf '\n--- Evaluation artifacts and safe scorer tests ---\n'
DATASET="$REPO_ROOT/evaluations/datasets/eval-dataset.json"
SCHEMA="$REPO_ROOT/evaluations/expected/output-schema.json"
SCORER="$REPO_ROOT/evaluations/scoring/scorer.py"
SCORER_TEST="$REPO_ROOT/evaluations/scoring/test_eval_dataset.py"
BASELINE="$REPO_ROOT/evaluations/reports/eval-baseline-gate-21.md"
require_file "Evaluation dataset exists" "$DATASET"
require_file "Evaluation schema exists" "$SCHEMA"
require_file "Evaluation scorer exists" "$SCORER"
require_file "Evaluation scorer test exists" "$SCORER_TEST"
require_file "Baseline report exists" "$BASELINE"
BODY="$(<"$DATASET")"
json_assert "Evaluation dataset has at least 30 cases" len_ge cases 30
# This suite has no API, database, or cloud calls. Cache and bytecode writes are disabled.
if (cd "$REPO_ROOT/backend" && PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m pytest \
  "$SCORER_TEST" -q -p no:cacheprovider); then
  pass "Pure evaluation scorer tests pass"
else
  fail "Pure evaluation scorer tests failed"
fi

printf '\n--- Architecture invariants ---\n'
if PYTHONPATH="$REPO_ROOT/backend" "$PYTHON" - <<'PY'
from app.schemas.triage import TriageResult
raise SystemExit(1 if {"risk_score", "risk_level"} & set(TriageResult.model_fields) else 0)
PY
then pass "ADR-003: triage schema cannot produce risk fields"; else fail "ADR-003 invariant"; fi
if PYTHONPATH="$REPO_ROOT/backend" "$PYTHON" - <<'PY'
from app.services.event_lifecycle import allowed_transitions
raise SystemExit(0 if "awaiting_review" in allowed_transitions("assessing") else 1)
PY
then pass "ADR-006: awaiting_review remains in lifecycle"; else fail "ADR-006 invariant"; fi
if PYTHONPATH="$REPO_ROOT/backend" "$PYTHON" - <<'PY'
from app.services.confidence_engine import ConfidenceEngine
from app.services.risk_engine import RiskEngine
raise SystemExit(0 if ConfidenceEngine is not RiskEngine else 1)
PY
then pass "ADR-004: confidence and risk engines remain separate"; else fail "ADR-004 invariant"; fi

printf '\n========================================\n'
printf ' E2E SMOKE RESULTS\n  Passed: %d\n  Failed: %d\n  Total:  %d\n' \
  "$PASS" "$FAIL" "$((PASS + FAIL))"
printf '  Coverage: API contracts and deterministic safety invariants\n'
printf '  Excluded: proof of live watsonx Orchestrate execution\n'
printf '========================================\n'
(( FAIL == 0 )) || exit 1

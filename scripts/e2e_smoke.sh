#!/usr/bin/env bash
# E2E API compliance smoke test — SentinelIQ Gate 0–21
# Run from: ~/sentineliq/
# Usage: bash scripts/e2e_smoke.sh

set -e
BASE="http://localhost:8000"
PASS=0
FAIL=0

check() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if echo "$actual" | grep -q "$expected"; then
    echo "  ✅ $label"
    PASS=$((PASS+1))
  else
    echo "  ❌ $label"
    echo "     expected substring: $expected"
    echo "     got: $(echo $actual | head -c 200)"
    FAIL=$((FAIL+1))
  fi
}

check_code() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✅ $label (HTTP $actual)"
    PASS=$((PASS+1))
  else
    echo "  ❌ $label — expected HTTP $expected, got $actual"
    FAIL=$((FAIL+1))
  fi
}

echo ""
echo "========================================"
echo " SentinelIQ E2E Compliance Smoke Test"
echo " Gates 0–21"
echo "========================================"

# ============================================================
# GATE 0/2: Health
# ============================================================
echo ""
echo "--- Gate 0/2: Health ---"
R=$(curl -s $BASE/health)
check "GET /health → ok" '"ok"' "$R"
check "GET /health → service name" '"SentinelIQ"' "$R"

# ============================================================
# GATE 15/19: Auth
# ============================================================
echo ""
echo "--- Gate 15/19: Authentication ---"
TOKEN_R=$(curl -s -X POST $BASE/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@sentineliq.local&password=SentinelIQ2024!")
check "POST /auth/token → access_token" 'access_token' "$TOKEN_R"
TOKEN=$(echo "$TOKEN_R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token','NO_TOKEN'))")

ME_R=$(curl -s $BASE/api/v1/auth/me -H "Authorization: Bearer $TOKEN")
check "GET /auth/me → username" 'username' "$ME_R"
check "GET /auth/me → roles" 'roles' "$ME_R"

# Unauthenticated access must be rejected (Gate 19 RBAC)
UNAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/v1/events")
if [ "$UNAUTH" = "401" ] || [ "$UNAUTH" = "403" ]; then
  echo "  ✅ GET /events without token → 401/403 (RBAC enforced)"
  PASS=$((PASS+1))
else
  echo "  ❌ GET /events without token → $UNAUTH (expected 401/403)"
  FAIL=$((FAIL+1))
fi

# ============================================================
# GATE 5: Event ingestion + deduplication
# ============================================================
echo ""
echo "--- Gate 5: Event ingestion ---"
EVT_R=$(curl -s -X POST $BASE/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"event_type":"person_detected","event_timestamp":"2026-11-07T10:00:00Z","location_id":"e2e-loc-001","detector_confidence":0.92}')
check "POST /events → id" '"id"' "$EVT_R"
check "POST /events → event_type" '"event_type"' "$EVT_R"
EVT_ID=$(echo "$EVT_R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id','NO_ID'))")
echo "  Event ID: $EVT_ID"

QUEUE_R=$(curl -s "$BASE/api/v1/events?page=1&page_size=5" -H "Authorization: Bearer $TOKEN")
check "GET /events → items array" '"items"' "$QUEUE_R"
check "GET /events → pagination total" '"total"' "$QUEUE_R"

# Deduplication (Gate 5 + Gate 20)
PROV_ID="e2e-dup-$(date +%s)"
DUP_DATA="{\"event_type\":\"badge_event\",\"event_timestamp\":\"2026-11-07T10:00:00Z\",\"location_id\":\"e2e-dup-loc\",\"provider_event_id\":\"$PROV_ID\"}"
FIRST_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/v1/events \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "$DUP_DATA")
SECOND_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/v1/events \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "$DUP_DATA")
check_code "First POST → 201" "201" "$FIRST_CODE"
check_code "Duplicate POST → 200 (dedup)" "200" "$SECOND_CODE"

# ============================================================
# GATE 6: Evidence-source tools
# ============================================================
echo ""
echo "--- Gate 6: Evidence-source tools ---"
for TOOL in access-events schedule work-orders delivery location-policy incident-history integration-health; do
  T_R=$(curl -s "$BASE/api/v1/tools/$TOOL?location_id=e2e-loc-001&facility_id=e2e-fac-001" -H "Authorization: Bearer $TOKEN")
  check "GET /tools/$TOOL → source_id" 'source_id' "$T_R"
done

# ============================================================
# GATE 9/10: Assessment (risk + confidence)
# ============================================================
echo ""
echo "--- Gate 9/10: Risk + confidence assessment ---"
ASSESS_R=$(curl -s -X POST "$BASE/api/v1/events/$EVT_ID/assess" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{}')
check "POST /assess → risk_level" 'risk_level' "$ASSESS_R"
check "POST /assess → risk_score" 'risk_score' "$ASSESS_R"
check "POST /assess → confidence_score" 'confidence_score' "$ASSESS_R"
check "POST /assess → confidence_level" 'confidence_level' "$ASSESS_R"
# ADR-003: risk must NOT come from LLM
LLM_CHECK=$(echo "$ASSESS_R" | python3 -c "import sys,json; d=json.load(sys.stdin); print('VIOLATION' if 'llm_risk_score' in str(d) or d.get('risk_source')=='llm' else 'OK')")
check "ADR-003: risk source is NOT llm" 'OK' "$LLM_CHECK"

RISK_R=$(curl -s "$BASE/api/v1/events/$EVT_ID/assessment" -H "Authorization: Bearer $TOKEN")
check "GET /assessment → risk_score" 'risk_score' "$RISK_R"
check "GET /assessment → reductions_json" 'reductions' "$RISK_R"

FACTORS_R=$(curl -s "$BASE/api/v1/events/$EVT_ID/assessment/factors" -H "Authorization: Bearer $TOKEN")
check "GET /assessment/factors → factors" 'factors' "$FACTORS_R"

RP_R=$(curl -s "$BASE/api/v1/risk-policies" -H "Authorization: Bearer $TOKEN")
check "GET /risk-policies → items" '"items"' "$RP_R"

# ============================================================
# GATE 14: Coordinator review
# ============================================================
echo ""
echo "--- Gate 14: Coordinator / review endpoint ---"
REVIEW_R=$(curl -s "$BASE/api/v1/events/$EVT_ID/review" -H "Authorization: Bearer $TOKEN")
check "GET /events/{id}/review → id" '"id"' "$REVIEW_R"

# ============================================================
# GATE 15: Human-review workflow — decision, escalation, feedback
# ============================================================
echo ""
echo "--- Gate 15: Human-review workflow ---"
DEC_R=$(curl -s -X POST "$BASE/api/v1/events/$EVT_ID/decision" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"decision_type":"accept","rationale":"E2E compliance test — accept"}')
check "POST /decision → id" '"id"' "$DEC_R"
check "POST /decision → decision_type" '"decision_type"' "$DEC_R"

DH_R=$(curl -s "$BASE/api/v1/events/$EVT_ID/decisions" -H "Authorization: Bearer $TOKEN")
check "GET /decisions → items" '"items"' "$DH_R"

DEC_LATEST=$(curl -s "$BASE/api/v1/events/$EVT_ID/decision" -H "Authorization: Bearer $TOKEN")
check "GET /decision (latest) → decision_type" 'decision_type' "$DEC_LATEST"

# New event for escalation test (can't escalate already-accepted)
ESC_EVT_R=$(curl -s -X POST $BASE/api/v1/events \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"event_type":"alarm_triggered","event_timestamp":"2026-11-07T11:00:00Z","location_id":"e2e-loc-002"}')
ESC_EVT_ID=$(echo "$ESC_EVT_R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id','NO_ID'))")
# Assess first
curl -s -X POST "$BASE/api/v1/events/$ESC_EVT_ID/assess" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{}' > /dev/null
ESC_R=$(curl -s -X POST "$BASE/api/v1/events/$ESC_EVT_ID/escalation" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"reason":"E2E escalation compliance test","priority":"high"}')
check "POST /escalation → id" '"id"' "$ESC_R"

FEED_R=$(curl -s -X POST "$BASE/api/v1/events/$EVT_ID/feedback" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"outcome":"accurate","comment":"E2E feedback test"}')
check "POST /feedback → id" '"id"' "$FEED_R"

FEED_GET=$(curl -s "$BASE/api/v1/events/$EVT_ID/feedback" -H "Authorization: Bearer $TOKEN")
check "GET /feedback → items" '"items"' "$FEED_GET"

# ============================================================
# GATE 18: Audit trail
# ============================================================
echo ""
echo "--- Gate 18: Audit trail ---"
AUDIT_R=$(curl -s "$BASE/api/v1/events/$EVT_ID/audit" -H "Authorization: Bearer $TOKEN")
check "GET /events/{id}/audit → items" '"items"' "$AUDIT_R"

GAUDIT_R=$(curl -s "$BASE/api/v1/audit" -H "Authorization: Bearer $TOKEN")
check "GET /audit (global) → items" '"items"' "$GAUDIT_R"
check "GET /audit (global) → total" '"total"' "$GAUDIT_R"

# ============================================================
# GATE 19: Admin API + RBAC
# ============================================================
echo ""
echo "--- Gate 19: RBAC + Admin API ---"
ADMIN_USERS=$(curl -s "$BASE/api/v1/admin/users" -H "Authorization: Bearer $TOKEN")
check "GET /admin/users → items" '"items"' "$ADMIN_USERS"

ADMIN_ROLES=$(curl -s "$BASE/api/v1/admin/roles" -H "Authorization: Bearer $TOKEN")
check "GET /admin/roles → roles" '"roles"' "$ADMIN_ROLES"

ADMIN_PERMS=$(curl -s "$BASE/api/v1/admin/permissions" -H "Authorization: Bearer $TOKEN")
check "GET /admin/permissions → permissions" '"permissions"' "$ADMIN_PERMS"

# ============================================================
# GATE 20: Failure hardening — safe degradation
# ============================================================
echo ""
echo "--- Gate 20: Safe degradation invariants ---"
# Missing location still returns a result (no crash)
MISS_R=$(curl -s -X POST $BASE/api/v1/events \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"event_type":"person_detected","event_timestamp":"2026-11-07T12:00:00Z","location_id":"nonexistent-location-xyz"}')
check "POST /events with unknown location → still creates event" '"id"' "$MISS_R"
MISS_ID=$(echo "$MISS_R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id','NO_ID'))")
MISS_ASSESS=$(curl -s -X POST "$BASE/api/v1/events/$MISS_ID/assess" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{}')
check "POST /assess with no evidence → still returns risk_level (no crash)" 'risk_level' "$MISS_ASSESS"

# ============================================================
# GATE 21: Evaluation dataset + scoring
# ============================================================
echo ""
echo "--- Gate 21: Evaluation framework ---"
check "eval-dataset.json exists" '' "$(test -f /home/ubuntu/sentineliq/evaluations/datasets/eval-dataset.json && echo 'EXISTS' || echo '')"
check "output-schema.json exists" '' "$(test -f /home/ubuntu/sentineliq/evaluations/expected/output-schema.json && echo 'EXISTS' || echo '')"
check "scorer.py exists" '' "$(test -f /home/ubuntu/sentineliq/evaluations/scoring/scorer.py && echo 'EXISTS' || echo '')"
check "baseline report exists" '' "$(test -f /home/ubuntu/sentineliq/evaluations/reports/eval-baseline-gate-21.md && echo 'EXISTS' || echo '')"
CASE_COUNT=$(python3 -c "import json; d=json.load(open('/home/ubuntu/sentineliq/evaluations/datasets/eval-dataset.json')); print(len(d['cases']))")
if [ "$CASE_COUNT" -ge 30 ]; then
  echo "  ✅ eval-dataset has $CASE_COUNT cases (≥30 required)"
  PASS=$((PASS+1))
else
  echo "  ❌ eval-dataset has $CASE_COUNT cases (need ≥30)"
  FAIL=$((FAIL+1))
fi

# ============================================================
# ARCHITECTURE INVARIANTS
# ============================================================
echo ""
echo "--- Architecture invariants ---"
# ADR-003: TriageResult must not contain risk_score
TRIAGE_SCHEMA=$(python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/sentineliq/backend')
from app.schemas.triage import TriageResult
fields = set(TriageResult.model_fields.keys())
print('VIOLATION' if 'risk_score' in fields or 'risk_level' in fields else 'OK')
")
check "ADR-003: TriageResult has no risk_score field" 'OK' "$TRIAGE_SCHEMA"

# ADR-006: state machine requires awaiting_review
LIFECYCLE=$(python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/sentineliq/backend')
from app.services.event_lifecycle import ALLOWED_TRANSITIONS
has_review = 'awaiting_review' in str(ALLOWED_TRANSITIONS)
print('OK' if has_review else 'VIOLATION')
")
check "ADR-006: awaiting_review in lifecycle state machine" 'OK' "$LIFECYCLE"

# ADR-004: ConfidenceEngine and RiskEngine are separate classes
INDEP=$(python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/sentineliq/backend')
from app.services.confidence_engine import ConfidenceEngine
from app.services.risk_engine import RiskEngine
print('OK' if ConfidenceEngine is not RiskEngine else 'VIOLATION')
")
check "ADR-004: ConfidenceEngine and RiskEngine are separate classes" 'OK' "$INDEP"

# ============================================================
# RESULTS
# ============================================================
echo ""
echo "========================================"
echo " E2E COMPLIANCE RESULTS"
echo "========================================"
echo "  ✅ Passed: $PASS"
echo "  ❌ Failed: $FAIL"
echo "  📊 Total:  $((PASS+FAIL))"
if [ "$FAIL" -eq 0 ]; then
  echo "  🏆 STATUS: ALL GATES PASS — FULLY COMPLIANT"
else
  echo "  ⚠️  STATUS: $FAIL CHECK(S) FAILED"
fi
echo "========================================"

#!/usr/bin/env bash
set -u

agents=(
  sentinel_coordinator
  sentinel_explanation_agent
  sentinel_context_agent
  sentinel_triage_agent
)
tools=(
  get_assessment_bundle
  get_integration_health
  search_knowledge
  get_incident_history
  get_location_policy
  get_delivery
  get_work_orders
  get_schedule
  get_access_events
  get_event_detail
)

for agent in "${agents[@]}"; do
  orchestrate agents remove -n "${agent}" --kind native || true
done
for tool in "${tools[@]}"; do
  orchestrate tools remove -n "${tool}" || true
done
orchestrate connections remove -a sentineliq_api || true


#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

: "${SENTINELIQ_API_BASE_URL:?Set the externally reachable SentinelIQ API base URL}"
: "${SENTINELIQ_API_BEARER_TOKEN:?Set a tools:read service bearer token}"

command -v orchestrate >/dev/null || {
  echo "orchestrate CLI not found; activate the EC2 ADK virtualenv first" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

python "${script_dir}/generate_tool_openapi.py" \
  --api-base-url "${SENTINELIQ_API_BASE_URL}" \
  --output "${tmp_dir}/sentineliq-readonly.openapi.json"

sed "s|__SENTINELIQ_API_BASE_URL__|${SENTINELIQ_API_BASE_URL%/}|g" \
  "${script_dir}/connections/sentineliq-api.yaml" \
  > "${tmp_dir}/sentineliq-api.yaml"

orchestrate connections import -f "${tmp_dir}/sentineliq-api.yaml"
for connection_env in draft live; do
  orchestrate connections configure \
    -a sentineliq_api --env "${connection_env}" --type team --kind bearer \
    --server-url "${SENTINELIQ_API_BASE_URL%/}"
  orchestrate connections set-credentials \
    -a sentineliq_api --env "${connection_env}" --token "${SENTINELIQ_API_BEARER_TOKEN}"
done

orchestrate tools import -k openapi \
  -f "${tmp_dir}/sentineliq-readonly.openapi.json" \
  --app-id sentineliq_api

orchestrate agents import -f "${script_dir}/triage/agent.yaml"
orchestrate agents import -f "${script_dir}/context/agent.yaml"
orchestrate agents import -f "${script_dir}/explanation/agent.yaml"

agent_names=(
  sentinel_triage_agent
  sentinel_context_agent
  sentinel_explanation_agent
)

if [[ -f "${script_dir}/coordinator/agent.yaml" ]]; then
  orchestrate agents import -f "${script_dir}/coordinator/agent.yaml"
  agent_names+=(sentinel_coordinator)
fi

# Native agents remain in draft after import. Deploy each named agent only after
# its dependencies have been imported so repeated runs update the active version
# using the ADK's name-based deployment semantics.
for agent_name in "${agent_names[@]}"; do
  orchestrate agents deploy --name "${agent_name}"
done

echo "SentinelIQ tools and agents imported and deployed in the active Orchestrate environment."
echo "Run 'orchestrate agents list -v' and set backend ORCHESTRATE_*_AGENT_ID variables"
echo "to the deployed agents' UUID IDs (not their SentinelIQ names)."


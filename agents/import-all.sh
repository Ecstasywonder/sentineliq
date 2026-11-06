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
orchestrate connections configure \
  -a sentineliq_api --env draft --type team --kind bearer
orchestrate connections set-credentials \
  -a sentineliq_api --env draft --token "${SENTINELIQ_API_BEARER_TOKEN}"

orchestrate tools import -k openapi \
  -f "${tmp_dir}/sentineliq-readonly.openapi.json" \
  --app-id sentineliq_api

orchestrate agents import -f "${script_dir}/triage/agent.yaml"
orchestrate agents import -f "${script_dir}/context/agent.yaml"
orchestrate agents import -f "${script_dir}/explanation/agent.yaml"

if [[ -f "${script_dir}/coordinator/agent.yaml" ]]; then
  orchestrate agents import -f "${script_dir}/coordinator/agent.yaml"
fi

echo "SentinelIQ tools and agents imported into the active Orchestrate environment."


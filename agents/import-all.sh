#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

: "${SENTINELIQ_API_BASE_URL:?Set the externally reachable SentinelIQ API base URL}"
: "${SENTINELIQ_API_CLIENT_ID:?Set the Orchestrate tools OAuth client ID}"
: "${SENTINELIQ_API_CLIENT_SECRET:?Set the Orchestrate tools OAuth client secret}"

command -v orchestrate >/dev/null || {
  echo "orchestrate CLI not found; activate the EC2 ADK virtualenv first" >&2
  exit 1
}

# Generate the OpenAPI bundle with the repository's backend environment when it
# exists.  Minimal EC2 images commonly expose only ``python3`` and the system
# interpreter does not contain the backend dependencies, so hard-coding
# ``python`` makes an otherwise valid deployment fail before the ADK is used.
if [[ -n "${SENTINELIQ_PYTHON_BIN:-}" ]]; then
  python_bin="${SENTINELIQ_PYTHON_BIN}"
elif [[ -x "${repo_root}/backend/.venv/bin/python" ]]; then
  python_bin="${repo_root}/backend/.venv/bin/python"
elif command -v python3 >/dev/null; then
  python_bin="$(command -v python3)"
elif command -v python >/dev/null; then
  python_bin="$(command -v python)"
else
  echo "Python interpreter not found; install Python 3 or set SENTINELIQ_PYTHON_BIN" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

# Schema generation is a build-time operation and does not connect to the
# database.  Do not apply production-runtime credential validation to this
# host-side process; Compose supplies the resolved production settings to the
# running backend separately.
APP_ENV=development "${python_bin}" "${script_dir}/generate_tool_openapi.py" \
  --api-base-url "${SENTINELIQ_API_BASE_URL}" \
  --output "${tmp_dir}/sentineliq-readonly.openapi.json"

sed "s|__SENTINELIQ_API_BASE_URL__|${SENTINELIQ_API_BASE_URL%/}|g" \
  "${script_dir}/connections/sentineliq-api.yaml" \
  > "${tmp_dir}/sentineliq-api.yaml"

orchestrate connections import -f "${tmp_dir}/sentineliq-api.yaml"
for connection_env in draft live; do
  orchestrate connections configure \
    -a sentineliq_api --env "${connection_env}" --type team \
    --kind oauth_auth_client_credentials_flow \
    --server-url "${SENTINELIQ_API_BASE_URL%/}"
  orchestrate connections set-credentials \
    -a sentineliq_api --env "${connection_env}" \
    --client-id "${SENTINELIQ_API_CLIENT_ID}" \
    --client-secret "${SENTINELIQ_API_CLIENT_SECRET}" \
    --send-via header \
    --token-url "${SENTINELIQ_API_BASE_URL%/}/api/v1/auth/service-token" \
    --grant-type client_credentials \
    --scope tools:read
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


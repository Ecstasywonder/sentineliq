"""Contract tests for the shared watsonx Orchestrate SaaS client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.orchestrate_client import OrchestrateClient, validate_watsonx_base_url


def _response(data: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = data
    return response


def _mock_async_client(*responses: MagicMock) -> tuple[MagicMock, AsyncMock]:
    client = AsyncMock()
    client.post = AsyncMock(side_effect=responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, client.post


@pytest.mark.asyncio
async def test_chat_uses_v2_iam_bearer_contract() -> None:
    client, post = _mock_async_client(
        _response({"access_token": "short-lived-token"}),
        _response({"choices": [{"message": {"content": '{"ok":true}'}}]}),
    )
    with patch("app.services.orchestrate_client.httpx.AsyncClient", return_value=client):
        content, telemetry = await OrchestrateClient(
            base_url="https://tenant.ibm-watson-orchestrate.com/",
            api_key="cloud-api-key",
            timeout=12.0,
        ).chat(
            agent_id="triage agent/1",
            system_prompt="Return JSON.",
            input_payload={"event_id": "EVT-1"},
        )

    assert content == '{"ok":true}'
    assert telemetry[0]["tool_name"] == "orchestrate_chat_completion"
    iam_call, chat_call = post.await_args_list
    assert iam_call.args[0] == "https://iam.cloud.ibm.com/identity/token"
    assert iam_call.kwargs["data"]["apikey"] == "cloud-api-key"
    assert chat_call.args[0] == (
        "https://tenant.ibm-watson-orchestrate.com/v2/orchestrate/"
        "triage%20agent%2F1/chat/completions"
    )
    assert chat_call.kwargs["headers"]["Authorization"] == "Bearer short-lived-token"
    assert chat_call.kwargs["json"]["stream"] is False
    assert chat_call.kwargs["json"]["messages"][1]["content"] == '{"event_id":"EVT-1"}'


@pytest.mark.asyncio
async def test_chat_accepts_openai_text_content_parts() -> None:
    client, post = _mock_async_client(
        _response({"access_token": "token"}),
        _response(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "first"},
                                {"type": "text", "text": {"value": " second"}},
                            ]
                        }
                    }
                ]
            }
        ),
    )
    with patch("app.services.orchestrate_client.httpx.AsyncClient", return_value=client):
        content, _ = await OrchestrateClient(
            base_url=("https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123/"),
            api_key="key",
            timeout=12.0,
            api_version="v1_5",
        ).chat(agent_id="agent", system_prompt="prompt", input_payload={})

    assert content == "first second"
    assert post.await_args_list[1].args[0] == (
        "https://us-south.watson-orchestrate.cloud.ibm.com/instances/instance-123/"
        "v1_5/orchestrate/agent/chat/completions"
    )


@pytest.mark.asyncio
async def test_chat_rejects_undocumented_top_level_output_shape() -> None:
    client, _ = _mock_async_client(
        _response({"access_token": "token"}),
        _response({"output": "not the documented chat-completions shape"}),
    )
    with (
        patch("app.services.orchestrate_client.httpx.AsyncClient", return_value=client),
        pytest.raises(ValueError, match="no choices"),
    ):
        await OrchestrateClient(
            base_url="https://tenant.ibm-watson-orchestrate.com",
            api_key="key",
            timeout=12.0,
        ).chat(agent_id="agent", system_prompt="prompt", input_payload={})


@pytest.mark.asyncio
async def test_chat_stops_when_iam_exchange_has_no_access_token() -> None:
    client, post = _mock_async_client(_response({"token_type": "Bearer"}))
    with (
        patch("app.services.orchestrate_client.httpx.AsyncClient", return_value=client),
        pytest.raises(ValueError, match="no access_token"),
    ):
        await OrchestrateClient(
            base_url="https://tenant.ibm-watson-orchestrate.com",
            api_key="key",
            timeout=12.0,
        ).chat(agent_id="agent", system_prompt="prompt", input_payload={})

    assert post.await_count == 1


@pytest.mark.parametrize(
    "base_url",
    [
        "http://tenant.ibm-watson-orchestrate.com",
        "https://tenant.ibm-watson-orchestrate.com.evil.example",
        "https://watson-orchestrate.cloud.ibm.com",
        "https://ibm-watson-orchestrate.com",
        "https://127.0.0.1",
        "https://localhost",
        "https://bad_name.ibm-watson-orchestrate.com",
        "https://bad..ibm-watson-orchestrate.com",
        "https://user:password@tenant.ibm-watson-orchestrate.com",
        "https://tenant.ibm-watson-orchestrate.com:8443",
        "https://tenant.ibm-watson-orchestrate.com?redirect=https://evil.example",
        "https://tenant.ibm-watson-orchestrate.com#fragment",
        "https://tenant.ibm-watson-orchestrate.com/arbitrary/path",
        "https://tenant.ibm-watson-orchestrate.com/instances/..",
        "https://tenant.ibm-watson-orchestrate.com/instances/%2e%2e",
    ],
)
def test_client_rejects_unsafe_base_url_before_network_call(base_url: str) -> None:
    with patch("app.services.orchestrate_client.httpx.AsyncClient") as async_client:
        with pytest.raises(ValueError, match="Orchestrate base URL"):
            OrchestrateClient(base_url=base_url, api_key="secret", timeout=12.0)

    async_client.assert_not_called()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://tenant.ibm-watson-orchestrate.com",
        "https://api.eu-gb.watson-orchestrate.cloud.ibm.com",
        "https://tenant.ibm-watson-orchestrate.com:443/instances/abc_123-DEF",
    ],
)
def test_client_accepts_allowlisted_saas_base_urls(base_url: str) -> None:
    OrchestrateClient(base_url=base_url, api_key="secret", timeout=12.0)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://us-south.ml.cloud.ibm.com",
        "https://us-south.ml.cloud.ibm.com.evil.example",
        "https://ml.cloud.ibm.com",
        "https://127.0.0.1",
        "https://localhost",
        "https://bad_name.ml.cloud.ibm.com",
        "https://secret@us-south.ml.cloud.ibm.com",
        "https://us-south.ml.cloud.ibm.com:8443",
        "https://us-south.ml.cloud.ibm.com?redirect=https://evil.example",
        "https://us-south.ml.cloud.ibm.com#fragment",
        "https://us-south.ml.cloud.ibm.com/ml/v1",
    ],
)
def test_watsonx_validator_rejects_unsafe_url(base_url: str) -> None:
    with pytest.raises(ValueError, match=r"watsonx\.ai base URL"):
        validate_watsonx_base_url(base_url)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://us-south.ml.cloud.ibm.com", "https://us-south.ml.cloud.ibm.com"),
        ("https://eu-de.ml.cloud.ibm.com/", "https://eu-de.ml.cloud.ibm.com"),
        (
            "https://jp-tok.ml.cloud.ibm.com:443",
            "https://jp-tok.ml.cloud.ibm.com:443",
        ),
    ],
)
def test_watsonx_validator_accepts_regional_ibm_saas_url(base_url: str, expected: str) -> None:
    assert validate_watsonx_base_url(base_url) == expected

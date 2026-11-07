"""Shared IBM watsonx Orchestrate chat-completions client.

The SaaS contract used here is the documented direct-agent chat endpoint. IBM
Cloud API keys are first exchanged for a short-lived IAM bearer token; the
``ZenApiKey`` scheme is intentionally not used because it is specific to
on-premises deployments.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_ORCHESTRATE_SAAS_HOST_SUFFIXES = (
    ".ibm-watson-orchestrate.com",
    ".watson-orchestrate.cloud.ibm.com",
)
_WATSONX_SAAS_HOST_SUFFIXES = (".ml.cloud.ibm.com",)
_INSTANCE_PATH_RE = re.compile(r"/instances/[A-Za-z0-9._~-]+")
_DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _validated_ibm_saas_base_url(
    value: str,
    *,
    host_suffixes: tuple[str, ...],
    service_name: str,
    allow_instance_path: bool,
) -> str:
    """Return a normalized IBM SaaS URL suitable for bearer-token requests.

    Both Orchestrate and watsonx.ai exchange API keys through IBM IAM, then
    attach the resulting bearer token to their configured service URL. A
    strict hostname allowlist prevents that token from being sent to an SSRF
    target or a deceptively named attacker-controlled host.
    """
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{service_name} base URL is required.")
    if candidate != value or any(character.isspace() for character in candidate):
        raise ValueError(f"{service_name} base URL must not contain whitespace.")
    if "?" in candidate or "#" in candidate:
        raise ValueError(f"{service_name} base URL must not contain a query or fragment.")

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"{service_name} base URL is invalid.") from exc

    if parsed.scheme.lower() != "https":
        raise ValueError(f"{service_name} base URL must use HTTPS.")
    if not parsed.netloc or hostname is None:
        raise ValueError(f"{service_name} base URL must include a hostname.")
    if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{service_name} base URL must not include user information.")
    if port not in (None, 443):
        raise ValueError(f"{service_name} base URL may only use HTTPS port 443.")

    normalized_host = hostname.lower()
    try:
        normalized_host.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{service_name} base URL hostname must be ASCII.") from exc
    if len(normalized_host) > 253 or any(
        not _DNS_LABEL_RE.fullmatch(label) for label in normalized_host.split(".")
    ):
        raise ValueError(f"{service_name} base URL hostname is invalid.")
    if not any(
        normalized_host.endswith(suffix) and normalized_host != suffix.removeprefix(".")
        for suffix in host_suffixes
    ):
        raise ValueError(f"{service_name} base URL hostname is not an allowed IBM SaaS host.")

    path = parsed.path.rstrip("/")
    if path and (not allow_instance_path or not _INSTANCE_PATH_RE.fullmatch(path)):
        expected_path = "empty or /instances/<instance-id>" if allow_instance_path else "empty"
        raise ValueError(f"{service_name} base URL path must be {expected_path}.")
    if path.endswith("/.") or path.endswith("/.."):
        raise ValueError(f"{service_name} base URL contains an invalid instance ID.")

    authority = normalized_host if port is None else f"{normalized_host}:443"
    return f"https://{authority}{path}"


def validate_orchestrate_base_url(value: str) -> str:
    """Validate and normalize an IBM watsonx Orchestrate SaaS base URL."""
    return _validated_ibm_saas_base_url(
        value,
        host_suffixes=_ORCHESTRATE_SAAS_HOST_SUFFIXES,
        service_name="Orchestrate",
        allow_instance_path=True,
    )


def validate_watsonx_base_url(value: str) -> str:
    """Validate and normalize an IBM watsonx.ai regional SaaS base URL."""
    return _validated_ibm_saas_base_url(
        value,
        host_suffixes=_WATSONX_SAAS_HOST_SUFFIXES,
        service_name="watsonx.ai",
        allow_instance_path=False,
    )


class OrchestrateClient:
    """Invoke one imported Orchestrate agent through the SaaS chat API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float,
        api_version: Literal["v1"] = "v1",
    ) -> None:
        validated_base_url = validate_orchestrate_base_url(base_url)
        if not api_key:
            raise ValueError("Orchestrate API key is required.")
        if api_version != "v1":
            raise ValueError("Orchestrate SaaS direct-agent API version must be v1.")
        self._base_url = validated_base_url
        self._api_key = api_key
        self._timeout = timeout
        self._api_version = api_version

    async def chat(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        input_payload: Mapping[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return assistant text plus a non-sensitive telemetry record."""
        try:
            parsed_agent_id = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Orchestrate agent ID must be a deployed agent UUID.") from exc
        if str(parsed_agent_id) != agent_id:
            raise ValueError("Orchestrate agent ID must be a canonical deployed agent UUID.")

        iam_token = await self._get_iam_token()
        encoded_agent_id = quote(agent_id, safe="")
        url = (
            f"{self._base_url}/{self._api_version}/orchestrate/{encoded_agent_id}/chat/completions"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(input_payload, default=str, separators=(",", ":")),
                },
            ],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {iam_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            started = time.monotonic()
            response = await client.post(url, headers=headers, json=payload)
            duration_ms = (time.monotonic() - started) * 1000
            response.raise_for_status()

        content = self._extract_content(response.json())
        return content, [
            {
                "tool_name": "orchestrate_chat_completion",
                "status": "success",
                "duration_ms": duration_ms,
                "sequence": 0,
            }
        ]

    async def _get_iam_token(self) -> str:
        async with httpx.AsyncClient(timeout=min(self._timeout, 15.0)) as client:
            response = await client.post(
                _IAM_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": self._api_key,
                },
            )
            response.raise_for_status()
        token = response.json().get("access_token", "")
        if not isinstance(token, str) or not token:
            raise ValueError("IAM token exchange returned no access_token.")
        return token

    @staticmethod
    def _extract_content(data: Any) -> str:
        """Extract text from OpenAI-style string or content-part responses."""
        if not isinstance(data, dict):
            raise ValueError("Orchestrate response was not a JSON object.")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("Orchestrate response contained no choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ValueError("Orchestrate response choice contained no message.")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict) and isinstance(text.get("value"), str):
                    parts.append(text["value"])
            joined = "".join(parts)
            if joined.strip():
                return joined
        raise ValueError("Orchestrate response content was empty.")

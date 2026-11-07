"""ASGI middleware that enforces a hard request-body byte ceiling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Reject oversized bodies without buffering an unbounded chunked upload."""

    def __init__(self, app: ASGIApp, *, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_content_length = headers.get(b"content-length")
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length)
            except ValueError:
                await self._error(
                    scope,
                    receive,
                    send,
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "Content-Length must be an integer.",
                )
                return
            if content_length < 0:
                await self._error(
                    scope,
                    receive,
                    send,
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "Content-Length must not be negative.",
                )
                return
            if content_length > self.max_body_size:
                await self._too_large(scope, receive, send)
                return

        # Read at most the configured ceiling before entering framework body
        # parsing. Raising from ``receive`` is not reliable because Starlette
        # can translate that exception into a generic 400 response. This
        # bounded buffer preserves a deterministic 413 for chunked uploads
        # without ever allocating an unbounded request body.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_size:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._error(
            scope,
            receive,
            send,
            413,
            "REQUEST_TOO_LARGE",
            f"Request body exceeds {self.max_body_size} bytes.",
        )

    @staticmethod
    async def _error(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": {"code": code, "message": message}},
        )
        await response(scope, receive, send)

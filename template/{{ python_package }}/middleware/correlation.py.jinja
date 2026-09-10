"""Vendored correlation-ID / request-ID middleware (D-011).

A small pure-ASGI middleware, deliberately not a dependency on
``asgi-correlation-id``. It:

* reads an inbound ``X-Request-ID`` header (configurable), or generates a UUID4
  when the header is absent or empty,
* stores the value in a :class:`contextvars.ContextVar` so any code in the
  request task can read it (``get_request_id()``),
* binds it into structlog's context vars so every log line for the request
  carries ``request_id``,
* echoes it back on the response ``X-Request-ID`` header.

Contextvars are async-task-safe, so this works correctly under concurrent
requests without thread-local hazards.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import bind_contextvars, unbind_contextvars

request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")

_DEFAULT_HEADER = "x-request-id"


def get_request_id() -> str:
    """Return the current request's correlation id, or ``""`` outside a request."""

    return request_id_ctx_var.get()


class CorrelationIdMiddleware:
    """Assigns every HTTP request a stable correlation id."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = _DEFAULT_HEADER,
        generator: Callable[[], str] | None = None,
    ) -> None:
        self.app = app
        self.header_name = header_name.lower()
        self.generator: Callable[[], str] = generator or (lambda: str(uuid.uuid4()))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw = headers.get(self.header_name.encode("latin-1"), b"").decode("latin-1").strip()
        request_id = raw or self.generator()

        token = request_id_ctx_var.set(request_id)
        bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                response_headers.append(
                    (self.header_name.encode("latin-1"), request_id.encode("latin-1"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            unbind_contextvars("request_id")
            request_id_ctx_var.reset(token)

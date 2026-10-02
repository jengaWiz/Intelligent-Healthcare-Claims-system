"""Unexpected errors must not reach the ASGI server's raw exception logger."""

import logging
from uuid import uuid4

from starlette.responses import JSONResponse

logger = logging.getLogger("claims.http")


class SafeErrorBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            request_id = scope.get("state", {}).get("request_id", str(uuid4()))
            logger.error("request_id=%s code=internal_error", request_id)
            # Never rethrow a raw exception containing database/document/secret data.
            if not started:
                await JSONResponse(
                    {
                        "code": "internal_error",
                        "message": "Request could not be completed",
                        "request_id": request_id,
                    },
                    status_code=500,
                    headers={"X-Request-ID": request_id},
                )(scope, receive, send)
            else:
                # Protected APIs have no streamed content. End any failed public
                # static-file response without exposing the underlying exception.
                try:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                except Exception:
                    pass  # Disconnected clients do not need another error response.

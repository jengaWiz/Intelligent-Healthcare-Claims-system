"""Bound non-upload request bodies before JSON/form parsing."""

from starlette.responses import JSONResponse


class RequestSizeMiddleware:
    def __init__(self, app, limit=65536):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        if scope["path"].startswith("/claims/") and scope["path"].endswith("/documents"):
            return await self.app(scope, receive, send)
        count = 0
        oversized = False

        async def bounded_receive():
            nonlocal count, oversized
            message = await receive()
            count += len(message.get("body", b""))
            if count > self.limit:
                oversized = True
                return {"type": "http.request", "body": b"!", "more_body": False}
            return message

        async def bounded_send(message):
            if not oversized:
                await send(message)

        await self.app(scope, bounded_receive, bounded_send)
        if oversized:
            await JSONResponse(
                {
                    "code": "request_too_large",
                    "message": "Request exceeds the configured limit",
                    "request_id": scope.get("state", {}).get("request_id", "unavailable"),
                },
                status_code=413,
            )(scope, receive, send)

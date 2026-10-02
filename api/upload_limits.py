"""Bound multipart traffic before Starlette can spool it to temporary storage."""

from starlette.formparsers import MultiPartException

MULTIPART_OVERHEAD_BYTES = 64 * 1024


class UploadSizeMiddleware:
    def __init__(self, app, max_upload_bytes):
        self.app = app
        self.budget = max_upload_bytes + MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if not (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and path.startswith("/claims/")
            and path.endswith("/documents")
        ):
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})
        lengths = [value for key, value in scope.get("headers", []) if key == b"content-length"]
        declared_large = False
        if lengths:
            try:
                declared_large = int(lengths[0]) > self.budget
            except ValueError:
                pass  # The actual byte counter remains authoritative.
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            if declared_large:
                state["upload_request_too_large"] = True
                raise MultiPartException("Upload request exceeds configured limit")
            message = await receive()
            if message["type"] == "http.disconnect":
                # MultipartParser closes spooled files on MultiPartException.
                raise MultiPartException("Upload interrupted")
            consumed += len(message.get("body", b""))
            if consumed > self.budget:
                state["upload_request_too_large"] = True
                raise MultiPartException("Upload request exceeds configured limit")
            return message

        await self.app(scope, bounded_receive, send)

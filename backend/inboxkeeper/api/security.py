"""Guards for an API that only ever listens on localhost.

Binding to 127.0.0.1 isn't enough on its own: any web page the user visits can
still send requests to it. Two checks close that gap:

* Host header allowlist, which defeats DNS rebinding (evil.com resolving to
  127.0.0.1 so the browser treats our API as same-origin).
* Origin check on state-changing requests, which stops cross-site form posts
  and fetch() calls that CORS alone wouldn't block (simple requests are sent
  before CORS is consulted; only the response is hidden).
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            # Browsers always send Origin on cross-site POSTs. Requests without
            # one come from non-browser clients (curl, tests), which can't be
            # driven by a malicious page.
            if origin is not None and origin not in self.allowed_origins:
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        return await call_next(request)

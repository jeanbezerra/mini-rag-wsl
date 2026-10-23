import re
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def local_authority(value: str, *, origin: bool = False) -> bool:
    pattern = r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?"
    if origin:
        pattern = r"https?://" + pattern
    if re.fullmatch(pattern, value, re.IGNORECASE) is None:
        return False
    try:
        parsed = urlsplit(value if origin else "//" + value)
        return (
            parsed.hostname in LOCAL_HOSTS
            and not parsed.netloc.endswith(":")
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and (parsed.scheme in {"http", "https"} if origin else not parsed.scheme)
        )
    except ValueError:
        return False


class LocalAccessMiddleware:
    """Validate every route before an SSE response can start."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            hosts, origins = headers.getlist("host"), headers.getlist("origin")
            if len(hosts) != 1 or not local_authority(hosts[0]):
                await PlainTextResponse("Invalid Host header", 421)(scope, receive, send)
                return
            if len(origins) > 1 or (origins and not local_authority(origins[0], origin=True)):
                await PlainTextResponse("Invalid Origin header", 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)

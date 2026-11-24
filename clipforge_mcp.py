"""Private MCP prototype. Run separately from the public web service."""
import os
import re
import secrets
import httpx
from mcp.server.fastmcp import FastMCP
from starlette.responses import Response
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

BASE = os.environ.get("CLIPFORGE_API", "https://clipforge-web-dccq.onrender.com").rstrip("/")
TOKEN = os.environ.get("CLIPFORGE_MCP_TOKEN", "")
mcp = FastMCP("ClipForge AI", stateless_http=True, json_response=True)

class RequireToken(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        supplied = request.headers.get("authorization", "")
        if not TOKEN or not secrets.compare_digest(supplied, "Bearer " + TOKEN):
            return Response("Unauthorized", status_code=401)
        return await call_next(request)

async def api(method, path, **kwargs):
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        response = await client.request(method, BASE + path, **kwargs)
        response.raise_for_status()
        return response.json()

@mcp.tool()
async def health() -> dict:
    """Check whether ClipForge is available."""
    return await api("GET", "/api/health")

@mcp.tool()
async def create_clip(url: str, rights: bool, duration: int = 45,
                      start: float = -1, subtitles: bool = True) -> dict:
    """Queue one vertical 1080p clip from an authorized source. Subtitles use the current engine; translation is not guaranteed. No publication."""
    if not rights:
        raise ValueError("Permission to use source video is required.")
    if duration not in (30, 45):
        raise ValueError("Choose 30 or 45 seconds.")
    return await api("POST", "/api/jobs", data={
        "url": url, "rights": "true", "length": str(duration),
        "count": "1", "output_quality": "1080", "framing": "crop",
        "start": str(start), "smart": str(start == -1).lower(),
        "subtitles": str(subtitles).lower(), "region": "CL",
    })

@mcp.tool()
async def clip_status(job_id: str) -> dict:
    """Check job progress and return preview URL only when complete."""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid job ID.")
    result = await api("GET", "/api/jobs/" + job_id)
    if result.get("status") == "done" and result.get("clips"):
        result["preview_url"] = BASE + "/api/jobs/" + job_id + "/clips/1"
    return result

app = mcp.streamable_http_app()
app.add_middleware(RequireToken)

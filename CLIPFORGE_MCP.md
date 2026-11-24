# ClipForge AI — MCP prototype

Install separately: `pip install 'mcp>=1.12,<2' 'httpx>=0.28,<1' uvicorn`.
Set CLIPFORGE_MCP_TOKEN to a strong random secret and CLIPFORGE_API to a trusted ClipForge server URL. Run `uvicorn clipforge_mcp:app --host 127.0.0.1 --port 8001`.

Tools: health, create_clip, clip_status. Transport: Streamable HTTP at /mcp. Prototype requires a Bearer token; not yet an OAuth-enabled ChatGPT app. Never expose the token in a URL or source code. Before remote deployment, implement compatible OAuth, per-user job ownership, API-side auth and quotas, persistent job storage, HTTPS and origin/host validation. Test unauthorized requests, MCP handshake, real job creation, preview, Spanish translation and failure handling. Current API supports up to 60-minute sources and fixed clip durations; chat spikes and Spanish translation are not yet implemented. Do not publish or activate billing automatically.

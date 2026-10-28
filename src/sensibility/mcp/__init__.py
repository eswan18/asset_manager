"""Agent access: the MCP endpoint at /mcp.

- `tokens`: configuration and verification of identity's access tokens.
- `gate`: the ASGI gate in front of the SDK (401/403, the caller, scopes)
  and the protected resource metadata document.
- `tools`: the eight tools as plain functions over the service layer.
- `results`: their structured results.
- `server`: the SDK's MCPServer, registering the tools thinly, and how it
  is mounted in the FastAPI app.
"""

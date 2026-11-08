"""Stdio MCP entry point containing only deterministic rule-engine tools."""

from mcp.server import MCPServer

from src.mcp_servers.tools.eligibility import register_tools


mcp = MCPServer("rule-engine")
register_tools(mcp)


if __name__ == "__main__":
    mcp.run()

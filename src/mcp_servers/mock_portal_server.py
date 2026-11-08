"""Stdio MCP entry point containing only mock-portal HTTP adapter tools."""

from mcp.server import MCPServer

from src.mcp_servers.rule_data import get_active_rule_data
from src.mcp_servers.tools.applications import register_tools


get_active_rule_data()
mcp = MCPServer("mock-portal")
register_tools(mcp)


if __name__ == "__main__":
    mcp.run()

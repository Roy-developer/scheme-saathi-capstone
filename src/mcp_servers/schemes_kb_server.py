"""Stdio MCP entry point containing only read-only scheme knowledge tools."""

from mcp.server import MCPServer

from src.mcp_servers.rule_data import get_active_rule_data
from src.mcp_servers.tools.scheme_search import register_tools


get_active_rule_data()
mcp = MCPServer("schemes-kb")
register_tools(mcp)


if __name__ == "__main__":
    mcp.run()

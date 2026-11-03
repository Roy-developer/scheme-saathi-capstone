"""Single MCP server entry point for all Scheme Saathi tools."""

from mcp.server import MCPServer

from src.mcp_servers.tools.eligibility import register_tools as register_eligibility
from src.mcp_servers.tools.scheme_search import register_tools as register_scheme_search


# Create one server; each tool module registers its tools on this same object.
mcp = MCPServer("scheme-saathi")
register_eligibility(mcp)
register_scheme_search(mcp)


if __name__ == "__main__":
    # Serve every registered tool over stdio for the FastAPI MCP client.
    mcp.run()

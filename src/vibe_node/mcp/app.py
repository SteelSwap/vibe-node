"""FastMCP application instance.

Separated from search_server.py to avoid circular imports.
Tool modules import `mcp` from here, not from search_server.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vibe-search")

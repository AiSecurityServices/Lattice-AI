from lattice_ai.adapters.http_api import HttpApiAdapter
from lattice_ai.adapters.mcp import McpAdapter
from lattice_ai.tools import register_adapter

register_adapter(McpAdapter())
register_adapter(HttpApiAdapter())

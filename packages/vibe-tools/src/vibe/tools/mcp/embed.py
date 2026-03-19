"""Query embedding via Ollama for the MCP server."""
from vibe_node.embed.client import EmbeddingClient

_client: EmbeddingClient | None = None


async def embed_query(text: str) -> list[float]:
    """Embed a query string using the configured Ollama model."""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return await _client.embed(text)


async def close():
    """Close the embedding client."""
    global _client
    if _client:
        await _client.close()
        _client = None

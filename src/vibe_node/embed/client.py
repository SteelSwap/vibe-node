"""Ollama-compatible embedding client.

Uses the OpenAI-compatible /v1/embeddings endpoint that Ollama exposes.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "hf.co/jinaai/jina-code-embeddings-1.5b-GGUF:Q8_0",
)


class EmbeddingClient:
    """Async client for generating embeddings via Ollama."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = EMBEDDING_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a vector."""
        response = await self._client.post(
            f"{self.base_url}/v1/embeddings",
            json={"model": self.model, "input": text},
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    async def embed_batch(
        self, texts: list[str], batch_size: int = 16
    ) -> list[list[float]]:
        """Embed a batch of texts. Chunks into sub-batches to avoid timeouts."""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            response = await self._client.post(
                f"{self.base_url}/v1/embeddings",
                json={"model": self.model, "input": chunk},
            )
            response.raise_for_status()
            data = response.json()["data"]
            data.sort(key=lambda x: x["index"])
            all_embeddings.extend(d["embedding"] for d in data)
        return all_embeddings

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()

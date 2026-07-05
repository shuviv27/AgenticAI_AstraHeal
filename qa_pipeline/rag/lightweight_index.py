from __future__ import annotations

from dataclasses import dataclass
from qa_pipeline.core.text import words


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


class LightweightRagIndex:
    """Small local RAG-style lexical index for offline demos.

    Enterprise deployments can replace this with Qdrant, Chroma, Azure AI Search, or pgvector.
    """

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []

    def add(self, chunk_id: str, text: str, metadata: dict) -> None:
        self.chunks.append(Chunk(chunk_id, text, metadata))

    def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        q = set(w.lower() for w in words(query))
        scored = []
        for chunk in self.chunks:
            c = set(w.lower() for w in words(chunk.text))
            score = len(q & c)
            if score:
                scored.append((score, chunk))
        return [c for _, c in sorted(scored, key=lambda x: x[0], reverse=True)[:top_k]]

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from app.config import get_settings


def vector_backend_status() -> dict[str, Any]:
    settings = get_settings()
    backend = "local"
    faiss_available = False
    numpy_available = False
    try:
        import faiss  # type: ignore  # noqa: F401

        faiss_available = True
    except Exception:
        faiss_available = False
    try:
        import numpy  # type: ignore  # noqa: F401

        numpy_available = True
    except Exception:
        numpy_available = False
    if settings.knowledge_vector_provider.lower() in {"auto", "faiss"} and faiss_available and numpy_available:
        backend = "faiss"
    return {
        "provider": settings.knowledge_vector_provider,
        "backend": backend,
        "dimensions": settings.knowledge_vector_dimensions,
        "faiss_available": faiss_available,
        "numpy_available": numpy_available,
    }


class VectorSearchIndex:
    def __init__(self, *, dimensions: int | None = None, provider: str | None = None) -> None:
        settings = get_settings()
        self.dimensions = max(64, min(dimensions or settings.knowledge_vector_dimensions, 2048))
        self.provider = (provider or settings.knowledge_vector_provider or "auto").lower()

    def search(self, chunks: list[dict[str, Any]], query: str, *, limit: int) -> list[dict[str, Any]]:
        if not chunks or not query.strip():
            return []
        if self.provider in {"auto", "faiss"}:
            faiss_hits = self._search_faiss(chunks, query, limit=limit)
            if faiss_hits is not None:
                return faiss_hits
        return self._search_local(chunks, query, limit=limit)

    def _search_faiss(self, chunks: list[dict[str, Any]], query: str, *, limit: int) -> list[dict[str, Any]] | None:
        try:
            import faiss  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            return None

        matrix = np.array([hashed_embedding(str(item.get("content") or ""), self.dimensions) for item in chunks], dtype="float32")
        query_vector = np.array([hashed_embedding(query, self.dimensions)], dtype="float32")
        index = faiss.IndexFlatIP(self.dimensions)
        index.add(matrix)
        scores, positions = index.search(query_vector, min(limit, len(chunks)))
        hits = []
        for score, pos in zip(scores[0], positions[0]):
            if pos < 0:
                continue
            item = dict(chunks[int(pos)])
            item["vector_score"] = round(float(score), 4)
            item["vector_backend"] = "faiss"
            hits.append(item)
        return hits

    def _search_local(self, chunks: list[dict[str, Any]], query: str, *, limit: int) -> list[dict[str, Any]]:
        query_vector = hashed_embedding(query, self.dimensions)
        scored = []
        for item in chunks:
            score = dot(query_vector, hashed_embedding(str(item.get("content") or ""), self.dimensions))
            if score > 0:
                enriched = dict(item)
                enriched["vector_score"] = round(score, 4)
                enriched["vector_backend"] = "local"
                scored.append((score, enriched))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]


def hashed_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign * token_weight(token)
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]


def tokenize(text: str) -> list[str]:
    lower = (text or "").lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lower)
    tokens: list[str] = []
    for word in words:
        tokens.append(word)
        if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 2:
            tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
    return tokens


def token_weight(token: str) -> float:
    if len(token) <= 2:
        return 1.0
    return 1.0 + min(len(token), 12) / 12.0


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))

from __future__ import annotations

import csv
import math
import io
import re
import sqlite3
import uuid
from collections import Counter
from typing import Any

from app.db import row_to_dict


SUPPORTED_TEXT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/x-ndjson",
    "application/pdf",
}
MAX_KNOWLEDGE_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


class KnowledgeBase:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add_document(
        self,
        *,
        user_id: str,
        role: str,
        title: str,
        source_name: str,
        mime_type: str,
        content_bytes: bytes,
    ) -> dict[str, Any]:
        role = normalize_role(role)
        if len(content_bytes) > MAX_KNOWLEDGE_BYTES:
            raise ValueError("File must be under 5MB for this knowledge base.")
        text = extract_text(content_bytes=content_bytes, source_name=source_name, mime_type=mime_type)
        if not text.strip():
            raise ValueError("No readable text found in this file.")

        chunks = split_text(text)
        doc_id = uuid.uuid4().hex
        self.conn.execute(
            """
            INSERT INTO knowledge_documents
            (id, user_id, role, title, source_name, mime_type, char_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [doc_id, user_id, role, title.strip() or source_name, source_name, mime_type, len(text), len(chunks)],
        )
        self.conn.executemany(
            """
            INSERT INTO knowledge_chunks
            (id, document_id, role, chunk_index, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            [[uuid.uuid4().hex, doc_id, role, index, chunk] for index, chunk in enumerate(chunks)],
        )
        self.conn.commit()
        return self.get_document(doc_id, user_id=user_id) or {"id": doc_id}

    def list_documents(self, *, user_id: str, role: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM knowledge_documents
            WHERE user_id = ? AND role = ?
            ORDER BY created_at DESC
            """,
            [user_id, normalize_role(role)],
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get_document(self, document_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        params: list[Any] = [document_id]
        where = "id = ?"
        if user_id:
            where += " AND user_id = ?"
            params.append(user_id)
        row = self.conn.execute(f"SELECT * FROM knowledge_documents WHERE {where}", params).fetchone()
        return row_to_dict(row)

    def delete_document(self, *, document_id: str, user_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM knowledge_documents WHERE id = ? AND user_id = ?", [document_id, user_id])
        self.conn.commit()
        return cursor.rowcount > 0

    def search(self, *, role: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        query_terms = tokenize(query)
        query_vector = term_vector(query_terms)
        rows = self.conn.execute(
            """
            SELECT c.id, c.document_id, c.chunk_index, c.content, d.title, d.source_name, d.created_at
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.role = ?
            ORDER BY d.created_at DESC
            LIMIT 500
            """,
            [normalize_role(role)],
        ).fetchall()
        scored: list[tuple[float, dict[str, Any]]] = []
        chunk_vectors: list[tuple[dict[str, Any], Counter[str], str]] = []
        for row in rows:
            item = row_to_dict(row)
            content = str(item.get("content") or "")
            content_terms = tokenize(content)
            chunk_vectors.append((item, term_vector(content_terms), content))

        doc_freq = document_frequency([vector for _, vector, _ in chunk_vectors])
        total_docs = max(len(chunk_vectors), 1)
        for item, content_vector, content in chunk_vectors:
            score = score_text(
                content=content,
                query=query,
                query_terms=query_terms,
                query_vector=query_vector,
                content_vector=content_vector,
                doc_freq=doc_freq,
                total_docs=total_docs,
            )
            if score > 0:
                item["score"] = round(score, 4)
                item["snippet"] = make_snippet(content, query_terms)
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]


def normalize_role(role: str) -> str:
    if role not in {"user", "merchant"}:
        raise ValueError("role must be user or merchant")
    return role


def extract_text(*, content_bytes: bytes, source_name: str, mime_type: str) -> str:
    lowered = source_name.lower()
    if lowered.endswith(".pdf") or mime_type == "application/pdf":
        return pdf_to_text(content_bytes)
    if not (mime_type in SUPPORTED_TEXT_TYPES or lowered.endswith((".txt", ".md", ".csv", ".json", ".ndjson"))):
        raise ValueError("Only txt, md, csv, json, and pdf files are supported now.")

    text = decode_text(content_bytes)
    if lowered.endswith(".csv") or mime_type == "text/csv":
        return csv_to_text(text)
    return text


def decode_text(content_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content_bytes.decode("utf-8", errors="ignore")


def csv_to_text(text: str) -> str:
    reader = csv.DictReader(io.StringIO(text))
    lines: list[str] = []
    for index, row in enumerate(reader):
        if index >= 2000:
            lines.append("Rows truncated at 2000 for lightweight indexing.")
            break
        compact = " | ".join(f"{key}: {value}" for key, value in row.items() if value not in {None, ""})
        if compact:
            lines.append(compact)
    return "\n".join(lines) or text


def pdf_to_text(content_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing dependency is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(content_bytes))
    except Exception as exc:
        raise ValueError("PDF could not be opened.") from exc

    lines: list[str] = []
    for index, page in enumerate(reader.pages[:80]):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            lines.append(f"[Page {index + 1}]\n{page_text.strip()}")
    text = "\n\n".join(lines)
    if not text.strip():
        raise ValueError("No selectable text found in this PDF.")
    return text


def split_text(text: str) -> list[str]:
    clean = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(clean) <= CHUNK_SIZE:
        return [clean]
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + CHUNK_SIZE)
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return chunks


def tokenize(text: str) -> list[str]:
    lower = text.lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lower)
    tokens: list[str] = []
    for word in words:
        tokens.append(word)
        if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 2:
            tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
    return [token for token in tokens if token.strip()]


def term_vector(terms: list[str]) -> Counter[str]:
    return Counter(terms)


def document_frequency(vectors: list[Counter[str]]) -> Counter[str]:
    freq: Counter[str] = Counter()
    for vector in vectors:
        freq.update(vector.keys())
    return freq


def score_text(
    *,
    content: str,
    query: str,
    query_terms: list[str],
    query_vector: Counter[str],
    content_vector: Counter[str],
    doc_freq: Counter[str],
    total_docs: int,
) -> float:
    lower = content.lower()
    score = 0.0
    if query and query.lower() in lower:
        score += 4.0
    for term in query_terms:
        count = lower.count(term)
        if count:
            score += min(count, 5) * (1.0 if len(term) <= 2 else 1.4)
    score += 6.0 * tfidf_cosine(query_vector, content_vector, doc_freq, total_docs)
    return score


def tfidf_cosine(
    left: Counter[str],
    right: Counter[str],
    doc_freq: Counter[str],
    total_docs: int,
) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    if not shared:
        return 0.0

    def weight(term: str, count: int) -> float:
        idf = math.log((1 + total_docs) / (1 + doc_freq.get(term, 0))) + 1.0
        return (1.0 + math.log(count)) * idf

    numerator = sum(weight(term, left[term]) * weight(term, right[term]) for term in shared)
    left_norm = math.sqrt(sum(weight(term, count) ** 2 for term, count in left.items()))
    right_norm = math.sqrt(sum(weight(term, count) ** 2 for term, count in right.items()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def make_snippet(content: str, terms: list[str], size: int = 180) -> str:
    lower = content.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(0, min(positions) - 40) if positions else 0
    snippet = content[start : start + size].strip()
    if start:
        snippet = "..." + snippet
    if start + size < len(content):
        snippet += "..."
    return snippet

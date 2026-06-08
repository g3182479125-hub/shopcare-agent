from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PolicyHit:
    title: str
    content: str
    score: int

    def to_dict(self) -> dict:
        return {"title": self.title, "content": self.content, "score": self.score}


class PolicyRAG:
    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path or Path(__file__).resolve().parents[1] / "data" / "policies" / "aftersales_policy.md"
        self.sections = self._load_sections()

    def _load_sections(self) -> list[tuple[str, str]]:
        text = self.policy_path.read_text(encoding="utf-8")
        sections: list[tuple[str, str]] = []
        current_title = "总则"
        current_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines).strip()))
                current_title = line.replace("## ", "", 1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_title, "\n".join(current_lines).strip()))
        return sections

    def _tokens(self, text: str) -> set[str]:
        words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())
        extra = []
        for item in ["退款", "退货", "换货", "补发", "质量", "物流", "食品", "生鲜", "美妆", "过敏", "3C", "发票", "人工"]:
            if item.lower() in text.lower():
                extra.append(item.lower())
        return set(words + extra)

    def search(self, query: str, limit: int = 4) -> list[dict]:
        q = self._tokens(query)
        hits: list[PolicyHit] = []
        for title, content in self.sections:
            score = len(q & self._tokens(title + "\n" + content))
            if score > 0:
                hits.append(PolicyHit(title=title, content=content[:700], score=score))
        hits.sort(key=lambda item: item.score, reverse=True)
        return [hit.to_dict() for hit in hits[:limit]]

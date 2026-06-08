from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from typing import Deque


class ConversationMemory:
    def __init__(self, max_turns: int = 8) -> None:
        self.max_turns = max_turns
        self._items: dict[str, Deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=max_turns * 2))
        self._lock = Lock()

    def get(self, session_id: str | None) -> list[dict[str, str]]:
        if not session_id:
            return []
        with self._lock:
            return list(self._items.get(session_id, []))

    def append(self, session_id: str | None, *, role: str, content: str) -> None:
        if not session_id or not content.strip():
            return
        with self._lock:
            self._items[session_id].append({"role": role, "content": content.strip()[:1600]})


conversation_memory = ConversationMemory()

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class GraphInterrupt(Exception):
    def __init__(self, *, node: str, state: dict[str, Any], reason: str) -> None:
        super().__init__(reason)
        self.node = node
        self.state = state
        self.reason = reason


@dataclass
class GraphResult:
    status: str
    state: dict[str, Any]
    current_node: str
    trace: list[dict[str, Any]]


NodeHandler = Callable[[dict[str, Any]], dict[str, Any] | str | None]


class AgentStateGraph:
    def __init__(self, *, name: str) -> None:
        self.name = name
        self.nodes: dict[str, NodeHandler] = {}
        self.edges: dict[str, str] = {}
        self.start_node = "start"
        self.end_node = "end"

    def add_node(self, name: str, handler: NodeHandler) -> "AgentStateGraph":
        self.nodes[name] = handler
        if len(self.nodes) == 1:
            self.start_node = name
        return self

    def add_edge(self, source: str, target: str) -> "AgentStateGraph":
        self.edges[source] = target
        return self

    def run(self, state: dict[str, Any], *, start_at: str | None = None, max_steps: int = 24) -> GraphResult:
        current = start_at or self.start_node
        trace: list[dict[str, Any]] = []
        steps = 0
        while current != self.end_node:
            if steps >= max_steps:
                raise GraphInterrupt(node=current, state=state, reason="max_steps_exceeded")
            handler = self.nodes.get(current)
            if handler is None:
                raise GraphInterrupt(node=current, state=state, reason="missing_node")
            try:
                outcome = handler(state)
            except GraphInterrupt:
                raise
            except Exception as exc:
                state.setdefault("errors", []).append({"node": current, "error": str(exc)})
                raise GraphInterrupt(node=current, state=state, reason="node_error") from exc

            if isinstance(outcome, dict):
                state.update(outcome)
                next_node = self.edges.get(current, self.end_node)
            elif isinstance(outcome, str):
                next_node = outcome
            else:
                next_node = self.edges.get(current, self.end_node)
            trace.append({"node": current, "next": next_node})
            current = next_node
            steps += 1
        return GraphResult(status="completed", state=state, current_node=current, trace=trace)


def interrupt_if_missing(state: dict[str, Any], key: str, *, node: str, reason: str) -> None:
    if not state.get(key):
        raise GraphInterrupt(node=node, state=state, reason=reason)

"""ROUTE 阶段内核：静态 DAG 查表（node 空间）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteDecision:
    next_node_id: str | None
    next_agent_id: str | None
    reason: str


class AgentRouter:
    def route_next(
        self, current_node_id: str | None, topology: dict[str, Any]
    ) -> RouteDecision:
        nodes = topology.get("nodes", [])
        edges = topology.get("edges", [])

        if current_node_id is None:
            entry = self._find_entry_node(nodes, edges)
            if entry is None:
                return RouteDecision(None, None, "拓扑无入口节点，直接终结。")
            return RouteDecision(
                entry["id"],
                self._agent_id_of(entry),
                f"静态拓扑入口节点: {entry['id']}。",
            )

        for edge in edges:
            if edge.get("source") == current_node_id:
                target_id = edge.get("target")
                target = self._node_by_id(nodes, target_id)
                if target is None:
                    return RouteDecision(None, None, f"目标节点缺失: {target_id}。")
                return RouteDecision(
                    target_id,
                    self._agent_id_of(target),
                    f"静态拓扑流转至下一节点: {target_id}。",
                )

        return RouteDecision(None, None, "已到达叶子节点，准备结算。")

    @staticmethod
    def _find_entry_node(
        nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        targets = {edge.get("target") for edge in edges}
        for node in nodes:
            if node.get("id") not in targets:
                return node
        return None

    @staticmethod
    def _node_by_id(
        nodes: list[dict[str, Any]], node_id: str | None
    ) -> dict[str, Any] | None:
        for node in nodes:
            if node.get("id") == node_id:
                return node
        return None

    @staticmethod
    def _agent_id_of(node: dict[str, Any]) -> str | None:
        return node.get("data", {}).get("agent_id")

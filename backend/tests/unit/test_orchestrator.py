"""M6 Orchestrator 单元测试。"""

from app.orchestrator.router import AgentRouter


def _topology_double():
    return {
        "nodes": [
            {"id": "node-1", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000001"}},
            {"id": "node-2", "type": "agent", "data": {"agent_id": "aaaaaaaa-0000-0000-0000-000000000002"}},
        ],
        "edges": [
            {"id": "edge-1", "source": "node-1", "target": "node-2", "data": {"condition": "default"}},
        ],
    }


def test_router_entry_node():
    router = AgentRouter()

    decision = router.route_next(None, _topology_double())

    assert decision.next_node_id == "node-1"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000001"


def test_router_static_next_node():
    router = AgentRouter()

    decision = router.route_next("node-1", _topology_double())

    assert decision.next_node_id == "node-2"
    assert decision.next_agent_id == "aaaaaaaa-0000-0000-0000-000000000002"


def test_router_leaf_returns_none():
    router = AgentRouter()

    decision = router.route_next("node-2", _topology_double())

    assert decision.next_node_id is None
    assert decision.next_agent_id is None


def test_router_single_node_entry_then_leaf():
    topo = {
        "nodes": [{"id": "solo", "type": "agent", "data": {"agent_id": "bbbbbbbb-0000-0000-0000-000000000001"}}],
        "edges": [],
    }
    router = AgentRouter()

    entry = router.route_next(None, topo)
    leaf = router.route_next("solo", topo)

    assert entry.next_node_id == "solo"
    assert entry.next_agent_id == "bbbbbbbb-0000-0000-0000-000000000001"
    assert leaf.next_node_id is None
    assert leaf.next_agent_id is None

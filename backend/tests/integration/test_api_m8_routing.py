"""M8 路由注册守卫：确保 14 个端点全部挂载到 app。"""

from app.main import app

EXPECTED_PATHS = {
    ("/api/v1/agents", "POST"),
    ("/api/v1/agents", "GET"),
    ("/api/v1/agents/{agent_id}", "GET"),
    ("/api/v1/agents/{agent_id}", "PATCH"),
    ("/api/v1/agents/{agent_id}", "DELETE"),
    ("/api/v1/workflows", "POST"),
    ("/api/v1/workflows", "GET"),
    ("/api/v1/workflows/{workflow_id}", "GET"),
    ("/api/v1/workflows/{workflow_id}", "PATCH"),
    ("/api/v1/workflows/{workflow_id}", "DELETE"),
    ("/api/v1/workflows/{workflow_id}/execute", "POST"),
    ("/api/v1/executions", "GET"),
    ("/api/v1/executions/{execution_id}", "GET"),
    ("/api/v1/executions/{execution_id}/timeline", "GET"),
}


def test_all_m8_routes_registered() -> None:
    registered = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            for method in methods:
                registered.add((path, method))
    missing = EXPECTED_PATHS - registered
    assert not missing, f"未注册的 M8 端点: {missing}"

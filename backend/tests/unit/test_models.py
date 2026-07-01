from app.models.agent import Agent
from app.models.user import User


def _indexed_columns(model) -> set[tuple[str, ...]]:
    return {tuple(column.name for column in idx.columns) for idx in model.__table__.indexes}


def test_user_org_id_indexed() -> None:
    assert ("org_id",) in _indexed_columns(User)


def test_agent_fk_columns_indexed() -> None:
    indexed = _indexed_columns(Agent)
    assert ("org_id",) in indexed
    assert ("created_by",) in indexed


def test_workflow_table_shape() -> None:
    from app.models.workflow import Workflow

    cols = Workflow.__table__.columns
    assert cols["created_by"].foreign_keys
    assert ("created_by",) in _indexed_columns(Workflow)
    assert ("org_id",) in _indexed_columns(Workflow)
    assert cols["topology"].nullable is False
    assert {
        "id",
        "org_id",
        "created_by",
        "name",
        "description",
        "topology",
        "is_active",
        "created_at",
        "updated_at",
    } <= set(cols.keys())


def test_workflow_execution_table_shape() -> None:
    from app.models.execution import WorkflowExecution

    cols = WorkflowExecution.__table__.columns
    assert cols["workflow_id"].foreign_keys
    assert ("workflow_id",) in _indexed_columns(WorkflowExecution)
    assert cols["status"].nullable is False
    assert cols["input"].nullable is False
    assert cols["output"].nullable is True
    assert cols["started_at"].nullable is True
    assert cols["finished_at"].nullable is True
    assert {
        "id",
        "org_id",
        "workflow_id",
        "status",
        "input",
        "output",
        "error",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    } <= set(cols.keys())


def test_execution_event_is_append_only() -> None:
    from app.models.event import ExecutionEvent

    cols = ExecutionEvent.__table__.columns
    assert cols["execution_id"].foreign_keys
    assert ("execution_id",) in _indexed_columns(ExecutionEvent)
    assert "created_at" in cols
    assert "updated_at" not in cols
    assert cols["protocol_stage"].nullable is False
    assert {
        "id",
        "execution_id",
        "protocol_stage",
        "event_type",
        "payload",
        "created_at",
    } == set(cols.keys())


def test_all_tables_registered_on_metadata() -> None:
    from app.models import Base

    assert {
        "users",
        "agents",
        "workflows",
        "workflow_executions",
        "execution_events",
    } <= set(Base.metadata.tables.keys())

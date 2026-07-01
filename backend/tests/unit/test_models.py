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

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

"""add updated_at triggers and foreign key indexes

Revision ID: 8f1c2a4b6d7e
Revises: 402d30448736
Create Date: 2026-06-30 23:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f1c2a4b6d7e"
down_revision: str | None = "402d30448736"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ─── 自包含：迁移内定义触发器函数 ─────────────────────
# init.sql 仅在容器首次初始化时执行，非容器环境（本地虚拟环境、CI）
# 需要迁移自行保证该函数存在，因此在此重复定义（幂等 CREATE OR REPLACE）。
_CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_TABLES_WITH_TIMESTAMP = ("users", "agents")


def upgrade() -> None:
    op.execute(_CREATE_FUNCTION)

    # updated_at 自动更新触发器
    for table in _TABLES_WITH_TIMESTAMP:
        op.execute(
            f"CREATE TRIGGER set_timestamp_{table} "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();"
        )

    # 外键 / 多租户字段索引（设计文档 Section 8.4）
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_agents_org_id", "agents", ["org_id"])
    op.create_index("ix_agents_created_by", "agents", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_agents_created_by", table_name="agents")
    op.drop_index("ix_agents_org_id", table_name="agents")
    op.drop_index("ix_users_org_id", table_name="users")

    for table in _TABLES_WITH_TIMESTAMP:
        op.execute(f"DROP TRIGGER IF EXISTS set_timestamp_{table} ON {table};")

    # 函数为共享资源，保留（其他表可能依赖），仅移除触发器与索引。

# NexusMesh — Phase 1 实施计划

**阶段**：Phase 1 — 基础设施 & 工程骨架
**时间**：Day 1–12
**目标**：从零构建可运行的完整工程脚手架，确保 `docker-compose up -d` 后后端服务健康运行，数据库迁移通过，Auth API 可调用。

---

## 交付标准（Definition of Done）

- [ ] `docker-compose up -d` 一键启动，backend / postgres / redis 全部 healthy
- [ ] `GET /health` 返回 200
- [ ] `POST /api/v1/auth/register` + `POST /api/v1/auth/login` 可用
- [ ] Alembic 迁移：`users` + `agents` 表创建成功
- [ ] `.env.example` 覆盖所有环境变量
- [ ] `README.md` 包含本地启动指南
- [ ] Gitee CI 模板存在（`.gitee/workflows/ci.yml`）
- [ ] ruff + pytest 配置完毕，`uv run pytest` 可执行

---

## 任务分解

### Sprint 1（Day 1–4）：Monorepo 骨架 + Docker 环境

#### Task 1.1 — 初始化目录结构
```
创建以下目录（空 __init__.py 占位）：
backend/app/{api/v1, common, config, core, db, models, schemas,
             orchestrator, protocol, state_manager, services, websocket}
backend/{migrations/versions, tests/{unit,integration}}
frontend/src/{api, components/{ui,layout}, features/{canvas,logs,timeline,panel},
              hooks, stores, types, pages}
docker/{postgres, redis, minio, nginx}
docs/{architecture, protocol, api, development}
scripts/
.gitee/workflows/
```

#### Task 1.2 — Git 初始化 + .gitignore
```
git init
添加 .gitignore：
  - .env
  - __pycache__/
  - .venv/
  - node_modules/
  - dist/
  - .DS_Store
  - *.pyc
  - .pytest_cache/
  - .ruff_cache/
```

#### Task 1.3 — docker-compose.yml（基础配置）
内容参见设计文档 Section 7，包含：
- backend（依赖 postgres + redis healthcheck）
- postgres:17-alpine + healthcheck
- redis:7.4-alpine + healthcheck
- nexusmesh-network
- postgres_data / redis_data 卷

#### Task 1.4 — docker-compose.override.yml（开发叠加）
- backend 挂载 `./backend:/app` + `--reload`
- postgres 暴露 5432
- redis 暴露 6379

#### Task 1.5 — docker/postgres/init.sql
```sql
-- 创建 trigger_set_timestamp() 函数
-- 创建 pgcrypto 扩展（gen_random_uuid()）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

#### Task 1.6 — docker/redis/redis.conf
```
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
```

---

### Sprint 2（Day 5–8）：后端工程初始化

#### Task 2.1 — backend/pyproject.toml
```toml
[project]
name = "nexusmesh-backend"
version = "0.1.0"
requires-python = ">=3.13"

dependencies = [
  "fastapi==0.115.*",
  "uvicorn[standard]==0.34.*",
  "pydantic==2.10.*",
  "pydantic-settings==2.*",
  "sqlalchemy==2.0.*",
  "alembic==1.14.*",
  "asyncpg==0.30.*",
  "redis==5.*",
  "litellm==1.50.*",   # ⚠️ 精确版本，CI拉取时不可升级
  "PyJWT[crypto]==2.10.*",
  "bcrypt==4.2.*",
  "httpx==0.28.*",
]

[project.optional-dependencies]
dev = [
  "pytest==8.*",
  "pytest-asyncio==0.24.*",
  "ruff==0.8.*",
  "httpx",  # 用于 TestClient
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
line-length = 88
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

#### Task 2.2 — backend/app/config/settings.py
实现 Pydantic BaseSettings（参见设计文档 Section 9）：
- `AppSettings` 类，含所有环境变量
- `@computed_field` 动态拼接 DATABASE_URL / REDIS_URL
- `Field(min_length=32)` 保护 SECRET_KEY / JWT_SECRET_KEY
- `CORS_ORIGINS` field_validator
- 底部单例：`settings = AppSettings()`

#### Task 2.3 — backend/app/db/session.py
```python
# AsyncSession 工厂
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config.settings import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.APP_DEBUG)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

#### Task 2.4 — backend/app/models/（SQLAlchemy ORM）
创建以下模型（参见设计文档 Section 8）：
- `base.py`：`Base = DeclarativeBase()`
- `user.py`：User 模型（id, org_id, email, username, hashed_password, role, is_active, timestamps）
- `agent.py`：Agent 模型（id, org_id, created_by FK, name, agent_type, llm_provider, llm_model, system_prompt, config JSONB, timestamps）

#### Task 2.5 — backend/migrations/ 初始化
```bash
uv run alembic init migrations
# 修改 migrations/env.py：
#   - 导入 Base from app.models.base
#   - 设置 target_metadata = Base.metadata
#   - 使用 asyncpg 异步驱动
uv run alembic revision --autogenerate -m "init users agents"
uv run alembic upgrade head
```

#### Task 2.6 — backend/app/core/security.py（JWT）
```python
# PyJWT 实现：
# - create_access_token(data: dict) -> str
# - create_refresh_token(data: dict) -> str
# - verify_token(token: str) -> dict
# 使用 settings.JWT_SECRET_KEY + settings.JWT_ALGORITHM
```

#### Task 2.7 — backend/app/core/auth.py（RBAC）
```python
# 角色枚举：admin / developer / viewer
# 依赖注入：
# - get_current_user(token: str, db: AsyncSession) -> User
# - require_role(roles: list[str]) → Depends(...)
```

---

### Sprint 3（Day 9–11）：API 端点 + 前端骨架

#### Task 3.1 — backend/app/api/v1/auth.py
```
POST /api/v1/auth/register   → 注册新用户
POST /api/v1/auth/login      → 登录，返回 access_token + refresh_token
POST /api/v1/auth/refresh    → 刷新 token
GET  /api/v1/auth/me         → 获取当前用户信息（需认证）
```

#### Task 3.2 — backend/app/main.py
```python
app = FastAPI(title="NexusMesh API", version="0.1.0")
# 中间件：CORS（settings.CORS_ORIGINS）
# 路由：include_router(auth_router, prefix=settings.API_V1_PREFIX)
# 健康检查：GET /health → {"status": "ok", "version": "0.1.0"}
# 启动事件：验证 Redis 连接、DB 连接
```

#### Task 3.3 — backend/Dockerfile
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync --no-dev
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Task 3.4 — 前端骨架初始化（本地）
```bash
cd frontend
pnpm create vite . --template react-ts
pnpm install
pnpm add @tanstack/react-query@5 react-router zustand@5
pnpm add -D @biomejs/biome tailwindcss@4
# 配置 Biome：biome.json
# 配置 TailwindCSS v4（CSS @theme）
```

#### Task 3.5 — 前端基础页面
```
src/pages/Login.tsx        — 登录表单（调用 POST /api/v1/auth/login）
src/pages/Dashboard.tsx    — 空壳页（认证后跳转）
src/api/http.ts            — axios 实例配置（baseURL, interceptors）
src/stores/sessionStore.ts — Zustand：存储 token + 用户信息
```

---

### Sprint 4（Day 12）：规范 + CI/CD 模板

#### Task 4.1 — .env.example（完整模板）
覆盖设计文档 Section 9.2 所有变量组。

#### Task 4.2 — .gitee/workflows/ci.yml（CI 模板）
```yaml
name: CI

on: [push, pull_request]

jobs:
  backend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install uv && uv sync
      - run: uv run ruff check backend/

  backend-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env: { POSTGRES_PASSWORD: test }
        options: --health-cmd pg_isready
      redis:
        image: redis:7.4-alpine
        options: --health-cmd "redis-cli ping"
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync
      - run: uv run pytest backend/tests/ -v

  frontend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - run: pnpm install --frozen-lockfile
      - run: pnpm biome check frontend/src/
```

#### Task 4.3 — README.md（初稿）
包含：
- 项目简介（中英文）
- 技术栈一览
- 本地启动步骤（`cp .env.example .env` → 填值 → `docker-compose up -d`）
- 前端启动步骤（`cd frontend && pnpm install && pnpm dev`）
- 目录结构说明
- 开发贡献规范链接（→ CONTRIBUTING.md）

#### Task 4.4 — scripts/
```bash
# start.sh
docker compose up -d

# stop.sh
docker compose down

# db-migrate.sh
docker compose exec backend uv run alembic upgrade head

# db-reset.sh（开发用）
docker compose down -v && docker compose up -d
```

#### Task 4.5 — backend/tests/unit/test_auth.py（基础测试）
```python
# 测试：
# - JWT token 创建与验证
# - bcrypt 密码哈希与校验
# - settings 配置加载（使用 test.env）
```

---

## 执行顺序

```
Day 1:   Task 1.1（目录结构）→ Task 1.2（.gitignore）
Day 2:   Task 1.3（docker-compose.yml）→ Task 1.4（override）→ Task 1.5（init.sql）→ Task 1.6（redis.conf）
Day 3:   Task 2.1（pyproject.toml）→ Task 2.2（settings.py）→ Task 2.3（db/session.py）
Day 4:   Task 2.4（models）→ Task 2.5（alembic 初始化 + 第一次迁移）
Day 5:   Task 2.6（security.py）→ Task 2.7（auth.py RBAC）
Day 6–7: Task 3.1（auth 端点）→ Task 3.2（main.py）→ Task 3.3（Dockerfile）
Day 8:   验证：docker-compose up -d → GET /health → POST /auth/login 测试通过
Day 9:   Task 3.4（前端 pnpm 初始化）
Day 10:  Task 3.5（Login + Dashboard + http.ts + sessionStore）
Day 11:  Task 4.1（.env.example）→ Task 4.2（CI 模板）→ Task 4.3（README）
Day 12:  Task 4.4（scripts）→ Task 4.5（基础测试）→ 全链路验证 + Phase 1 DoD 检查
```

---

## 风险 & 注意事项

| 风险 | 缓解措施 |
|------|---------|
| Python 3.13 + asyncpg C 扩展不兼容 | 预备降级至 3.12.x 的 Dockerfile |
| LiteLLM API 版本变更 | Phase 1 不调用 LiteLLM，仅安装，版本已精确锁定 |
| Alembic async 配置复杂 | 参考官方 `run_migrations_online` async 示例 |
| Tailwind v4 CSS-first 配置学习曲线 | Day 9 前先阅读 v4 migration guide |

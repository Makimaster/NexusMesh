# NexusMesh

NexusMesh 是一个面向多智能体协作的模块化单体平台，目标是把调度、协议、状态管理和可观测界面放在同一个可本地部署的工程里。

## Tech Stack

- Backend: FastAPI, SQLAlchemy Async, Alembic, PostgreSQL, Redis
- Frontend: React 19, Vite 6, TanStack Query, Zustand
- Tooling: uv, Ruff, Docker Compose, pnpm, Biome

## Quick Start

1. 复制环境变量模板

```powershell
Copy-Item .env.example .env
```

2. 启动基础服务

```powershell
docker compose up -d
```

3. 运行后端测试

```powershell
cd backend
uv sync --extra dev
uv run pytest tests -q
```

4. 启动前端开发环境

```powershell
corepack enable
corepack prepare pnpm@9.15.0 --activate
pnpm -C frontend install
pnpm -C frontend dev
```

## Project Structure

```text
backend/   FastAPI app, models, auth, migrations, tests
frontend/  React SPA shell for dashboard and login
docker/    PostgreSQL and Redis bootstrap files
scripts/   Local helper scripts for start, stop and migration
```

## Development Notes

- `.claude/` 只用于本地协作上下文，不进入 Git
- Phase 1 当前目标是打通工程骨架、认证接口和基础测试链路
- 贡献说明后续补充到 `CONTRIBUTING.md`

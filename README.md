# NexusMesh（织网）

NexusMesh 是一个面向多智能体协作的模块化单体（Modular Monolith）平台，将调度引擎、通信协议、状态管理与可视化监控界面整合在同一个可本地部署的工程中。项目目标是让多 Agent 的协作过程可视化、流式数据传输低延迟、协作调度全程可观测。

## 技术栈

- 后端：FastAPI、SQLAlchemy（全异步）、Alembic、PostgreSQL、Redis
- 前端：React 19、Vite 6、TanStack Query、Zustand
- 工程工具：uv、Ruff、Docker Compose、pnpm、Biome

## 目录结构

```text
NexusMesh/
├── backend/            FastAPI 应用：模型、认证、数据库迁移与测试
├── frontend/           React 单页应用：仪表盘与登录页壳层
├── docker/             PostgreSQL 与 Redis 的初始化配置
├── scripts/            本地辅助脚本（启动、停止、迁移、重置）
├── docs/               项目文档：架构、协议、API、开发指南与设计文档
└── docker-compose.yml  服务编排（backend / postgres / redis）
```

## 快速开始

### 方式一：Docker 一键启动（推荐用于部署验证）

后端与数据库全部在容器内运行，容器间通过服务名互访。适合验证「使用者拿到代码后一键部署」这条路径。

```bash
cp .env.example .env             # 复制环境变量模板，按需填入密钥
docker compose up -d --build     # 构建镜像并启动 backend + postgres + redis
                                 # 依赖变更后同样用 --build 重构容器
docker compose exec backend uv run alembic upgrade head   # 在容器内执行数据库迁移
# 启动完成后访问 http://localhost:8000/health
```

### 方式二：本地开发（推荐用于日常开发）

后端跑在本地 `.venv`，Docker 仅托管 PostgreSQL 与 Redis 依赖。`.env` 中的 `POSTGRES_HOST` / `REDIS_HOST` 默认即为 `localhost`，无需修改。

#### 首次搭建（只做一次）

```bash
# 1. 准备环境变量：复制模板为 .env，按需填入密钥
cp .env.example .env

# 2. 安装后端依赖到本地 .venv（--extra dev 连同 pytest / ruff 一起装）
#    仅在首次或依赖变更后需要执行
cd backend
uv sync --extra dev

# 3. 初始化数据库表结构（需 postgres 已在运行，见下方「日常启动」第 1 步）
#    仅在首次或有新迁移时需要执行
uv run alembic upgrade head

# 4. 安装前端依赖：corepack 用于激活指定版本的 pnpm（避免全局安装）
corepack enable
corepack prepare pnpm@9.15.0 --activate
pnpm -C frontend install
```

#### 日常启动（每次开发）

```bash
# 1. 只用 Docker 起依赖服务（不启动 backend 容器）
docker compose up -d postgres redis

# 2. 启动后端（--reload 热重载，改代码自动重启）
cd backend
uv run uvicorn app.main:app --reload --port 8000

# 3. 启动前端（-C frontend 表示在 frontend 目录内执行，无需先 cd）
pnpm -C frontend dev            # 访问 http://localhost:5173
```

> 冒烟测试：`cd backend && uv run pytest tests -q`


## 开发说明

- 两种模式共用一份 `.env`：`.env` 里 HOST 写 `localhost` 供本地开发；Docker 完整启动时由 `docker-compose.yml` 的 `environment` 覆盖为服务名 `postgres` / `redis`。
- 数据库迁移由 Alembic 管理，`updated_at` 字段通过数据库触发器 `trigger_set_timestamp()` 自动维护。
- `.claude/` 仅用于本地协作上下文，不纳入版本控制。
- Phase 1 当前目标是打通工程骨架、认证接口与基础测试链路。
- 贡献规范详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

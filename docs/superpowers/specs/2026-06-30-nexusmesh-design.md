# NexusMesh — 系统架构设计文档

**版本**：1.0.0
**日期**：2026-06-30
**状态**：已确认，待实现
**开发周期**：60 天（独立全栈）

---

## 目录

1. [项目概述](#1-项目概述)
2. [背景与痛点分析](#2-背景与痛点分析)
3. [架构决策记录（ADR）](#3-架构决策记录adr)
4. [技术选型清单](#4-技术选型清单)
5. [系统总体架构](#5-系统总体架构)
6. [Monorepo 目录结构](#6-monorepo-目录结构)
7. [Docker 基础设施设计](#7-docker-基础设施设计)
8. [数据库设计](#8-数据库设计)
9. [配置管理](#9-配置管理)
10. [开发阶段计划](#10-开发阶段计划)
11. [已知局限性与技术债规划](#11-已知局限性与技术债规划)

---

## 1. 项目概述

| 字段 | 内容 |
|------|------|
| 项目名称 | **NexusMesh（织网）** |
| 英文全称 | Nexus Multi-Agent Collaboration Platform |
| 中文全称 | Nexus 多智能体协作管理平台 |
| 方向 | AI Infrastructure（AI 基础设施）|
| 核心定位 | 多 Agent 调度引擎 + 可视化管理平台 |
| Gitee 地址 | https://gitee.com/xiaofeng-markos |

### 项目目标

> 定义一套标准化的多智能体协作流式通信协议，并提供图形化监控看板，
> 使得多 Agent 协作过程可视化、流式数据传输低延迟、协作调度可观测。

---

## 2. 背景与痛点分析

### 市面上现有框架的问题

| 痛点 | NexusMesh 解决方案 |
|------|-------------------|
| 私有化部署门槛高 | Docker Compose 一键启动，零云依赖 |
| 通信协议不统一 | 自研五阶段协议（`protocol/` 模块），JSON Schema 强校验 |
| 系统调试困难 | React Flow 实时拓扑 + Timeline 执行链路回溯 |
| 实时流式输出缺失 | FastAPI WebSocket + Redis Pub/Sub 全推送链路 |
| 前后台集成复杂度高 | FastAPI 统一 API Gateway + OpenAPI 规范自动生成文档 |

---

## 3. 架构决策记录（ADR）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Agent 框架 | 自研（DeepAgents = NexusMesh 核心产出） | 完全控制生命周期与协议 |
| LLM 调用层 | LiteLLM 多厂商统一接口 | 避免单厂商锁定，一套代码支持多模型 |
| 认证方案 | JWT + RBAC（admin/developer/viewer）| 无状态、无第三方依赖、够用 |
| MinIO | Phase 3 加入，Phase 1 预留注释配置 | YAGNI，Phase 1 无文件存储需求 |
| 多租户 | 单租户 + 预留 `org_id` 字段 | 低成本预留，避免后期大规模迁移 |
| 整体架构 | **模块化单体（Modular Monolith）** | 最适合 60 天独立全栈，边界清晰，可后续拆分 |
| 包管理（后端）| uv | 秒级安装，Python 3.13 多版本管理支持好 |
| 代码规范（后端）| ruff | 替代 black+flake8+isort，统一极速 |
| 代码规范（前端）| Biome | 替代 ESLint+Prettier，与 ruff 同哲学 |
| 前端路由 | React Router 7 Library Mode（SPA）| 内部仪表盘，无 SSR 需求 |
| HTTP 状态管理 | TanStack Query v5 | 配合 React 19 Action 机制，服务端状态分离 |

---

## 4. 技术选型清单

### 4.1 后端

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | `3.13.x`（备选 `3.12.x`）| 若遇 C 扩展不兼容降至 3.12 |
| FastAPI | `0.115.x` | ASGI 框架 |
| Pydantic | `2.10.x` | Rust 核心，v2 系列 |
| pydantic-settings | `2.x` | Pydantic v2 独立配置库 |
| SQLAlchemy | `2.0.x` | 全异步 ORM |
| Alembic | `1.14.x` | 数据库迁移 |
| uvicorn | `0.34.x` | ASGI 服务器 |
| asyncpg | `0.30.x` | PostgreSQL 异步驱动 |
| redis-py | `5.x` | 官方合并版，原生异步 |
| LiteLLM | `==1.50.x`（精确锁定）| ⚠️ 禁止用 `>=`，API 变更频繁 |
| PyJWT | `2.10.x` | JWT 签发/验证（替代已废弃 python-jose）|
| bcrypt | `4.2.x` | 密码哈希（替代 passlib，直接调用原生 API）|
| httpx | `0.28.x` | 异步 HTTP 客户端 |
| pytest | `8.x` | 测试框架 |
| pytest-asyncio | `0.24.x` | `asyncio_mode = auto` |
| ruff | `0.8.x` | Linter + Formatter |
| uv | latest | 包管理工具 |

### 4.2 前端

| 依赖 | 版本 | 说明 |
|------|------|------|
| Node.js | `22.13+ LTS` | 前端测试栈（`jsdom@29`）要求 `^22.13.0` |
| pnpm | `9.x` | 禁止 npm/yarn 混用 |
| React | `19.x` | ⚠️ 引入第三方库须验证 React 19 兼容性 |
| Vite | `6.x` | Library Mode SPA |
| TypeScript | `5.x` | — |
| TailwindCSS | `4.x` | ⚠️ 废弃 `tailwind.config.js`，改为 CSS `@theme` 配置 |
| @xyflow/react | `12.x` | ⚠️ 原 `reactflow` 包名已迁移 |
| Zustand | `5.x` | ⚠️ 具名导出：`import { create } from 'zustand'` |
| React Router | `7.x` | Library Mode，包名 `react-router` |
| TanStack Query | `5.x` | REST 服务端状态管理 |
| Biome | `1.9.x+` | 替代 ESLint + Prettier |

### 4.3 基础设施

| 组件 | 版本 | 说明 |
|------|------|------|
| PostgreSQL | `17.x` | — |
| Redis | `7.4.x LTS` | ⚠️ 8.x 协议变更为 RSALv2+SSPLv1，不选 |
| MinIO | `RELEASE.2025-xx`（精确 Tag）| ⚠️ 禁止 `:latest` |
| Docker Engine | `29.x` | 27.x 已 EOL |
| Docker Compose | `2.31.x+` | 统一用 `docker compose`（无连字符）|
| Nginx | `1.26.x stable` | 偶数版本 = stable |

---

## 5. 系统总体架构

### 5.1 架构模式

**模块化单体（Modular Monolith）**：单个 FastAPI 进程，清晰内部模块边界，
通过 Python 函数调用通信，无网络序列化开销。

### 5.2 模块依赖方向（单向，严禁反向）

```
api/          → orchestrator/   → state_manager/ → common/
api/          → services/       → models/
api/          → websocket/      → common/
orchestrator/ → protocol/       → common/
```
<!-- 箭头方向表示「依赖于」。严禁反向依赖。 -->

### 5.3 核心数据流

```
用户触发任务
  → REST API 接收（api/v1/）
  → Coordinator 创建 Workflow 执行实例
  → Scheduler 分配 Agent
  → 五阶段协议：INIT → RECEIVE → ROUTE → EXECUTE → FINISH
  → state_manager 写入 Redis（实时热数据）+ PostgreSQL（持久化）
  → WebSocket broadcaster 推送事件给前端
  → 前端 React Flow 实时渲染拓扑 + LogStream
```

### 5.4 五阶段通信协议

NexusMesh 最核心的差异化设计。所有 Agent 间通信必须经过 `protocol/` 模块封包：

| 阶段 | 名称 | 说明 |
|------|------|------|
| 1 | `INIT` | 初始化，建立 Agent 上下文 |
| 2 | `RECEIVE` | 任务接收，解析输入 Payload |
| 3 | `ROUTE` | 多跳路由，决定下一个 Agent |
| 4 | `EXECUTE` | 执行，调用 LLM，产出 Token 流 |
| 5 | `FINISH` | 结果返回，写入执行记录 |

**标准事件类型**：`agent_spawn` / `agent_call` / `agent_finish` / `agent_reflect`

### 5.5 WebSocket 事件流

```
LiteLLM Token → orchestrator → protocol 封包
  → Redis Pub/Sub（channel: execution:{id}）
  → websocket/broadcaster.py 订阅
  → WebSocket 推送前端
  → LogStream + AgentCanvas 实时更新
```

---

## 6. Monorepo 目录结构

```
NexusMesh/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST 路由（agents, workflows, auth）
│   │   ├── common/          # redis_client, logger, middleware, utils
│   │   ├── config/          # settings.py（Pydantic BaseSettings）
│   │   ├── core/            # security.py（JWT）, auth.py（RBAC）, exceptions.py
│   │   ├── db/              # session.py（AsyncSession 工厂）
│   │   ├── models/          # SQLAlchemy ORM（user, agent, workflow, execution）
│   │   ├── schemas/         # Pydantic API Schema（请求/响应）
│   │   ├── orchestrator/    # DeepAgents 核心（coordinator, scheduler, router, base_agent）
│   │   ├── protocol/        # 五阶段协议（stages, events, serializer, schemas/）
│   │   ├── state_manager/   # Redis 状态机（context, session, task_state）
│   │   ├── services/        # 业务逻辑（agent_service, workflow_service, llm_service）
│   │   ├── websocket/       # WS 网关（gateway, handlers, broadcaster）
│   │   └── main.py
│   ├── migrations/          # Alembic（versions/, env.py）
│   ├── tests/               # unit/, integration/, conftest.py
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── .dockerignore
│
├── frontend/
│   ├── src/
│   │   ├── api/             # http.ts, ws.ts
│   │   ├── components/      # ui/, layout/
│   │   ├── features/        # canvas/, logs/, timeline/, panel/
│   │   ├── hooks/           # useWebSocket.ts, useAgentStream.ts
│   │   ├── stores/          # agentStore.ts, sessionStore.ts（Zustand）
│   │   ├── types/           # protocol.ts（与后端协议对齐）
│   │   ├── pages/           # Dashboard, WorkflowEditor, Login
│   │   └── main.tsx
│   ├── vite.config.ts
│   ├── tailwind.config.css  # v4 CSS-first 配置
│   └── package.json
│
├── docker/
│   ├── postgres/init.sql
│   ├── redis/redis.conf
│   ├── minio/               # Phase 3 预留
│   └── nginx/               # 后期预留
│
├── docs/superpowers/specs/  # 本文档所在
├── scripts/                 # start.sh, stop.sh, db-migrate.sh, db-reset.sh
├── .gitee/workflows/ci.yml
├── .env.example
├── .env                     # ⚠️ 加入 .gitignore，永远不提交
├── docker-compose.yml
├── docker-compose.override.yml
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

---

## 7. Docker 基础设施设计

### 7.1 服务拓扑

所有服务在同一私有网络 `nexusmesh-network`，容器间通过服务名互访。
**PostgreSQL / Redis 端口不对外暴露**（开发 override 中开放）。

| 服务 | 镜像 | 对外端口 |
|------|------|---------|
| backend | nexusmesh-backend:latest | 8000 |
| postgres | postgres:17-alpine | 仅内网（开发 override: 5432）|
| redis | redis:7.4-alpine | 仅内网（开发 override: 6379）|
| minio | RELEASE.2025-xx | Phase 3 启用 |

### 7.2 关键设计

- `docker-compose.yml`：基础配置（镜像、网络、卷）
- `docker-compose.override.yml`：本地开发叠加（源码挂载 + 热重载 + 端口暴露）
- `healthcheck` 确保 backend 在 postgres/redis 健康后启动（`depends_on.condition: service_healthy`）
- 数据卷：`postgres_data`、`redis_data` 均使用 `driver: local` 持久化

---

## 8. 数据库设计

### 8.1 核心原则

- UUID 主键，避免 ID 枚举攻击
- `org_id` 预留多租户字段（Phase 1 为 NULL）
- `updated_at` 由数据库触发器 `trigger_set_timestamp()` 自动维护
- 执行事件表（`execution_events`）**仅追加，无 updated_at**
- 外键删除策略统一用 `ON DELETE SET NULL`（保留业务数据）

### 8.2 表结构概览

| 表名 | 用途 |
|------|------|
| `users` | 用户账号 + RBAC 角色 |
| `agents` | Agent 配置（非运行时状态）|
| `workflows` | 工作流定义 + React Flow 拓扑快照 |
| `workflow_executions` | 单次执行实例（状态、输入、输出）|
| `execution_events` | 五阶段协议事件流（可观测性核心数据源）|

### 8.3 execution_events payload 规范

```json
{
  "protocol_stage": "EXECUTE",
  "agent_message": "...",
  "prompt_tokens": 512,
  "completion_tokens": 128,
  "model": "gpt-4o",
  "model_cost_usd": 0.0032
}
```

Token 审计与成本看板均从此字段提取。

### 8.4 关键索引策略

- 外键字段全部建索引（`created_by`、`org_id`、`workflow_id`、`execution_id`）
- `workflow_executions.status` 使用**部分索引**：`WHERE status IN ('pending', 'running')`
- `execution_events.created_at DESC` 索引支持时间线倒序查询

---

## 9. 配置管理

### 9.1 Pydantic BaseSettings

- 依赖：`pydantic-settings 2.x`（独立包，需显式安装）
- `DATABASE_URL` / `REDIS_URL` 通过 `@computed_field` 动态拼接
- `SECRET_KEY` / `JWT_SECRET_KEY` 通过 `Field(min_length=32)` 强制校验（Fail-Fast）
- `CORS_ORIGINS` 支持逗号分隔字符串，`field_validator` 自动解析为 `List[str]`

### 9.2 环境变量分组

| 分组 | 关键变量 |
|------|---------|
| 应用 | `APP_ENV`, `SECRET_KEY`, `LOG_LEVEL` |
| 数据库 | `POSTGRES_*`, `DATABASE_URL`（computed）|
| Redis | `REDIS_*`, `REDIS_URL`（computed）|
| JWT | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` |
| LLM | `LITELLM_API_BASE`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEFAULT_LLM_MODEL` |
| CORS | `CORS_ORIGINS`（支持逗号分隔，覆盖 Vite 5173/4173 端口）|

### 9.3 安全规则

- `.env` 永远加入 `.gitignore`，**禁止提交真实密钥**
- `.env.example` 提交到仓库，包含所有 key，value 为空或示例值
- LiteLLM 版本必须精确锁定：`litellm==1.50.x`

---

## 10. 开发阶段计划

| 阶段 | 时间 | 核心交付物 |
|------|------|-----------|
| **Phase 1** | Day 1–12 | Monorepo 初始化、Docker 环境、DB 迁移、JWT Auth、API 骨架 |
| **Phase 2** | Day 13–24 | 五阶段协议实现、WebSocket 网关、Redis 状态机 |
| **Phase 3** | Day 25–38 | Orchestrator（Coordinator+Scheduler+Router）、LiteLLM 集成、MinIO |
| **Phase 4** | Day 39–50 | React 前端（React Flow 拓扑、LogStream、Timeline、NodePanel）|
| **Phase 5** | Day 51–60 | E2E 集成测试、压测优化、Prometheus/Grafana 基础监控、文档收尾 |

---

## 11. 已知局限性与技术债规划

| 类别 | 局限性 | 规划时机 |
|------|--------|---------|
| 测试覆盖率 | 目标 35–50%，企业标准 80%+ | Phase 5 后持续补充 |
| 安全加固 | 基础 JWT+RBAC，无 OWASP 审计、限流 | Phase 5 后 |
| WebSocket 高并发 | 单实例正常，多实例 WS 需 Redis Adapter | 需求驱动时实现 |
| 多租户 | `org_id` 预留，行级隔离未实现 | 商业化阶段 |
| 前端 UX | 核心功能跑通，动画/空状态/错误态不完整 | 迭代打磨 |
| Prometheus/Grafana | Phase 5 基础搭建，指标不精调 | 持续运营阶段 |
| 协议形式化规范 | 代码注释级别，无 RFC 文档 | 开源推广前 |
| LiteLLM 厂商覆盖 | 接通 2–3 个主流 Provider | 按需扩展 |

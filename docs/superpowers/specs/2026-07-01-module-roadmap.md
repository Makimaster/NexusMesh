# NexusMesh — 模块实施路线图（Phase 2–5）

**版本**：1.0.0
**日期**：2026-07-01
**状态**：已确认，待逐模块细化
**上游文档**：[系统架构设计](./2026-06-30-nexusmesh-design.md)

---

## 1. 文档定位

本文档是 [系统架构设计文档](./2026-06-30-nexusmesh-design.md) 的**执行侧延伸**，不重复其内容。

| 文档 | 回答的问题 |
|------|-----------|
| 系统架构设计 | 用什么架构、什么技术栈、协议长什么样、数据库怎么设计 |
| **本路线图** | 剩余工作切成哪些模块、以什么顺序建、每个模块的边界与完成标准 |
| 各模块详细计划 | 单个模块内部的具体任务、函数签名、schema、逐步验证项 |

Phase 1（工程骨架、认证、基础设施）已完成。本路线图覆盖 **Phase 2–5**，将剩余工作切分为 **16 个可独立交付的模块**。

---

## 2. 循环工作流

本路线图是稳定的顶层地图；具体实现按模块逐个推进，形成闭环：

```
模块路线图（本文档，稳定不常改）
  │
  └─→ 取下一个待开工模块
        └─→ 编写该模块的详细执行计划（docs/superpowers/plans/）
              └─→ 交由 codex + subagent 按计划编码
                    └─→ 编码完成 + 验证通过 + 即时中文 Git 提交
                          └─→ 回到路线图，取下一个模块，产出新计划
```

- 一个模块 = 一次 codex 任务，粒度控制在单次可完成、可验证的范围。
- 每个模块完成后**立即中文提交**（遵循 MEMORY.md 协作规范），描述需追溯改动目的。
- 详细计划文件命名：`docs/superpowers/plans/YYYY-MM-DD-M{n}-{模块名}-plan.md`。

---

## 3. 模块切分原则

**依赖驱动，自底向上。** 严格遵循设计文档 §5.2 的单向依赖链：

```
api/          → orchestrator/   → state_manager/ → common/
api/          → services/       → models/
api/          → websocket/      → common/
orchestrator/ → protocol/       → common/
```

构建顺序沿依赖链**从底层向上**：先建被依赖的、纯粹的、可独立测试的模块，再建组合它们的上层模块。这样每个模块开工时，其依赖的下层已稳定，避免因半成品接口返工。

每个模块必须满足（呼应 CLAUDE.md 规范）：

- **单一职责**：一句话说清它做什么。
- **明确边界**：输入/输出/依赖清晰，可脱离上层独立测试。
- **最小实现**：只做设计文档要求的，不做“以防万一”的扩展。
- **可验证 DoD**：完成标准包含可运行的测试项，能独立闭环。

---

## 4. 模块地图总览

| 模块 | 名称 | 落地位置 | 前置依赖 | 阶段 |
|------|------|---------|---------|------|
| M1 | 数据模型扩展 | `models/`、`migrations/` | —（Phase 1 已有 base/user/agent） | Phase 2 |
| M2 | 五阶段协议 | `protocol/` | common | Phase 2 |
| M3 | Redis 状态机 | `state_manager/` | common、M1 | Phase 2 |
| M4 | WebSocket 网关 | `websocket/` | common、M2、M3 | Phase 2 |
| M5 | LLM 服务层 | `services/llm_service` | common | Phase 3 |
| M6 | Orchestrator 核心 | `orchestrator/` | M2、M3、M5 | Phase 3 |
| M7 | 业务服务层 | `services/` | M1、M6 | Phase 3 |
| M8 | REST API 扩展 | `api/v1/` | M6、M7 | Phase 3 |
| M9 | 前端基础设施 | `frontend/src/{api,types,hooks,components}` | M2、M4、M8（接口契约） | Phase 4 |
| M10 | AgentCanvas 拓扑 | `frontend/src/features/canvas` | M9 | Phase 4 |
| M11 | LogStream 日志流 | `frontend/src/features/logs` | M9 | Phase 4 |
| M12 | Timeline 执行链路 | `frontend/src/features/timeline` | M9 | Phase 4 |
| M13 | NodePanel 节点面板 | `frontend/src/features/panel` | M9、M10 | Phase 4 |
| M14 | E2E 集成测试 | `backend/tests/integration`、前端 e2e | M8、M10–M13 | Phase 5 |
| M15 | 可观测性 | `common/`、`docker/` | M8 | Phase 5 |
| M16 | 压测优化 + 文档收尾 | 全局 | M14 | Phase 5 |

> **MinIO / Nginx 不进主线。** 设计文档 ADR 已明确 YAGNI/预留，`docker-compose.yml` 中保留注释配置。仅当出现文件存储或反向代理的真实需求时，才作为“按需模块”单独立计划，不占用主线模块号。

---

## 5. 模块详情

每个模块条目为**目录型**：给出职责、落地位置、接口概要、DoD 与前置依赖。完整的函数签名、协议 schema、事件字段定义在该模块开工时，写入其详细执行计划。

---

### Phase 2 — 协议与实时通信底座

#### M1 数据模型扩展

- **职责**：补齐设计文档 §8.2 剩余三张表的 ORM 模型与迁移。
- **落地**：`models/workflow.py`、`models/execution.py`、`models/event.py`；新增 Alembic 迁移。
- **输入 / 输出 / 依赖**：无运行时输入；产出 ORM 模型 + 数据库表；依赖 Phase 1 的 `Base`/`TimestampMixin`。
- **要点**：`workflows`（拓扑快照 JSONB）、`workflow_executions`（状态、输入、输出，status 部分索引）、`execution_events`（仅追加、无 updated_at、created_at DESC 索引）；外键统一 `ON DELETE SET NULL` 并建索引。
- **DoD**：迁移 `upgrade head` / `downgrade base` 双向通过；三表结构与设计文档 §8 一致；模型可被导入且 `alembic revision --autogenerate` 无残余 diff。
- **前置**：无。

#### M2 五阶段协议

- **职责**：实现 INIT→RECEIVE→ROUTE→EXECUTE→FINISH 五阶段协议的封包、事件与 JSON Schema 校验，作为 Agent 间通信的统一契约。
- **落地**：`protocol/stages.py`、`protocol/events.py`、`protocol/serializer.py`、`protocol/schemas/`。
- **输入 / 输出 / 依赖**：输入为阶段数据结构；输出为经校验的序列化事件；仅依赖 `common`（最纯粹，可完全独立单测）。
- **要点**：阶段枚举 + 标准事件类型（`agent_spawn`/`agent_call`/`agent_finish`/`agent_reflect`）；JSON Schema 强校验；`execution_events.payload` 字段规范（设计文档 §8.3）作为序列化目标。
- **DoD**：每个阶段与事件类型有往返（封包→序列化→反序列化→校验）单测；非法 payload 被 Schema 拒绝的负向测试通过。
- **前置**：common（已有）。

#### M3 Redis 状态机

- **职责**：管理 Agent 执行期的热状态（上下文、会话、任务态），写 Redis。
- **落地**：`state_manager/context.py`、`state_manager/session.py`、`state_manager/task_state.py`。
- **输入 / 输出 / 依赖**：输入为执行/会话标识与状态数据；输出为 Redis 读写；依赖 `common/redis_client`（已有）、M1（持久化对照）。
- **要点**：热数据入 Redis、持久化数据入 PostgreSQL 的分工；键命名规范（如 `execution:{id}`）与 M4 的 Pub/Sub channel 对齐。
- **DoD**：状态读写、过期、并发覆盖有集成测试（对真实/内存 Redis）；键命名与 M4 约定一致。
- **前置**：M1。

#### M4 WebSocket 网关

- **职责**：订阅 Redis Pub/Sub，将执行事件实时推送前端。
- **落地**：`websocket/gateway.py`、`websocket/handlers.py`、`websocket/broadcaster.py`。
- **输入 / 输出 / 依赖**：输入为 Redis 频道事件；输出为 WebSocket 帧；依赖 `common`、M2（事件格式）、M3（channel 约定）。
- **要点**：`channel: execution:{id}` 订阅 → broadcaster 广播；连接生命周期与鉴权（复用 Phase 1 JWT）；断线处理。
- **DoD**：端到端本地测试——发布一条 Redis 事件，WebSocket 客户端收到对应帧；鉴权失败连接被拒。
- **前置**：M2、M3。

### Phase 3 — 编排引擎与 LLM

#### M5 LLM 服务层

- **职责**：封装 LiteLLM 多厂商调用，提供统一的流式调用接口与 token/成本统计。
- **落地**：`services/llm_service.py`。
- **输入 / 输出 / 依赖**：输入为模型名、消息、参数；输出为 token 流 + 用量统计；依赖 `common`、`config`（LLM 相关环境变量已在 Phase 1 settings 中预留）。
- **要点**：LiteLLM 版本精确锁定（设计文档已定 `1.50.x`）；流式 yield token；产出 `prompt_tokens`/`completion_tokens`/`model`/`model_cost_usd`，对齐 `execution_events.payload`（§8.3）。
- **DoD**：对 mock/stub 的 LLM 后端有单测——流式返回、用量字段计算正确；不真实消耗 API 配额。
- **前置**：common（已有）。

#### M6 Orchestrator 核心

- **职责**：DeepAgents 调度核心——创建工作流执行实例、分配 Agent、驱动五阶段协议流转。
- **落地**：`orchestrator/base_agent.py`、`orchestrator/coordinator.py`、`orchestrator/scheduler.py`、`orchestrator/router.py`。
- **输入 / 输出 / 依赖**：输入为工作流定义与任务输入；输出为执行事件流（经 M2 封包、经 M3 落状态、经 Redis 发布供 M4 推送）；依赖 M2、M3、M5。
- **要点**：Coordinator 建执行实例 → Scheduler 分配 → Router 多跳路由 → 调 M5 执行 → 写状态/发事件；单向依赖，禁止反向引用 api/services。
- **DoD**：一个最小工作流（单/双 Agent）端到端跑通并产出完整五阶段事件序列的集成测试；事件落库与 Redis 发布可验证。
- **前置**：M2、M3、M5。

#### M7 业务服务层

- **职责**：Agent 与 Workflow 的 CRUD 及生命周期业务逻辑。
- **落地**：`services/agent_service.py`、`services/workflow_service.py`。
- **输入 / 输出 / 依赖**：输入为业务请求 DTO；输出为持久化实体；依赖 M1（模型）、M6（触发执行）。
- **要点**：沿用 Phase 1 `AuthService` 的服务类风格（构造注入 `AsyncSession`）；业务校验与错误以 `ValueError` 上抛，由 API 层转 HTTP。
- **DoD**：Agent/Workflow 增删改查 + 触发执行的服务层单测（对测试库）通过。
- **前置**：M1、M6。

#### M8 REST API 扩展

- **职责**：暴露 agents / workflows / executions 的 REST 端点。
- **落地**：`api/v1/agents.py`、`api/v1/workflows.py`、`api/v1/executions.py`、对应 `schemas/`。
- **输入 / 输出 / 依赖**：输入为 HTTP 请求；输出为 Pydantic 响应；依赖 M6、M7，复用 Phase 1 的 RBAC 依赖（`require_role`）。
- **要点**：沿用 Phase 1 auth 路由风格（`APIRouter` + `Depends` + `response_model`）；RBAC 分级；OpenAPI 自动文档。
- **DoD**：各端点有 TestClient 集成测试（含鉴权/权限负向用例）；OpenAPI schema 生成无误。
- **前置**：M6、M7。

### Phase 4 — 前端可视化

#### M9 前端基础设施

- **职责**：搭建前端与后端通信的公共层，作为 M10–M13 的共同底座。
- **落地**：`frontend/src/api/ws.ts`、`frontend/src/types/protocol.ts`、`frontend/src/hooks/{useWebSocket,useAgentStream}.ts`、`frontend/src/components/layout/`。
- **输入 / 输出 / 依赖**：输入为后端 REST/WS 契约；输出为类型化的数据访问 hook 与布局；依赖 M2（协议类型对齐）、M4（WS 帧格式）、M8（REST 契约）。
- **要点**：`types/protocol.ts` 与后端协议一一对齐（同一份契约的前端镜像）；`useWebSocket` 封装重连；沿用 Phase 1 的 `http.ts`/`sessionStore` 风格与 TanStack Query。
- **DoD**：WS 连接建立/重连、REST 数据获取的 hook 有测试或 Storybook/最小可运行验证；协议类型与后端无偏差。
- **前置**：M2、M4、M8（契约）。

#### M10 AgentCanvas 拓扑

- **职责**：用 React Flow（@xyflow/react）实时渲染 Agent 协作拓扑。
- **落地**：`frontend/src/features/canvas/`。
- **输入 / 输出 / 依赖**：输入为 M9 的 agent 事件流；输出为拓扑视图；依赖 M9。
- **要点**：节点/边随 `agent_spawn`/`agent_call`/`agent_finish` 动态增删；状态色彩映射。
- **DoD**：给定一段事件序列，拓扑正确渲染与更新（组件测试或本地手测录屏可复现）。
- **前置**：M9。

#### M11 LogStream 日志流

- **职责**：实时流式展示 EXECUTE 阶段的 token 输出与事件日志。
- **落地**：`frontend/src/features/logs/`。
- **输入 / 输出 / 依赖**：输入为 M9 的 token/事件流；输出为滚动日志视图；依赖 M9。
- **DoD**：流式 token 增量渲染、自动滚动、按执行过滤可用。
- **前置**：M9。

#### M12 Timeline 执行链路

- **职责**：按时间倒序回溯执行链路（可观测性核心视图）。
- **落地**：`frontend/src/features/timeline/`。
- **输入 / 输出 / 依赖**：输入为 `execution_events`（经 M8 查询接口，created_at DESC）；输出为时间线视图；依赖 M9。
- **DoD**：给定执行 ID，时间线按阶段/时间正确呈现事件。
- **前置**：M9。

#### M13 NodePanel 节点面板

- **职责**：查看/编辑选中 Agent 节点的配置与运行详情。
- **落地**：`frontend/src/features/panel/`。
- **输入 / 输出 / 依赖**：输入为选中节点（来自 M10）+ agent 配置（M8）；输出为详情/编辑面板；依赖 M9、M10。
- **DoD**：点击拓扑节点弹出对应详情；配置编辑经 M8 接口保存成功。
- **前置**：M9、M10。

### Phase 5 — 集成与运维

#### M14 E2E 集成测试

- **职责**：打通「触发工作流 → 五阶段执行 → 事件推送 → 前端渲染」全链路的端到端测试。
- **落地**：`backend/tests/integration/`、前端 e2e（Playwright 或等价）。
- **输入 / 输出 / 依赖**：依赖 M8、M10–M13。
- **要点**：覆盖率对齐设计文档 §11 目标（35–50%）。
- **DoD**：至少一条完整业务链路的 E2E 用例在本地/CI 通过。
- **前置**：M8、M10–M13。

#### M15 可观测性

- **职责**：接入 Prometheus/Grafana 基础监控与结构化日志。
- **落地**：`common/`（metrics/中间件）、`docker/`（监控栈配置）。
- **输入 / 输出 / 依赖**：依赖 M8。
- **要点**：设计文档 §11 定位为「基础搭建、指标不精调」，保持最小实现。
- **DoD**：关键指标（请求量、执行数、token/成本）可在 Grafana 看到；`/metrics` 端点可用。
- **前置**：M8。

#### M16 压测优化 + 文档收尾

- **职责**：压测、性能优化、补全 `docs/` 各文档、开源推广前收尾。
- **落地**：全局；`docs/{architecture,protocol,api,development}/`。
- **输入 / 输出 / 依赖**：依赖 M14。
- **要点**：填充 Phase 1 建立的空文档目录；WebSocket 高并发按需驱动优化（§11）。
- **DoD**：压测报告存档；`docs/` 四个目录有对应文档；README/协议文档与实现一致。
- **前置**：M14。

---

## 6. 规范约束（贯穿所有模块）

每个模块的详细计划与编码都必须遵循：

- **简化优先**（CLAUDE.md §2）：只实现本模块 DoD 所需，不做预留式扩展；MinIO/Nginx 等按需模块不提前引入。
- **外科手术式改动**（CLAUDE.md §3）：只动本模块范围，不顺手重构周边；配合现有代码风格（Phase 1 已确立的服务类、路由、settings 模式）。
- **目标驱动 + 测试闭环**（CLAUDE.md §4）：DoD 中的测试项即成功标准，编码循环至测试通过。
- **单向依赖**（设计文档 §5.2）：严禁反向依赖，模块只依赖其声明的前置。
- **即时中文提交**（MEMORY.md）：每个模块完成并验证后立即提交，描述追溯改动目的。
- **代码规范**：后端 `ruff check app tests migrations` + `pytest` 全绿；前端 `biome check` 全绿；CI 必须通过。

---

## 7. 后续动作

本路线图确认后，进入循环工作流第一步：为 **M1 数据模型扩展** 编写详细执行计划（`docs/superpowers/plans/`），交由 codex + subagent 实现。
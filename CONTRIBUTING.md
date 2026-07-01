# 贡献指南

感谢你对 NexusMesh 的关注。本文档说明参与开发的基本约定。

## 开发环境

请先阅读 [README](./README.md) 的「快速开始」，推荐使用「方式二：本地开发」搭建环境。

- 后端：Python 3.13 + uv，代码规范工具为 Ruff
- 前端：Node.js 22 LTS + pnpm 9，代码规范工具为 Biome

## 分支与提交

- 主分支为 `main`，请勿直接向其推送。
- 新功能从 `main` 切出 `feature/*` 分支，缺陷修复使用 `fix/*` 分支。
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范，例如：
  - `feat: 新增 Agent 调度接口`
  - `fix: 修复 JWT 刷新令牌校验`
  - `docs: 补充协议设计说明`

## 代码规范

提交前请在本地通过以下检查：

```powershell
# 后端
cd backend
uv run ruff check app tests migrations
uv run pytest tests -q

# 前端
pnpm -C frontend check
```

## 数据库变更

- 所有表结构变更必须通过 Alembic 迁移完成，禁止手动改库。
- 生成迁移：`uv run alembic revision --autogenerate -m "变更说明"`。
- 提交前确认迁移可 `upgrade head` 与 `downgrade` 双向执行。

## Pull Request

- 一个 PR 聚焦一件事，描述中说明变更内容、测试方式与影响范围。
- 涉及接口变更时，同步更新 `docs/` 下相关文档。
- 确保本地检查全部通过后再请求合并：后端 `ruff check app tests migrations` + `uv run pytest tests`，前端 `pnpm -C frontend check`。

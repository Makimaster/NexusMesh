"""M3 状态管理器自定义异常。"""


class ConcurrencyError(RuntimeError):
    """task_state 乐观锁冲突，超过最大重试次数时抛出。

    由 M6 Orchestrator 捕获后决策：中止当前调度步骤或上层重试。
    """

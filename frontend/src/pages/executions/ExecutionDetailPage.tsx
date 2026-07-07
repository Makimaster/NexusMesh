import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { executionsApi } from "../../api/executions";
import { AgentCanvas } from "../../features/canvas/AgentCanvas";
import { useCanvasState } from "../../features/canvas/useCanvasState";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useSessionStore } from "../../stores/sessionStore";

const ACTIVE_STATUSES = ["pending", "running"];

export default function ExecutionDetailPage() {
  const { id = "" } = useParams();
  const token = useSessionStore((state) => state.accessToken);

  const {
    data: execution,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["execution", id],
    queryFn: () => executionsApi.get(id),
    enabled: !!id,
  });

  const isActive = execution
    ? ACTIVE_STATUSES.includes(execution.status)
    : false;

  const { wsState, events } = useAgentStream({
    executionId: id,
    token: isActive ? token : null,
  });
  const { nodes, edges } = useCanvasState(events);

  if (isLoading) return <p>加载中…</p>;
  if (isError || !execution) return <p>加载执行详情失败</p>;

  if (!isActive) {
    return (
      <div className="mesh-execution-detail">
        <h1>Execution {id}</h1>
        <p className="mesh-execution-ended">
          此执行已结束（{execution.status}
          ）。实时画布仅用于进行中的执行，历史回溯请查看 Timeline。
        </p>
      </div>
    );
  }

  return (
    <div className="mesh-execution-detail">
      <header className="mesh-execution-detail__header">
        <h1>Execution {id}</h1>
        <span className={`mesh-ws-indicator mesh-ws--${wsState}`}>
          {wsState}
        </span>
      </header>
      <div className="mesh-execution-detail__canvas">
        <AgentCanvas nodes={nodes} edges={edges} />
      </div>
    </div>
  );
}

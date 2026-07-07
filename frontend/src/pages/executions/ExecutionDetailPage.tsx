import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useParams } from "react-router";

import { executionsApi } from "../../api/executions";
import { AgentCanvas } from "../../features/canvas/AgentCanvas";
import { useCanvasState } from "../../features/canvas/useCanvasState";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useSessionStore } from "../../stores/sessionStore";
import type {
  TimelineEventResponse,
  WebSocketEvent,
} from "../../types/protocol";

const ACTIVE_STATUSES = ["pending", "running"];

type ProtocolCanvasEvent = Exclude<
  WebSocketEvent,
  { event_type: "agent_chunk_stream" }
>;

function isProtocolEvent(event: WebSocketEvent): event is ProtocolCanvasEvent {
  return event.event_type !== "agent_chunk_stream";
}

function flattenTimelineEvent(event: TimelineEventResponse): WebSocketEvent {
  return {
    ...event.payload,
    protocol_stage: event.protocol_stage,
    event_type: event.event_type,
    created_at: event.created_at,
  } as WebSocketEvent;
}

function getProtocolEventKey(event: ProtocolCanvasEvent): string {
  return Object.entries(event)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([key, value]) => `${key}:${JSON.stringify(value)}`)
    .join("|");
}

function mergeCanvasEvents(
  timelineEvents: TimelineEventResponse[] | undefined,
  streamEvents: WebSocketEvent[],
): WebSocketEvent[] {
  const seenProtocolEvents = new Set<string>();
  const protocolEvents: Array<{
    event: ProtocolCanvasEvent;
    order: number;
  }> = [];
  const chunkStreamEvents: WebSocketEvent[] = [];

  const pushEvent = (event: WebSocketEvent, order: number) => {
    if (!isProtocolEvent(event)) {
      chunkStreamEvents.push(event);
      return;
    }
    const key = getProtocolEventKey(event);

    if (seenProtocolEvents.has(key)) {
      return;
    }

    seenProtocolEvents.add(key);
    protocolEvents.push({
      event,
      order,
    });
  };

  let order = 0;

  for (const event of timelineEvents?.map(flattenTimelineEvent) ?? []) {
    pushEvent(event, order);
    order += 1;
  }

  for (const event of streamEvents) {
    pushEvent(event, order);
    order += 1;
  }

  protocolEvents.sort((left, right) => {
    const timeDiff =
      Date.parse(left.event.created_at) - Date.parse(right.event.created_at);
    if (timeDiff !== 0) {
      return timeDiff;
    }

    return left.order - right.order;
  });

  return [...protocolEvents.map(({ event }) => event), ...chunkStreamEvents];
}

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

  const { data: timelineEvents } = useQuery({
    queryKey: ["execution", id, "timeline"],
    queryFn: () => executionsApi.timeline(id),
    enabled: !!id && isActive,
  });

  const { wsState, events } = useAgentStream({
    executionId: id,
    token: isActive ? token : null,
  });
  const canvasEvents = useMemo(
    () => mergeCanvasEvents(timelineEvents, events),
    [timelineEvents, events],
  );
  const { nodes, edges } = useCanvasState(canvasEvents);

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

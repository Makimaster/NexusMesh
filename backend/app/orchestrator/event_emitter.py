"""M6 事件双写网关：Redis 广播 + PG 落库。"""

from __future__ import annotations

import json
import uuid

from app.common.logger import log
from app.db.session import AsyncSessionLocal
from app.models.event import ExecutionEvent
from app.protocol import ProtocolEvent, to_payload
from app.state_manager.keys import get_channel_events


class EventEmitter:
    def __init__(self, redis) -> None:
        self._redis = redis

    async def emit_event(self, execution_id: str, event: ProtocolEvent) -> None:
        data = to_payload(event)
        channel = get_channel_events(execution_id)
        await self._redis.publish(channel, json.dumps(data))
        try:
            await self._persist(execution_id, event, data)
        except Exception as exc:
            log.critical("EventEmitter persist failed for %s: %s", execution_id, exc)

    async def emit_token(
        self,
        execution_id: str,
        agent_id: str,
        text: str,
        reasoning: bool = False,
    ) -> None:
        channel = get_channel_events(execution_id)
        data = {
            "event_type": "agent_chunk_stream",
            "agent_id": agent_id,
            "text": text,
            "reasoning": reasoning,
        }
        await self._redis.publish(channel, json.dumps(data))

    async def _persist(
        self,
        execution_id: str,
        event: ProtocolEvent,
        data: dict,
    ) -> None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(
                    ExecutionEvent(
                        execution_id=uuid.UUID(execution_id),
                        protocol_stage=event.protocol_stage.value,
                        event_type=event.event_type.value,
                        payload=data,
                    )
                )

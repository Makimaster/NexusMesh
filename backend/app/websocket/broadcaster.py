import asyncio

from fastapi import WebSocket
from redis.exceptions import ConnectionError, RedisError

CHANNEL_PATTERN = "channel:execution:*:events"


class Broadcaster:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = {}
        self._pubsub = None
        self._task: asyncio.Task | None = None

    async def start(self, redis) -> None:
        if self._pubsub is not None or self._task is not None:
            return
        self._pubsub = redis.pubsub()
        await self._pubsub.psubscribe(CHANNEL_PATTERN)
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        pubsub = self._pubsub
        self._pubsub = None
        if pubsub is not None:
            await pubsub.punsubscribe()

    async def subscribe(self, channel: str, ws: WebSocket) -> None:
        self._channels.setdefault(channel, set()).add(ws)

    async def unsubscribe(self, channel: str, ws: WebSocket) -> None:
        sockets = self._channels.get(channel)
        if not sockets:
            return
        sockets.discard(ws)
        if not sockets:
            self._channels.pop(channel, None)

    def _extract_execution_id(self, channel: str) -> str | None:
        parts = channel.split(":")
        if len(parts) != 4:
            return None
        if parts[0] != "channel" or parts[1] != "execution" or parts[3] != "events":
            return None
        if not parts[2]:
            return None
        return parts[2]

    async def _listen_loop(self) -> None:
        while self._pubsub is not None:
            try:
                async for message in self._pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue

                    channel = message.get("channel")
                    data = message.get("data")

                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    if isinstance(data, bytes):
                        data = data.decode()
                    elif data is None:
                        data = ""
                    else:
                        data = str(data)

                    for ws in list(self._channels.get(channel, ())):
                        try:
                            await ws.send_text(data)
                        except Exception:
                            pass
                return
            except asyncio.CancelledError:
                return
            except (RedisError, ConnectionError):
                await asyncio.sleep(1)
                if self._pubsub is None:
                    return
                await self._pubsub.psubscribe(CHANNEL_PATTERN)

    def _clear_for_test(self) -> None:
        self._channels.clear()


broadcaster = Broadcaster()

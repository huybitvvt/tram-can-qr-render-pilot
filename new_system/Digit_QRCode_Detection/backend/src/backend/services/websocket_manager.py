"""Bounded fan-out for lightweight recognition events."""

from __future__ import annotations

import asyncio
from typing import Any


class WebSocketManager:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._clients):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    @property
    def client_count(self) -> int:
        return len(self._clients)

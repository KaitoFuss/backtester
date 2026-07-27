from collections import deque

from backtester.core.events import Event


class EventQueue:
    """FIFO event buffer drained synchronously by the engine each bar. Backed
    by a ``deque`` rather than ``queue.Queue``: the event loop is
    single-threaded, so the locking a thread-safe queue does on every put/get
    is pure overhead here."""

    def __init__(self) -> None:
        self._q: deque[Event] = deque()

    def put(self, event: Event) -> None:
        self._q.append(event)

    def get(self) -> Event:
        return self._q.popleft()

    def empty(self) -> bool:
        return not self._q

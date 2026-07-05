import queue

from backtester.core.events import Event


class EventQueue:
    def __init__(self) -> None:
        self._q: queue.Queue[Event] = queue.Queue()

    def put(self, event: Event) -> None:
        self._q.put(event)

    def get(self) -> Event:
        return self._q.get()

    def empty(self) -> bool:
        return self._q.empty()

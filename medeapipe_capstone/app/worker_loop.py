"""Single-threaded scheduling and observable state, without a GUI runtime."""
import heapq
import itertools
import threading
import time


class StateValue:
    def __init__(self, value=''):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in tuple(self.callbacks):
            callback()

    def trace_add(self, _mode, callback):
        self.callbacks.append(callback)


class WorkerLoop:
    def __init__(self):
        self._condition = threading.Condition()
        self._tasks = []
        self._sequence = itertools.count()
        self.closed = False

    def after(self, milliseconds, callback):
        with self._condition:
            if not self.closed:
                heapq.heappush(self._tasks, (time.monotonic() + milliseconds / 1000,
                                            next(self._sequence), callback))
                self._condition.notify()

    def destroy(self):
        with self._condition:
            self.closed = True
            self._tasks.clear()
            self._condition.notify_all()

    def run(self):
        while True:
            with self._condition:
                if self.closed:
                    return
                if not self._tasks:
                    self._condition.wait()
                    continue
                deadline, _sequence, callback = self._tasks[0]
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                heapq.heappop(self._tasks)
            callback()

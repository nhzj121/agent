"""Process-local admission and cooperative execution lifetime; no transport cancellation."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, RLock, get_ident
import time
import uuid

_current = ContextVar("research_execution", default=None)


class ExecutionStopped(RuntimeError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(detail)


class ResearchBusy(RuntimeError):
    pass


class ResearchAdmission:
    """One limiter per service process. No waiting queue and no global-host quota."""
    def __init__(self, limit):
        self.limit, self.active = limit, 0
        self._lock = RLock()

    def acquire(self):
        with self._lock:
            if self.active >= self.limit:
                raise ResearchBusy("RESEARCH_CAPACITY_EXCEEDED")
            self.active += 1
        return _AdmissionLease(self)

    def _release(self):
        with self._lock:
            self.active -= 1


class _AdmissionLease:
    def __init__(self, owner):
        self.owner = owner
        self._lock = RLock()
        self._released = False

    def release(self):
        with self._lock:
            if not self._released:
                self._released = True
                self.owner._release()


class ExecutionControl:
    """Root + actual Worker references retain capacity until all Python work exits."""
    def __init__(self, seconds, *, clock=time.monotonic, waiter=None, on_idle=None):
        self.id = uuid.uuid4().hex
        self.clock = clock
        self.deadline = clock() + seconds
        self.cancel_event = Event()
        self.lock = RLock()
        self.code = None
        self.detail = None
        self._refs = 1
        self._root_finished = False
        self._idle = Event()
        self._callbacks = [on_idle] if on_idle else []
        self._streams = {}
        self._waiter = waiter

    def remaining(self):
        return max(0., self.deadline - self.clock())

    def check(self):
        with self.lock:
            if not self.cancel_event.is_set() and self.remaining() <= 0:
                self.cancel("research deadline exceeded", code="DEADLINE_EXCEEDED")
            if self.cancel_event.is_set():
                self.code = self.code or "CANCELLED"
                self.detail = self.detail or "execution cancelled"
                raise ExecutionStopped(self.code, self.detail)

    def cancel(self, detail="execution cancelled", *, code="CANCELLED"):
        # The same lock orders tool commits and accepted cancellation.
        with self.lock:
            if not self.cancel_event.is_set():
                self.code, self.detail = code, detail
                self.cancel_event.set()

    @contextmanager
    def commit(self):
        with self.lock:
            self.check()
            yield

    def retain(self):
        with self.lock:
            self.check()
            if self._refs == 0:
                raise RuntimeError("execution already idle")
            self._refs += 1

    def on_idle(self, callback):
        with self.lock:
            if self._refs:
                self._callbacks.insert(0, callback)
                return
        callback()

    def release(self):
        with self.lock:
            self._refs -= 1
            if self._refs:
                return
            callbacks, self._callbacks = self._callbacks, []
        try:
            for callback in callbacks:
                callback()
        finally:
            self._idle.set()

    def finish(self):
        with self.lock:
            if self._root_finished:
                return
            self._root_finished = True
        self.release()

    def wait_idle(self, timeout=None):
        return self._idle.wait(timeout)

    def wait_retry(self, seconds):
        self.check()
        delay = min(seconds, self.remaining())
        if self._waiter:
            self._waiter(delay)
        else:
            self.cancel_event.wait(delay)
        self.check()

    def own_stream(self, stream):
        with self.lock:
            self._streams.setdefault(get_ident(), set()).add(stream)

    def disown_stream(self, stream):
        with self.lock:
            streams = self._streams.get(get_ident(), set())
            streams.discard(stream)
            if not streams:
                self._streams.pop(get_ident(), None)

    def close_thread_streams(self):
        # Only called by the owner thread, never close another Worker's response.
        with self.lock:
            streams = self._streams.pop(get_ident(), set())
        for stream in streams:
            stream.close()


def current_execution():
    return _current.get()


@contextmanager
def bind_execution(execution):
    token = _current.set(execution)
    try:
        yield execution
    finally:
        _current.reset(token)


def checkpoint():
    control = current_execution()
    if control is not None:
        control.check()


def close_thread_streams():
    control = current_execution()
    if control is not None:
        control.close_thread_streams()


@contextmanager
def tool_boundary():
    control = current_execution()
    if control is None:
        yield
    else:
        with control.commit():
            yield

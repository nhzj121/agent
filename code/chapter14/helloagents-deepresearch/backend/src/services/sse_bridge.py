"""ASGI transport lifecycle around one synchronous research iterator.

Only the producer advances/closes that iterator. A separate supervisor accepts
cancellation under ExecutionControl's commit lock, without blocking the ASGI loop.
"""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
import json
import logging
from threading import Event, Lock, Thread

import anyio
from starlette.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)
_END = object()
_WAKE = object()


@dataclass(frozen=True)
class ExecutionFailure:
    error: Exception


class ResearchBridge:
    def __init__(self, control, iterator_factory, cancellation_factory):
        self.control = control
        self.iterator_factory = iterator_factory
        self.cancellation_factory = cancellation_factory
        # Reserve lifetimes while still in the synchronous route setup thread.
        # One belongs to the producer, one to the transport supervisor.
        control.retain(allow_cancelled=True)
        control.retain(allow_cancelled=True)
        self.stopped = Event()
        self._finish_transport = Event()
        self._cancel_accepted = Event()
        self._stop_lock = Lock()
        self._close_requested = False
        self._reason = None
        self._code = None
        self._emit_terminal = False
        self._producer_started = False
        self.completed = False
        self.research_done = Event()
        self.producer_done = Event()
        self.supervisor_done = Event()

    def open(self):
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=32)
        self._cancelled_items = self._loop.create_future()
        self._supervision_finished = self._loop.create_future()
        try:
            Thread(target=self._supervise, name="research-transport", daemon=True).start()
        except Exception:
            # No producer has started: no tool/network code can hold this
            # private context's lock. Return all three reserved references.
            self.control.finish()
            self.control.release()
            self.control.release()
            self.supervisor_done.set()
            raise

    def request_close(self, reason=None, *, code="CLIENT_DISCONNECTED", emit_terminal=False):
        with self._stop_lock:
            if self._close_requested:
                return
            self._close_requested = True
            # api.ts releases its reader after a terminal frame. That is normal
            # transport cleanup once research has produced done/error.
            if self.research_done.is_set():
                reason, emit_terminal = None, False
            self._reason, self._code = reason, code
            self._emit_terminal = emit_terminal
            self.stopped.set()
            self._finish_transport.set()
        self._notify(self._wake)

    def _wake(self):
        if not self._queue.full():
            self._queue.put_nowait(_WAKE)

    def _notify(self, callback, *args):
        try:
            self._loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            # ASGI loop has gone away; synchronous cleanup still owns capacity.
            pass

    def _set_cancelled_items(self, items):
        if not self._cancelled_items.done():
            self._cancelled_items.set_result(items)

    def _set_supervision_finished(self):
        if not self._supervision_finished.done():
            self._supervision_finished.set_result(None)

    @property
    def cleanup_pending(self):
        return not self.control.wait_idle(0)

    def _supervise(self):
        self._finish_transport.wait()
        items = []
        try:
            if self._reason is not None:
                self.control.cancel(self._reason, code=self._code)
                items = self.cancellation_factory(self.control)
        except Exception:
            logger.exception("Research cancellation snapshot failed")
            items = [ExecutionFailure(RuntimeError("Research cancellation failed"))]
        finally:
            self._cancel_accepted.set()
            self._notify(self._set_cancelled_items, items)
            try:
                if not self._producer_started:
                    self.control.release()
                    self.producer_done.set()
                self.control.finish()
            finally:
                try:
                    self.control.release()
                finally:
                    self.supervisor_done.set()
                    self._notify(self._set_supervision_finished)

    def _put(self, item):
        if self.stopped.is_set():
            return False
        operation = self._queue.put(item)
        try:
            pending = asyncio.run_coroutine_threadsafe(operation, self._loop)
        except RuntimeError:
            operation.close()
            return False
        while True:
            try:
                pending.result(timeout=.05)
                return not self.stopped.is_set()
            except FutureTimeout:
                if self.stopped.is_set():
                    pending.cancel()
                    return False

    def _produce(self):
        inner = None
        try:
            if self.stopped.is_set():
                return
            inner = self.iterator_factory()
            for item in inner:
                if isinstance(item, dict) and item.get("type") in ("done", "error"):
                    self.research_done.set()
                if not self._put(item):
                    break
        except Exception as exc:
            self.research_done.set()
            if not self.stopped.is_set():
                self._put(ExecutionFailure(exc))
        finally:
            # Transport owns the first cancellation reason. Closing the Agent
            # iterator before supervisor acceptance could win with generic
            # GeneratorExit/CANCELLED instead of CLIENT_DISCONNECTED.
            # Only the producer waits; ASGI remains free, capacity is retained.
            if self.stopped.is_set() and self._reason is not None:
                self._cancel_accepted.wait()
            try:
                close = getattr(inner, "close", None)
                if close is not None:
                    close()  # exclusively on the iterator's owner thread
            except Exception:
                logger.exception("Research iterator cleanup failed")
            finally:
                try:
                    self.control.finish()
                    self.research_done.set()
                    self._put(_END)
                finally:
                    self.control.release()
                    self.producer_done.set()

    async def items(self):
        try:
            if not self.stopped.is_set():
                self._producer_started = True
                try:
                    Thread(target=self._produce, name="research-execution", daemon=True).start()
                except Exception as exc:
                    self._producer_started = False
                    self.request_close("research execution thread could not start",
                                       code="EXECUTION_START_FAILED")
                    yield ExecutionFailure(exc)
                    return
            while True:
                if self.stopped.is_set():
                    if self._emit_terminal:
                        for item in await asyncio.shield(self._cancelled_items):
                            yield item
                    return
                item = await self._queue.get()
                if self.stopped.is_set():
                    continue  # queued pre-cancel events never follow terminal snapshot
                if item is _END:
                    self.completed = True
                    return
                if item is not _WAKE:
                    yield item
        finally:
            if not self.completed:
                self.request_close("research response iterator closed")

    async def watch_deadline(self):
        while not self.stopped.is_set():
            if self.research_done.is_set():
                return
            remaining = self.control.remaining()
            if remaining <= 0:
                self.request_close("research deadline exceeded", code="DEADLINE_EXCEEDED",
                                   emit_terminal=True)
                return
            await anyio.sleep(min(.05, remaining))


class _ResearchResponseLifecycle:
    async def __call__(self, scope, receive, send):
        self.bridge.open()
        try:
            async with anyio.create_task_group() as group:
                async def transmit():
                    try:
                        await self._transmit(scope, receive, send)
                    except OSError:
                        self.bridge.request_close("ASGI response send failed")
                    finally:
                        group.cancel_scope.cancel()

                async def disconnected():
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            self.bridge.request_close("HTTP client disconnected")
                            group.cancel_scope.cancel()
                            return

                # One receive consumer for ASGI 2.3 and 2.4, including periods
                # with no outgoing chunks (e.g. blocked Planner/Reporter).
                group.start_soon(disconnected)
                group.start_soon(self.bridge.watch_deadline)
                group.start_soon(transmit)
        finally:
            self.bridge.request_close(
                None if self.bridge.completed else "ASGI research request closed")
            # No join, Queue.get or synchronous cancel/commit lock on this loop.
            with anyio.CancelScope(shield=True):
                close = getattr(getattr(self, "body_iterator", None), "aclose", None)
                if close is not None:
                    await close()
                if self.bridge.completed:
                    # This is an async notification, never thread.join/wait.
                    # Normal response completion includes transport lease release.
                    await asyncio.shield(self.bridge._supervision_finished)


class ResearchStreamingResponse(_ResearchResponseLifecycle, StreamingResponse):
    def __init__(self, bridge):
        self.bridge = bridge
        super().__init__(self._encode(), media_type="text/event-stream",
                         headers={"Cache-Control":"no-cache", "Connection":"keep-alive"})

    async def _encode(self):
        inner = self.bridge.items()
        try:
            async for item in inner:
                if isinstance(item, ExecutionFailure):
                    logger.error("Streaming research failed: %s", item.error)
                    item = {"type":"error", "detail":str(item.error),
                            "run_id":self.bridge.control.id, "run_status":"failed"}
                yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
        finally:
            await inner.aclose()

    async def _transmit(self, scope, receive, send):
        await self.stream_response(send)


class ResearchJSONResponse(_ResearchResponseLifecycle, Response):
    def __init__(self, bridge):
        self.bridge = bridge
        super().__init__(content=b"", media_type="application/json")

    async def _transmit(self, scope, receive, send):
        result, failed = None, False
        inner = self.bridge.items()
        try:
            async for item in inner:
                if isinstance(item, ExecutionFailure):
                    failed = True
                    result = {"detail":"Research failed"}
                else:
                    result = item
        finally:
            await inner.aclose()
        await JSONResponse(result, status_code=500 if failed else 200)(scope, receive, send)

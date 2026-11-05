"""Cancellation and request budgets shared by research task workers."""

from contextlib import contextmanager
from functools import lru_cache
from threading import BoundedSemaphore, Event
from uuid import uuid4


class ResearchCancelled(Exception):
    """The user cancelled this research; this is not a task failure."""


class RequestBudget:
    def __init__(self, max_llm: int, max_search: int):
        self.llm = BoundedSemaphore(max_llm)
        self.search = BoundedSemaphore(max_search)


@lru_cache(maxsize=1)
def default_budget():
    # Also bound standalone agents; the HTTP manager supplies its shared budget.
    from config import Configuration
    config = Configuration.from_env()
    return RequestBudget(config.max_llm_concurrency, config.max_search_concurrency)


@contextmanager
def cancellable_slot(gate, runtime):
    """Never perform work after cancellation, including while waiting for a slot."""
    while True:
        runtime.check_cancelled()
        if gate.acquire(timeout=0.1):
            break
    try:
        runtime.check_cancelled()
        yield
    finally:
        gate.release()


class ResearchRuntime:
    def __init__(self, *, research_id: str | None = None, budget: RequestBudget | None = None):
        self.research_id = research_id or uuid4().hex
        self.budget = budget if budget is not None else default_budget()
        self._cancelled = Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise ResearchCancelled("研究已取消")

    def llm_slot(self):
        return cancellable_slot(self.budget.llm, self)

    def search_slot(self):
        return cancellable_slot(self.budget.search, self)

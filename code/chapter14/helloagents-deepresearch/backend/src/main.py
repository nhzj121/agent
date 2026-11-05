"""FastAPI entrypoint exposing the DeepResearchAgent via HTTP."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
import sys
from typing import Any, Dict, Iterator, Optional

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from config import Configuration, SearchAPI
from agent import DeepResearchAgent
from models import ResearchOutcome
from services.research_manager import ResearchManager, ResearchQueueFull, ResearchHistoryUnavailable
from services.research_store import SQLiteResearchStore

# 添加控制台日志处理程序
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)


# 添加错误日志文件处理程序
logger.add(
    sink=sys.stderr,
    level="ERROR",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)


class ResearchRequest(BaseModel):
    """Payload for triggering a research run."""

    topic: str = Field(..., description="Research topic supplied by the user")
    search_api: SearchAPI | None = Field(
        default=None,
        description="Override the default search backend configured via env",
    )


class ResearchResponse(BaseModel):
    """HTTP response containing the generated report and structured tasks."""

    report_markdown: str = Field(
        ..., description="Markdown-formatted research report including sections"
    )
    outcome: ResearchOutcome | None = Field(
        default=None, description="Research completion status and task counts"
    )
    todo_items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured TODO items with summaries and sources",
    )


def _mask_secret(value: Optional[str], visible: int = 4) -> str:
    """Mask sensitive tokens while keeping leading and trailing characters."""
    if not value:
        return "unset"

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def _build_config(payload: ResearchRequest) -> Configuration:
    overrides: Dict[str, Any] = {}

    if payload.search_api is not None:
        overrides["search_api"] = payload.search_api

    return Configuration.from_env(overrides=overrides)


def create_app(*, agent_factory=None, config: Configuration | None = None) -> FastAPI:
    # Resolve the factory at execution time; every research gets a fresh agent.
    settings = config or Configuration.from_env()
    store = SQLiteResearchStore(settings.research_db_path)
    manager = ResearchManager(agent_factory or (
        lambda config, runtime: DeepResearchAgent(config=config, runtime=runtime)
    ), config=settings, store=store)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(manager.start)
        log_startup_configuration()
        try:
            yield
        finally:
            await asyncio.to_thread(manager.close)

    app = FastAPI(title="HelloAgents Deep Researcher", lifespan=lifespan)
    app.state.research_manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Research-ID"],
    )

    def log_startup_configuration() -> None:
        config = Configuration.from_env()

        if config.llm_provider == "ollama":
            base_url = config.sanitized_ollama_url()
        elif config.llm_provider == "lmstudio":
            base_url = config.lmstudio_base_url
        else:
            base_url = config.llm_base_url or "unset"

        logger.info(
            "DeepResearch configuration loaded: provider=%s model=%s base_url=%s search_api=%s "
            "max_loops=%s fetch_full_page=%s tool_calling=%s strip_thinking=%s api_key=%s",
            config.llm_provider,
            config.resolved_model() or "unset",
            base_url,
            (config.search_api.value if isinstance(config.search_api, SearchAPI) else config.search_api),
            config.max_web_research_loops,
            config.fetch_full_page,
            config.use_tool_calling,
            config.strip_thinking_tokens,
            _mask_secret(config.llm_api_key),
        )

    @app.get("/healthz")
    def health_check() -> Dict[str, str]:
        return {"status": "ok"}

    def submit(payload: ResearchRequest) -> dict:
        try:
            return manager.submit(payload.topic, _build_config(payload))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ResearchQueueFull as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def lookup(research_id: str) -> dict:
        try:
            return manager.get(research_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="研究不存在或历史记录已移除") from exc

    def event_response(research_id: str, after: int = 0, *, legacy=False) -> StreamingResponse:
        lookup(research_id)
        try:
            manager.validate_cursor(research_id, after)
        except ResearchHistoryUnavailable as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        def iterator() -> Iterator[str]:
            for event in manager.events(research_id, after):
                if event is None:
                    yield ": keep-alive\n\n"
                else:
                    prefix = "" if legacy else f"id: {event['seq']}\n"
                    yield prefix + f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(iterator(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Research-ID": research_id,
        })

    @app.post("/researches", status_code=202)
    def create_research(payload: ResearchRequest) -> dict:
        """Register a research; execution and event subscriptions are independent."""
        return submit(payload)

    @app.get("/researches")
    def list_researches() -> dict:
        return {"researches": manager.list()}

    @app.get("/researches/{research_id}")
    def get_research(research_id: str) -> dict:
        return lookup(research_id)

    @app.get("/researches/{research_id}/events")
    def research_events(research_id: str, after: int = Query(default=0, ge=0),
                        last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        if last_event_id is not None:
            try:
                after = max(after, int(last_event_id))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Last-Event-ID 必须是事件序号") from exc
        return event_response(research_id, after)

    @app.post("/researches/{research_id}/cancel")
    def cancel_research(research_id: str) -> dict:
        lookup(research_id)
        return manager.cancel(research_id)

    @app.get("/researches/{research_id}/report")
    def research_report(research_id: str) -> dict:
        snapshot = lookup(research_id)
        if not snapshot["report_available"]:
            raise HTTPException(status_code=409, detail="当前研究尚无最终报告")
        return {"research_id": research_id, "report_markdown": snapshot["report_markdown"],
                "outcome": snapshot["outcome"]}

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        job = submit(payload)
        result = manager.wait(job["research_id"])
        return ResearchResponse(report_markdown=result["report_markdown"],
                                todo_items=result["todo_items"], outcome=result["outcome"])

    @app.post("/research/stream")
    def stream_research(payload: ResearchRequest) -> StreamingResponse:
        job = submit(payload)
        # Preserve the original data-only SSE framing for existing clients.
        return event_response(job["research_id"], legacy=True)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

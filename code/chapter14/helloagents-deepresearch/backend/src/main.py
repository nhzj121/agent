"""FastAPI entrypoint exposing the DeepResearchAgent via HTTP."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
import sys
from typing import Any, Dict, Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from config import Configuration, SearchAPI
from agent import DeepResearchAgent

# Keep legacy factory replacements compatible with the original run(topic) protocol.
_ExecutionAgent = DeepResearchAgent
from services.execution_control import (
    ExecutionControl, ResearchAdmission, ResearchBusy, bind_execution)
from threading import Lock

_process_admission = None
_admission_lock = Lock()


def _admission(config):
    global _process_admission
    with _admission_lock:
        if _process_admission is None:
            _process_admission = ResearchAdmission(config.max_active_research)
        return _process_admission


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

    run_id: str | None = None
    run_status: str = "completed"
    warnings: list[str] = Field(default_factory=list)
    report_note_id: str | None = None
    report_note_path: str | None = None
    report_note_status: str = "not_started"
    report_note_error: dict | None = None

    report_markdown: str = Field(
        ..., description="Markdown-formatted research report including sections"
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


def create_app(*, agent_factory=None, admission=None) -> FastAPI:
    app = FastAPI(title="HelloAgents Deep Researcher")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
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

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        try:
            config = _build_config(payload)
            try:
                lease = (admission or _admission(config)).acquire()
            except ResearchBusy as exc:
                raise HTTPException(status_code=429, detail={
                    "code":"RESEARCH_CAPACITY_EXCEEDED", "detail":"active research limit reached"}) from exc
            control = ExecutionControl(config.research_deadline_seconds, on_idle=lease.release)
            try:
                agent = (agent_factory or DeepResearchAgent)(config=config)
            except BaseException:
                control.finish()
                raise
        except HTTPException:
            raise
        except ValueError as exc:  # Likely due to unsupported configuration
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive guardrail
            raise HTTPException(status_code=500, detail="Research failed") from exc

        try:
            with bind_execution(control):
                result = (agent.run(payload.topic, execution=control)
                          if isinstance(agent, _ExecutionAgent) else agent.run(payload.topic))
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Research failed") from exc
        finally:
            control.finish()

        return ResearchResponse(
            report_markdown=(result.report_markdown or result.running_summary or ""),
            todo_items=[asdict(item) if is_dataclass(item) else vars(item) for item in result.todo_items],
            **{key: getattr(result, key, default) for key, default in [
                ("run_id", None), ("run_status", "completed"), ("warnings", []),
                ("report_note_id", None), ("report_note_path", None),
                ("report_note_status", "not_started"), ("report_note_error", None)]},
        )

    @app.post("/research/stream")
    def stream_research(payload: ResearchRequest) -> StreamingResponse:
        try:
            config = _build_config(payload)
            try:
                lease = (admission or _admission(config)).acquire()
            except ResearchBusy as exc:
                raise HTTPException(status_code=429, detail={
                    "code":"RESEARCH_CAPACITY_EXCEEDED", "detail":"active research limit reached"}) from exc
            control = ExecutionControl(config.research_deadline_seconds, on_idle=lease.release)
            try:
                agent = (agent_factory or DeepResearchAgent)(config=config)
            except BaseException:
                control.finish()
                raise
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        except Exception as exc:
            raise HTTPException(status_code=500, detail="Research initialization failed") from exc

        def event_iterator() -> Iterator[str]:
            inner = None
            try:
                inner = (agent.run_stream(payload.topic, execution=control)
                         if isinstance(agent, _ExecutionAgent) else agent.run_stream(payload.topic))
                for event in inner:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:  # pragma: no cover - defensive guardrail
                logger.exception("Streaming research failed")
                error_payload = {"type": "error", "detail": str(exc),
                                 "run_id": getattr(agent, "run_id", None), "run_status": "failed"}
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            finally:
                close = getattr(inner, "close", None)
                try:
                    if close is not None:
                        close()
                finally:
                    control.finish()

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

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

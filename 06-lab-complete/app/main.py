"""
Production AI Agent — Part 6 Final Project

Đạt đủ 12 tiêu chí trong README.md:
    python check_production_ready.py
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của app thành 1 JSON object hợp lệ (tiêu chí 10)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("event", "path", "method", "status", "ms", "cost_usd", "environment"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(JsonFormatter())
    logger.addHandler(_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan quản lý khởi động và graceful shutdown khi nhận SIGTERM (tiêu chí 11)."""
    prev_handler = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        logger.info("SIGTERM received, draining in-flight requests", extra={"event": "sigterm"})
        if callable(prev_handler):
            prev_handler(signum, frame)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        pass

    logger.info(
        "Agent starting",
        extra={"event": "startup", "environment": settings.environment},
    )
    yield
    logger.info("Agent shutting down gracefully", extra={"event": "shutdown"})
    close_redis()


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def structured_access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "HTTP request handled",
        extra={
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": elapsed_ms,
        },
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = "anonymous"


@app.get("/health")
def health():
    """Tiêu chí 4 — Liveness probe: luôn trả 200 khi process còn chạy."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Tiêu chí 5 — Readiness probe: 200 khi Redis sẵn sàng, 503 khi mất kết nối Redis."""
    if not redis_healthy():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "redis": "disconnected"},
        )
    return {"status": "ready", "redis": "connected"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Tiêu chí 6, 7, 8 — Auth (401) -> Rate limit (429) -> Cost guard (402) -> Mock LLM."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)

    logger.info(
        "Question answered",
        extra={"event": "llm_call", "path": "/ask", "status": 200, "cost_usd": round(cost, 8)},
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "cost_usd": round(cost, 8),
    }

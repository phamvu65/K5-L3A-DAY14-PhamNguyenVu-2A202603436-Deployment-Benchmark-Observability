"""
Cost guard (tiêu chí 8).

Yêu cầu:
  • Cộng dồn chi phí LLM (tính theo token) vào Redis
  • Tổng chi phí vượt DAILY_BUDGET_USD (hoặc MONTHLY_BUDGET_USD) → HTTP 402
"""
from datetime import datetime, timezone
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_local_cost_usd: float = 0.0


def _cost_key() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{today}:{settings.agent_api_key or 'default'}"


def _current_spend() -> float:
    client = get_redis()
    if client is not None:
        try:
            val = client.get(_cost_key())
            return float(val) if val is not None else 0.0
        except Exception:
            pass
    return _local_cost_usd


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    budget = settings.daily_budget_usd
    spent = _current_spend()
    if spent >= budget:
        raise HTTPException(
            status_code=402,
            detail=f"Budget exceeded: spent ${spent:.6f} / budget ${budget:.6f}",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    global _local_cost_usd
    in_tok = max(1, input_tokens)
    out_tok = max(1, output_tokens)
    cost = (in_tok / 1000.0) * PRICE_INPUT_PER_1K + (out_tok / 1000.0) * PRICE_OUTPUT_PER_1K

    client = get_redis()
    if client is not None:
        try:
            key = _cost_key()
            client.incrbyfloat(key, cost)
            client.expire(key, 86400 * 2)
            return cost
        except Exception:
            pass

    _local_cost_usd += cost
    return cost

"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

Yêu cầu:
  • Đọc REDIS_URL từ config
  • App vẫn phải KHỞI ĐỘNG ĐƯỢC khi Redis chưa sẵn sàng (đừng ping Redis lúc import)
  • redis_healthy() dùng cho GET /ready: Redis không kết nối được → False
"""
from typing import Optional
import redis
from app.config import settings

r: Optional[redis.Redis] = (
    redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    if settings.redis_url
    else None
)


def get_redis() -> Optional[redis.Redis]:
    """Trả về Redis client nếu REDIS_URL được cấu hình."""
    global r
    if r is None and settings.redis_url:
        r = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    return r


def redis_healthy() -> bool:
    """Kiểm tra kết nối tới Redis cho readiness probe (/ready)."""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False


def close_redis() -> None:
    """Đóng kết nối Redis khi shutdown."""
    global r
    if r is not None:
        try:
            r.close()
        except Exception:
            pass

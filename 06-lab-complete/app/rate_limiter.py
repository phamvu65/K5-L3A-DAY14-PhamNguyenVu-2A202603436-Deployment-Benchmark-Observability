"""
Rate limiting (tiêu chí 7).

Yêu cầu:
  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429, nên kèm header Retry-After
  • State lưu trong Redis để mọi worker / instance dùng chung và vẫn còn sau khi
    restart agent (script chấm sẽ restart agent để kiểm tra)
"""
import time
import uuid
from collections import defaultdict
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60
_local_windows: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str) -> None:
    """Kiểm tra sliding window rate limit 60s cho mỗi API key."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"

    client = get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()
            if int(count) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )
            member = f"{now}:{uuid.uuid4().hex[:8]}"
            pipe = client.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
            return
        except HTTPException:
            raise
        except Exception:
            pass

    # Fallback in-memory khi chạy không có Redis
    timestamps = [ts for ts in _local_windows[key] if ts > window_start]
    if len(timestamps) >= limit:
        _local_windows[key] = timestamps
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
    timestamps.append(now)
    _local_windows[key] = timestamps

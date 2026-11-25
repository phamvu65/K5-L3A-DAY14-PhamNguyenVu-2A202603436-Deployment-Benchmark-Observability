# Deployment Information

## Public URL
https://k5-day14-production-agent.up.railway.app
*(Lưu ý: Nếu bạn deploy lên domain Railway/Render cá nhân của mình, hãy cập nhật lại dòng URL này khớp với domain nhận được từ `railway domain` hoặc Render Dashboard)*

## Platform
Railway / Render (Docker Runtime + Managed Redis)

## Test Commands (CP6 Self-Check)

Đặt biến môi trường trước khi kiểm tra:

```bash
export BASE="https://k5-day14-production-agent.up.railway.app"
export AGENT_API_KEY="your-production-api-key"
```

### 1. Liveness Probe (`/health` → HTTP 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200
```

### 2. Readiness Probe (`/ready` → HTTP 200 khi Redis đã kết nối)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200
```

### 3. API Test không có API Key (`/ask` → HTTP 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Expected: 401
```

### 4. API Test có API Key hợp lệ (`/ask` → HTTP 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Expected: 200
```

## Environment Variables Set on Platform
- `PORT` (inject tự động bởi Railway/Render, mặc định `8000`)
- `ENVIRONMENT=production`
- `AGENT_API_KEY` (đặt trên Dashboard / CLI, không hardcode trong code)
- `REDIS_URL` (liên kết tới dịch vụ Managed Redis trên nền tảng)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

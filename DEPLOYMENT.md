# Deployment Information

## Public URL
https://k5-day14-production-agent-m4nh.onrender.com

## Platform
Render Blueprint (`render.yaml` — Docker Web Service `k5-day14-production-agent` + Managed Key Value Redis `k5-day14-redis`)

## Test Commands (CP6 Self-Check)

Đặt biến môi trường trước khi kiểm tra:

```bash
export BASE="https://k5-day14-production-agent-m4nh.onrender.com"
export AGENT_API_KEY="<your-render-generated-agent-api-key>"
```

### 1. Liveness Probe (`GET /health` → HTTP 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Output: 200
```
**Response JSON thực tế:**
```json
{"status":"ok","environment":"production"}
```

### 2. Readiness Probe (`GET /ready` → HTTP 200 khi Redis đã kết nối)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Output: 200
```
**Response JSON thực tế:**
```json
{"status":"ready","redis":"connected"}
```

### 3. API Test không có API Key (`POST /ask` → HTTP 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Output: 401
```

### 4. API Test có API Key hợp lệ (`POST /ask` → HTTP 200)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Output: 200
```
**Response JSON thực tế:**
```json
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","user_id":"anonymous","cost_usd":2.01e-05}
```

## Environment Variables Set on Platform
- `PORT` (inject tự động bởi Render)
- `ENVIRONMENT=production`
- `AGENT_API_KEY` (`generateValue: true` trên Render Dashboard, không hardcode trong code)
- `REDIS_URL` (tự động liên kết tới dịch vụ `k5-day14-redis` qua `fromService.connectionString`)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)

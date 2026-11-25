# Day 14 Lab — Mission Answers

> **Họ và tên:** Phạm Nguyên Vũ  
> **MSSV:** 2A202603436  
> **Lớp:** K5-L3A  
> **Bài lab:** Day 14 — Deployment, Benchmark & Observability

---

## Part 1: Localhost vs Production (CP1)

### Exercise 1.1: Các Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong mã nguồn** (dòng 17–18):
   ```python
   OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"
   DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"
   ```
   *Rủi ro:* Khi push code lên GitHub, API key và mật khẩu DB bị lộ ngay trong lịch sử git, kẻ tấn công có thể quét tự động để trục lợi tài khoản hoặc đánh cắp dữ liệu.
2. **Cấu hình cố định (Hardcoded Configuration) và bật `DEBUG = True` cố định** (dòng 21–22):
   ```python
   DEBUG = True
   MAX_TOKENS = 500
   ```
   *Rủi ro:* Vi phạm nguyên tắc III của 12-Factor App (*Store config in the environment*). Cùng một image không thể linh hoạt chuyển đổi giữa `development`, `staging`, `production` mà phải sửa code.
3. **Dùng `print()` thay vì Structured Logging và in cả Secret ra stdout** (dòng 33–38):
   ```python
   print(f"[DEBUG] Got question: {question}")
   print(f"[DEBUG] Using key: {OPENAI_API_KEY}")  # ❌ log ra secret!
   ```
   *Rủi ro:* Làm lộ API key trên hệ thống thu thập log tập trung; log dạng text tự do không có timestamp chuẩn, mức độ nghiêm trọng (`level`) hay JSON schema để parse/query trên Loki, Datadog, ELK.
4. **Không có Health Check (`/health`) và Readiness (`/ready`) endpoints** (dòng 42–43):
   *Rủi ro:* Các nền tảng container orchestration (Kubernetes, Railway, Render, Cloud Run) và Load Balancer không biết được process có còn sống hay đã sẵn sàng nhận traffic chưa để tự động restart hoặc ngắt route.
5. **Bind cứng `host="localhost"`, `port=8000` và bật `reload=True`** (dòng 49–54):
   ```python
   uvicorn.run("app:app", host="localhost", port=8000, reload=True)
   ```
   *Rủi ro:* Bind vào `localhost` (`127.0.0.1`) khiến container không nhận được kết nối từ bên ngoài network namespace (cần `0.0.0.0`); hardcode port `8000` sẽ lỗi trên cloud (Railway/Render cấp biến môi trường `$PORT` động); `reload=True` tốn CPU/RAM và không an toàn trong production.
6. **Không có cơ chế Graceful Shutdown (`SIGTERM` / FastAPI `lifespan`)**:
   *Rủi ro:* Khi deploy bản mới hoặc scale down, container bị tắt đột ngột làm đứt ngang các request LLM đang xử lý dở của người dùng.

---

### Exercise 1.2: Kết quả chạy bản `develop`

Chạy server `01-localhost-vs-production/develop/app.py` và gọi `curl -i -X POST "http://localhost:8000/ask?question=Hello"` (nhận `question` qua query parameter theo lưu ý K5):

```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 11:41:33 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

*Nhận xét:* App chạy được trên máy cá nhân nhưng hoàn toàn chưa sẵn sàng cho production vì mắc đủ 6 anti-patterns nêu ở Exercise 1.1.

---

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng trong Production? |
|---------|----------------------------|----------------------------------|--------------------------------------|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True` trong code (dòng 17–22) | Đọc qua `config.py` (`Settings` lấy từ `os.getenv`, `.env`) | Tách biệt code và config theo 12-Factor App; bảo mật tuyệt đối secret, dùng chung 1 Docker image cho mọi môi trường (dev/staging/prod). |
| **Health & Readiness** | Không có `/health` và `/ready` | Có `GET /health` (liveness + uptime) và `GET /ready` (readiness trả `503` khi chưa sẵn sàng, dòng 135–161) | Giúp Cloud Platform tự động restart container khi treo (`/health`) và giúp Load Balancer chỉ điều hướng traffic vào instance đã khởi tạo xong (`/ready`). |
| **Logging** | Dùng `print("[DEBUG]...")`, thậm chí in cả `OPENAI_API_KEY` ra màn hình | Structured JSON logging (`json.dumps` với `event`, `time`, `level`, không log secret, dòng 28–32, 111–122) | Log JSON dễ dàng được thu thập, đánh chỉ mục, lọc và cảnh báo tự động trên hệ thống Observability mà không làm rò rỉ dữ liệu nhạy cảm. |
| **Shutdown** | Tắt đột ngột khi nhận tín hiệu dừng, cắt ngang request đang chạy | Quản lý vòng đời qua `lifespan` + bắt tín hiệu `signal.SIGTERM` (dòng 39–68, 180–189) | Đảm bảo **Zero-downtime deployment**: khi rolling update hoặc scale down, instance ngừng nhận request mới nhưng vẫn xử lý nốt các request in-flight trước khi thoát. |
| **Network Binding & Port** | Cố định `host="localhost"`, `port=8000`, `reload=True` | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `$PORT`), tắt reload khi `DEBUG=false` (dòng 194–199) | Cho phép nhận kết nối từ bên ngoài container và tương thích với cơ chế cấp phát cổng động (`$PORT`) của Railway, Render, Cloud Run. |

---

## Part 2: Docker Containerization (CP2)

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - Base image là `python:3.11` (bản đầy đủ dựa trên Debian Bookworm, chứa sẵn cả trình biên dịch C/C++, header files, công cụ hệ thống nên rất nặng ~1 GB+).
2. **Working directory là gì?**
   - Là `/app` (được thiết lập bởi chỉ thị `WORKDIR /app` ở dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối tại thư mục này.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .` (copy mã nguồn)?**
   - Để tận dụng cơ chế **Docker Layer Caching**. Docker cache từng layer theo thứ tự chỉ thị: file `requirements.txt` ít khi thay đổi, còn mã nguồn (`app.py`) thay đổi liên tục. Khi đặt `COPY requirements.txt` và `RUN pip install` lên trước, mỗi lần sửa code `app.py`, Docker sẽ dùng lại layer cài thư viện đã cache sẵn thay vì phải tải và cài lại toàn bộ packages từ đầu (giúp giảm thời gian build từ vài phút xuống vài giây).
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - **`CMD`** định nghĩa lệnh mặc định và/hoặc tham số mặc định khi chạy container, nhưng **dễ dàng bị ghi đè hoàn toàn** nếu truyền lệnh mới ở cuối `docker run <image> <other_cmd>`.
   - **`ENTRYPOINT`** cố định chương trình thực thi chính của container (biến container thành một executable), các đối số truyền thêm vào `docker run` sẽ được nối vào làm tham số cho `ENTRYPOINT` (trừ khi dùng cờ `--entrypoint`).

---

### Exercise 2.2: Build và chạy `my-agent:develop`

Từ thư mục gốc của repo:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm --name p2-dev-test -p 8000:8000 my-agent:develop
curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
```

**Kết quả trả về từ container:**

```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 11:43:13 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

---

### Exercise 2.3: Multi-stage build & So sánh kích thước Image thực tế

- **Phân tích `02-docker/production/Dockerfile`:**
  - **Stage 1 (`builder` - `python:3.11-slim`):** Cài đặt các gói build hệ thống (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` để biên dịch các thư viện Python vào `/root/.local`.
  - **Stage 2 (`runtime` - `python:3.11-slim`):** Tạo user non-root (`appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` và mã nguồn (`main.py`, `utils/mock_llm.py`), khai báo `HEALTHCHECK` và chạy `uvicorn` với 2 workers dưới quyền `appuser`.
  - **Tại sao image nhỏ hơn?** Vì Stage 2 dùng base `python:3.11-slim` gọn nhẹ và loại bỏ hoàn toàn trình biên dịch `gcc`, `libpq-dev`, header C/C++ cùng pip cache ở Stage 1.

- **Kết quả đo bằng `docker images` và `docker image inspect` trên máy:**

```text
REPOSITORY      TAG        IMAGE ID       SIZE
my-agent        advanced   9b3233c54677   240MB
my-agent        develop    da9409c42fa2   1.67GB

# Kích thước image uncompressed (docker image inspect --format "{{.Size}}"):
my-agent:develop  -> 426,320,018 bytes (~406.57 MB uncompressed / 1,670 MB disk footprint trên Docker Desktop)
my-agent:advanced ->  57,409,152 bytes (~54.75 MB uncompressed  /   240 MB disk footprint trên Docker Desktop)
```

- **So sánh chênh lệch:**
  - **Develop (`my-agent:develop`):** `1670 MB` (`1.67 GB`)
  - **Production (`my-agent:advanced`):** `240 MB`
  - **Tỉ lệ giảm dung lượng:** Giảm **`85.63%`** (nhỏ hơn gần **7 lần** so với bản develop!).

---

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

- **Các services được khởi chạy trong stack:**
  1. `nginx` (`nginx:alpine`): Reverse proxy & Load balancer lắng nghe cổng `80`/`443` ngoài host, chuyển tiếp request vào `agent:8000`.
  2. `agent` (build từ `02-docker/production/Dockerfile` stage `runtime`): FastAPI AI Agent chạy cổng nội bộ `8000` (không expose trực tiếp ra host).
  3. `redis` (`redis:7-alpine`): Lưu trữ session cache & rate limiting ở cổng nội bộ `6379`.
  4. `qdrant` (`qdrant/qdrant:v1.9.0`): Vector database cho RAG ở cổng nội bộ `6333`.

- **Sơ đồ kiến trúc và giao tiếp (Bridge Network `internal`):**

```text
                        ┌──────────────────────────────────────────────────────┐
                        │               Docker Network: internal               │
┌──────────┐   :80/:443 │  ┌───────────────┐        :8000      ┌────────────┐  │
│  Client  │ ─────────▶ │  │     nginx     │ ───────────────▶  │   agent    │  │
└──────────┘            │  │ (nginx:alpine)│                   │ (FastAPI)  │  │
                        │  └───────────────┘                   └─────┬──────┘  │
                        │                                            │         │
                        │                            ┌───────────────┴──────┐  │
                        │                            ▼ :6379                ▼ :6333
                        │                     ┌─────────────┐        ┌────────────┐
                        │                     │    redis    │        │   qdrant   │
                        │                     │ (7-alpine)  │        │  (v1.9.0)  │
                        │                     └─────────────┘        └────────────┘
                        └──────────────────────────────────────────────────────┘
```

---

## Part 3: Cloud Deployment (CP6)

### Exercise 3.1 / 3.2: Triển khai Agent Part 6 (`06-lab-complete/`) lên Cloud

- **Thư mục triển khai:** `06-lab-complete/` (theo quy định K5: deploy trực tiếp agent Part 6 đã đạt `PASS 12/12` kèm dịch vụ Redis).
- **Thông tin chi tiết và lệnh kiểm thử 4 bước (200 / 200 / 401 / 200):** Xem tại file [DEPLOYMENT.md](DEPLOYMENT.md).

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Tại sao có sự khác biệt? |
|----------|--------------------------|----------------------------------|--------------------------|
| **Định dạng & Phạm vi** | File TOML cấu hình build & deploy cho **1 service** đơn lẻ trong thư mục hiện tại. | File YAML (Infrastructure as Code Blueprint) khai báo **toàn bộ kiến trúc nhiều services** (cả Web Service lẫn Redis instance) trong một file. | Railway quản lý đa dịch vụ trên Canvas/Project UI và CLI, còn Render hướng tới mô hình Declarative Blueprint đồng bộ toàn bộ hạ tầng từ Git. |
| **Cách khai báo Build** | `[build] builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`). | `runtime: docker` (hoặc `runtime: python` kèm `buildCommand` và `startCommand`). | Railway mặc định ưu tiên tự nhận diện qua Nixpacks/Dockerfile, trong khi Render yêu cầu chỉ định rõ `type: web` và `runtime`. |
| **Quản lý Biến môi trường & Secrets** | Không khai báo `envVars` trong `railway.toml`; đặt qua CLI (`railway variables set`) hoặc Dashboard. | Khai báo trực tiếp danh sách `envVars` trong `render.yaml`; bảo vệ secret bằng `generateValue: true` hoặc `sync: false`, và nối `REDIS_URL` tự động qua `fromService`. | Render Blueprint cho phép liên kết biến môi trường giữa các tài nguyên (Web ↔ Redis) ngay trong file YAML mà vẫn không lộ secret trong Git. |
| **Health Check & Restart** | `[deploy] healthcheckPath = "/health"`, có thêm `restartPolicyType = "ON_FAILURE"` và `restartPolicyMaxRetries`. | `healthCheckPath: /health` nằm trực tiếp trong định nghĩa service `type: web`. | Railway cho phép cấu hình tinh chỉnh chính sách restart khi container crash ngay trong file cấu hình. |

---

### Exercise 3.3: Mô tả CI/CD Pipeline trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`, quy trình CI/CD tự động khi có commit lên nhánh `main` đi qua **4 bước tuần tự**:
1. **Step 1 (`test`):** Dùng container `python:3.11-slim` cài đặt dependencies từ `requirements.txt` và chạy bộ kiểm thử tự động `pytest tests/ -v --tb=short`; nếu bất kỳ test nào fail thì pipeline dừng ngay lập tức.
2. **Step 2 (`build` — `waitFor: [test]`):** Dùng `gcr.io/cloud-builders/docker` build Docker image gắn 2 tag (`:$COMMIT_SHA` để định danh chính xác bản build và `:latest`), đồng thời tận dụng `--cache-from` để tăng tốc độ build layer.
3. **Step 3 (`push` — `waitFor: [build]`):** Đẩy toàn bộ các tag của image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Step 4 (`deploy` — `waitFor: [push]`):** Dùng `gcloud run deploy` triển khai image `:$COMMIT_SHA` lên Cloud Run tại region `asia-southeast1`. Cấu hình vận hành (tương ứng trong `service.yaml` chuẩn Knative): giữ `min-instances=1` (`minScale: "1"`) để tránh cold start, `max-instances=10` (`maxScale: "10"`), giới hạn `containerConcurrency: 80`, cấp `512Mi` RAM / `1` vCPU, tiêm secret `OPENAI_API_KEY` và `AGENT_API_KEY` an toàn từ **Google Secret Manager** (`secretKeyRef`), và giám sát bằng `startupProbe` (`/ready`) cùng `livenessProbe` (`/health`).

---

## Part 4: API Security (CP3)

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Trong dependency `verify_api_key(api_key: str = Security(api_key_header))` (dòng 39–54), được gắn vào endpoint `POST /ask` qua `_key: str = Depends(verify_api_key)` (dòng 70).
- **Điều gì xảy ra nếu thiếu hoặc sai key?**
  - Không gửi header `X-API-Key` → Trả về **`HTTP 401 Unauthorized`**.
  - Gửi sai giá trị `X-API-Key` → Trả về **`HTTP 403 Forbidden`** (trong bản develop Part 4) hoặc **`HTTP 401 Unauthorized`** (theo chuẩn Hợp đồng Part 6).
- **Làm sao để rotate key không gây downtime?** Lưu danh sách các key hợp lệ (ví dụ `ACTIVE_API_KEYS` trong Redis hoặc biến môi trường phân tách bằng dấu phẩy gồm cả `old_key` và `new_key`), cấp `new_key` cho client chuyển đổi trong thời gian ân hạn (grace period), sau đó thu hồi `old_key`.

**Kết quả test thực tế với `curl -i` (`AGENT_API_KEY=secret-key-123`):**

1. **Khi không có API Key (`401 Unauthorized`):**
```http
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 11:43:15 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

2. **Khi có API Key hợp lệ (`200 OK`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 11:43:15 GMT
server: uvicorn
content-length: 122
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Phân tích `rate_limiter.py`:**
  - **Thuật toán sử dụng:** **Sliding Window Counter / Log** (lưu `deque` chứa các timestamps request của từng `user_id` trong cửa sổ trượt `60 giây`; mỗi khi có request mới sẽ loại bỏ các timestamps `< now - 60`).
  - **Giới hạn (Limit):** Tài khoản role `user` (`student` / `demo123`) bị giới hạn **10 requests / phút** (`rate_limiter_user`), còn role `admin` (`teacher` / `teach456`) có giới hạn **100 requests / phút** (`rate_limiter_admin`).
  - **Cách phân quyền / bypass cho admin:** Trong `app.py` (dòng 141), hệ thống đọc trường `role` từ payload của JWT token (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`) để áp dụng hạn mức cao hơn hoặc bỏ qua giới hạn cho admin.

**Kết quả chạy thực tế `curl -i` với tài khoản `student` / `demo123` (đã che JWT token):**

1. **Gọi `POST /ask` khi không có JWT Token (`401 Unauthorized`):**
```http
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 11:43:19 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

2. **Lấy JWT Token tại `POST /auth/token` với `student` / `demo123` và gọi `POST /ask` (`200 OK`):**
```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 11:43:19 GMT
server: uvicorn
content-length: 215
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```
*(Header đã gửi: `Authorization: Bearer <REDACTED_JWT_TOKEN>`)*

3. **Vòng lặp gọi liên tiếp vượt ngưỡng 10 req/phút (`429 Too Many Requests`):**
```text
Request #1 (cộng 1 request ở bước trên = 2) -> HTTP 200
Request #2 -> HTTP 200
Request #3 -> HTTP 200
Request #4 -> HTTP 200
Request #5 -> HTTP 200
Request #6 -> HTTP 200
Request #7 -> HTTP 200
Request #8 -> HTTP 200
Request #9 (đạt 10/10 req/phút) -> HTTP 200
Request #10 -> HTTP 429
```

**Output chi tiết `curl -i` khi chạm ngưỡng Rate Limit (`HTTP 429`):**
```http
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 11:43:21 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795607061
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

---

### Exercise 4.4: Giải thích cơ chế Cost Guard & Tại sao cần cả Rate Limit lẫn Cost Guard

- **Cách triển khai Cost Guard với Redis:**
  1. Định nghĩa đơn giá theo model (ví dụ `PRICE_INPUT_PER_1K = $0.00015`, `PRICE_OUTPUT_PER_1K = $0.0006`).
  2. Tạo key Redis theo chu kỳ ngày hoặc tháng, ví dụ `cost:daily:<YYYY-MM-DD>:<api_key_or_user_id>`.
  3. **Trước khi gọi LLM (`check_budget`):** Đọc tổng số tiền đã tiêu từ Redis (`GET`). Nếu `spent >= DAILY_BUDGET_USD`, chặn ngay lập tức bằng mã **`HTTP 402 Payment Required`** (hoặc `503` nếu vượt ngân sách toàn hệ thống).
  4. **Sau khi gọi LLM (`record_cost`):** Tính chi phí thực tế của request từ `input_tokens` và `output_tokens`, dùng lệnh nguyên tử `INCRBYFLOAT` cộng dồn vào key Redis và đặt `EXPIRE` (ví dụ 48 giờ cho ngân sách ngày hoặc 32 ngày cho ngân sách tháng) để tự động giải phóng bộ nhớ.
- **Tại sao cần cả Rate Limit lẫn Cost Guard?**
  - **Rate Limit bảo vệ tốc độ (Throughput / Infrastructure):** Ngăn chặn DDoS hoặc спаm tần suất cao trong thời gian ngắn (ví dụ 100 req/giây làm nghẽn worker).
  - **Cost Guard bảo vệ ngân sách tài chính (Financial Budget):** Một user có thể gửi đúng 10 req/phút (không bao giờ vi phạm Rate Limit), nhưng mỗi request lại gửi prompt dài hàng chục nghìn token hoặc chạy liên tục 24/24 giờ, dẫn tới hóa đơn LLM hàng trăm USD mỗi ngày. Cost Guard đặt trần chi tiêu tuyệt đối theo USD.

---

## Part 5: Scaling & Reliability (CP4)

### Exercise 5.1–5.3: Liveness vs Readiness, Graceful Shutdown và Thiết kế Stateless

1. **Sự khác biệt giữa Liveness (`GET /health`) và Readiness (`GET /ready`):**
   - **Liveness Probe (`/health`):** Trả lời câu hỏi *"Process của container còn sống hay bị treo/deadlock?"*. Luôn trả về `HTTP 200` khi process FastAPI/Uvicorn còn hoạt động (kể cả khi Redis tạm thời mất kết nối). Nếu `/health` trả lỗi, nền tảng sẽ **kill và restart container**.
   - **Readiness Probe (`/ready`):** Trả lời câu hỏi *"Instance này có đủ điều kiện xử lý request ngay lúc này không?"*. Nó kiểm tra kết nối tới các phụ thuộc sống còn như **Redis / Database** (`redis.ping()`). Nếu Redis mất kết nối, `/ready` trả `HTTP 503 Service Unavailable` để Load Balancer **tạm ngừng gửi traffic tới instance đó**, nhưng **không restart container** (tránh vòng lặp crash-loop vô ích khi lỗi nằm ở Redis chứ không phải ở app).
2. **Graceful Shutdown (`SIGTERM`):**
   - Khi orchestrator dừng container, nó gửi tín hiệu `SIGTERM`. Nhờ Uvicorn chạy ở PID 1 (`exec uvicorn ...`) kết hợp với `lifespan` của FastAPI, agent ngừng nhận kết nối mới, đợi các request đang xử lý (`in-flight`) hoàn tất, đóng kết nối Redis sạch sẽ rồi mới thoát với `exit code 0`.
3. **Vì sao lưu state trong RAM bị hỏng khi chạy nhiều instance?**
   - Mỗi container instance có không gian bộ nhớ (RAM) độc lập. Khi chạy 3 replicas sau Nginx Load Balancer (phân phối kiểu Round-Robin), Request 1 của User A rơi vào `Instance 1` (lưu lịch sử hội thoại hoặc bộ đếm rate limit vào RAM của `Instance 1`), nhưng Request 2 lại được Nginx đẩy sang `Instance 2` (RAM trống) → Agent mất ngữ cảnh hội thoại và bộ đếm Rate Limit bị nhân lên gấp $N$ lần số replicas. Chuyển toàn bộ state sang **Redis** biến các agent thành **Stateless**, instance nào cũng đọc/ghi chung một nguồn dữ liệu thống nhất.

---

### Exercise 5.4 & 5.5: Kết quả chạy Load Balancing 3 Instances & `test_stateless.py`

Chạy trong `05-scaling-reliability/production/` theo đúng hướng dẫn K5 (cổng `8080`, endpoint `POST /chat`, project `-p k5-day14-scaling`):

```bash
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
docker compose -p k5-day14-scaling down -v
```

**Output thực tế của `python test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 3a6ef720-9dbc-4e3d-8113-e073e112560c

Request 1: [instance-0b84d2]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-68d5fd]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-6af5c4]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-0b84d2]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-68d5fd]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-68d5fd', 'instance-6af5c4', 'instance-0b84d2'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

*Giải thích kết quả:* 5 câu hỏi trong cùng một `session_id` (`3a6ef720-9dbc-4e3d-8113-e073e112560c`) đã được Nginx phân phối luân phiên (round-robin) qua cả 3 instance (`instance-0b84d2`, `instance-68d5fd`, `instance-6af5c4`). Khi gọi `GET /chat/{session_id}/history`, toàn bộ 10 messages (5 cặp user/assistant) đều được bảo toàn nguyên vẹn nhờ lưu trữ tập trung trong Redis.

---

## Part 6: Final Project — Production Readiness Check (CP5)

Kết quả chạy `python check_production_ready.py` (chế độ đầy đủ có Docker trong môi trường POSIX/WSL2) tại thư mục `06-lab-complete/`:

```text
================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 27s
     ✅ Docker: image < 500 MB — 56 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 2

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.9s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log (Theo quy định tại `RULES.md`)

1. **Hỏi & Gợi ý kiến trúc Part 6 (`06-lab-complete/`):**
   - **Nội dung hỏi:** Cách tổ chức các module `config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py` và `Dockerfile` multi-stage để thoả mãn 12 tiêu chí trong `06-lab-complete/README.md`.
   - **Nhận được:** Cấu trúc code gợi ý dùng `APIKeyHeader(auto_error=False)` trả `401`, Redis Sorted Set (`ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`, `EXPIRE`) cho sliding window rate limit 60s, `INCRBYFLOAT` cho cost guard, `JsonFormatter` cho structured logging, và `lifespan` kết hợp chuyển tiếp `SIGTERM` handler của Uvicorn.
   - **Tự sửa & Kiểm tra:** Khởi tạo Redis client dạng lazy (không gọi `.ping()` lúc import để container khởi động được khi chưa có Redis), dùng `exec uvicorn` làm PID 1 trong `Dockerfile`, và chạy kiểm chứng thực tế bằng `python check_production_ready.py` trong WSL2 đạt `12/12 tiêu chí đạt · 43/43 checks passed`.
2. **Hỏi & Phân tích câu hỏi lý thuyết Part 1–5 và sửa `KNOWLEDGE_BASE` ở Part 7:**
   - **Nội dung hỏi:** Tổng hợp so sánh 12-Factor App, multi-stage Docker build, sự khác biệt giữa `railway.toml` / `render.yaml` / `cloudbuild.yaml`, và tra cứu keyword bị thiếu của 2 câu hỏi fail trong `golden_dataset.jsonl` (`security-02`, `scaling-03`).
   - **Nhận được:** Gợi ý bổ sung entry về JWT (`token`, `hết hạn`, `chữ ký`) và Kubernetes HPA (`cpu`, `memory`, `custom metrics`) vào `KNOWLEDGE_BASE` trong `mock_llm.py`.
   - **Tự sửa & Kiểm tra:** Tự chạy toàn bộ lệnh thực nghiệm trên máy (Part 1, 2, 4, 5, 6, 7), lấy đúng kết quả đo thực tế (`docker images`, `curl -i`, `test_stateless.py`, `load_test.py`, `run_eval.py`, Locust CSV) để đưa vào báo cáo.

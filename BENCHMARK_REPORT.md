# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Phạm Nguyên Vũ (MSSV: 2A202603436)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + WSL2 Ubuntu (CPython 3.11.18), Docker Desktop 29.6.2 (Docker Compose v5.3.1)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500** ms | Đảm bảo 95% người dùng nhận được phản hồi tương tác tức thì (< 0.5 giây); p95 phản ánh trải nghiệm thực tế tốt hơn average vì không bị che khuất bởi các request nhanh và cũng không quá nhạy với 1% outlier cực đoan như p99. |
| Error rate `/ask` | < **2.0** % | Chấp nhận tỷ lệ lỗi transient nhỏ từ LLM provider bên thứ ba (~1% upstream 503/timeout), dành ra 2% Error Budget để có thể retry ở tầng client mà không gây gián đoạn dịch vụ hay báo động giả (alert fatigue). |
| Accuracy trên golden dataset | ≥ **85.0** % (Mục tiêu sau khi fix KB: **100.0** %) | Ngưỡng Quality Gate tối thiểu trước khi deploy để đảm bảo pipeline RAG trả lời chính xác kiến thức domain và chặn tự động mọi commit gây regression so với baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

*(Số liệu trích xuất trực tiếp từ `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` với `--requests 300`)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.04 | 198.7 | 227.2 | 1719.9 | 0.33% | ✅ PASS |
| 10 | 34.64 | 202.8 | 256.6 | 1708.4 | 1.00% | ✅ PASS |
| 50 | 90.94 | 240.6 | 653.8 | 1756.3 | 1.00% | ❌ FAIL (p95 > 500ms) |
| 100 | 46.96 | 812.1 | 4208.7 | 4751.4 | 1.00% | ❌ FAIL (p95 > 500ms) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **RPS không tăng tuyến tính theo concurrency** khi vượt ngưỡng bão hòa:
  - Ở giai đoạn đầu từ `concurrency = 1` lên `concurrency = 10`, RPS tăng gần tuyến tính (**8.57 lần**, từ `4.04` lên `34.64 req/s`) trong khi `p50` (~202.8ms) và `p95` (~256.6ms) hầu như không đổi vì `asyncio` event loop tận dụng tốt thời gian chờ I/O (`await asyncio.sleep`) của Mock LLM.
  - Khi tăng lên `concurrency = 50` (tăng 5 lần so với 10), RPS chỉ tăng **2.63 lần** (đạt đỉnh `90.94 req/s`), nhưng `p95` đã vọt lên `653.8 ms` (vượt ngưỡng SLO 500ms).
  - Khi đẩy lên `concurrency = 100`, hệ thống rơi vào trạng thái **quá tải (thrashing / queueing contention)** trên 1 worker process đơn lẻ: RPS **sụt giảm ngược** xuống còn `46.96 req/s`, `p50` tăng gấp 4 lần lên `812.1 ms` và `p95` vọt lên tới `4208.7 ms` (theo Định luật Little $L = \lambda W$ và Universal Scalability Law: chi phí lập lịch hàng trăm coroutine + overhead xử lý HTTP/JSON trên 1 tiến trình Python đơn nhân làm thời gian xếp hàng tăng vọt).

### 2.2 Tail latency

*(Số liệu trích xuất trực tiếp từ `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` với `--requests 300 --concurrency 20`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 210.9 | 252.5 | 289.4 |
| 0.03 (mặc định) | 245.5 | 256.4 | 1707.0 |
| 0.1 | 297.7 | 1682.1 | 1727.4 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Chỉ số nhạy nhất với tỷ lệ nhỏ request chậm (3%) là `p99`** (tăng vọt từ `289.4 ms` lên **`1707.0 ms`**, tức tăng gần **6 lần** khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03`, trong khi `avg` chỉ nhích nhẹ từ `210.9 ms` lên `245.5 ms` và `p95` giữ nguyên ở `256.4 ms`). Khi tỷ lệ request chậm vượt quá 5% (`MOCK_SLOW_RATE = 0.1`, tức 10% request bị chậm), cả **`p95`** cũng nhảy vọt lên **`1682.1 ms`** (gấp 6.5 lần).
- **SLO tuyệt đối không nên đặt theo `average` (trung bình cộng)** vì ngay cả khi có tới **10% người dùng phải chờ ~1.7 giây** (`MOCK_SLOW_RATE = 0.1`), chỉ số `avg` vẫn chỉ ở mức **`297.7 ms`** (nhìn rất đẹp và thấp hơn nhiều so với ngưỡng 500ms). Trung bình cộng trộn lẫn 90% request nhanh (~200ms) với 10% request cực chậm (~1700ms), che giấu hoàn toàn trải nghiệm tồi tệ ở phần đuôi phân phối (**tail latency**). Dùng `p95` và `p99` buộc hệ thống phải đảm bảo chất lượng phục vụ cho cả nhóm 5% và 1% người dùng chịu độ trễ cao nhất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Số liệu trích xuất trực tiếp từ `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | **4.3%** (1/23) | **91.3%** (21/23) | **100.0%** (23/23) |
| Avg tokens / câu | 57.9 | 109.0 | 113.9 |
| Tổng cost (USD) | $0.000415 | $0.000760 | $0.000792 |
| Cost / câu đúng (USD) | $0.00041535 | $0.00003619 | $0.00003445 |
| Quality gate | ❌ FAIL | ✅ PASS (≥ 80%) | ✅ PASS (100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt", "api key", "xác thực"], "JWT là token tự chứa thông tin (payload), có thời gian hết hạn (exp) và chữ ký số (signature) để server xác thực mà không cần tra database mỗi lần như API key tĩnh.")` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["kubernetes", "hpa", "horizontal pod autoscaler"], "Kubernetes HPA (Horizontal Pod Autoscaler) tự động scale số lượng pod dựa trên chỉ số CPU, memory hoặc custom metrics như số request mỗi giây.")` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |

**Cách dùng exit code của `run_eval.py` làm Quality Gate trong CI/CD (Exercise 7.3):**

Script `eval/run_eval.py` trả về **`exit code 0`** khi `accuracy >= --min-accuracy` và `regressions == 0`, ngược lại trả về **`exit code 1`**. Trong GitHub Actions (hoặc GitLab CI), mọi step có exit code khác 0 sẽ tự động đánh dấu pipeline **FAILED** và chặn không cho merge Pull Request:

```yaml
# .github/workflows/eval-quality-gate.yml
name: AI Agent Quality Gate
on: [pull_request]
jobs:
  eval-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies & start Agent v2
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 PORT=8002 python app.py &
          sleep 3
      - name: Run Golden Dataset Evaluation & Regression Gate
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          python eval/run_eval.py \
            --url http://localhost:8002 \
            --min-accuracy 0.95 \
            --baseline reports/eval_v2.json \
            --out reports/eval_ci.json
```

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Latency & Token Cost tăng nhẹ:** Agent v2 có thêm bước RAG retrieval (`search_knowledge_base` ~20ms) và chèn tài liệu tìm được vào prompt nên `p50 latency` tăng từ `170.9 ms` lên `202.7 ms`, số token trung bình mỗi câu tăng gần gấp đôi từ `57.9` lên `113.9 tokens` (tổng chi phí cho 23 câu tăng từ `$0.000415` lên `$0.000792`).
- **Hiệu quả kinh tế thực tế (`Cost / câu đúng`) vượt trội hoàn toàn:** Vì v1 không có context nên trả lời chung chung, chỉ đúng `1/23` câu (`4.3%`), dẫn đến chi phí cho mỗi câu trả lời đúng là **`$0.00041535`**. Ngược lại, v2 (sau khi bổ sung KB) trả lời đúng `23/23` câu (`100%`), giúp chi phí trên mỗi câu trả lời đúng giảm xuống chỉ còn **`$0.00003445`** — **rẻ hơn gấp 12 lần** so với v1! Điều này chứng minh không nên chỉ nhìn vào "chi phí trên mỗi request" mà phải đánh giá theo **"chi phí trên mỗi kết quả đúng" (Cost per Correct Answer)**.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

*(Ghi chú trả lời Exercise 7.4:*
1. *Khoảng cách giữa `avg` (~220ms) và `p95`/`p99` (~1.7s) trên Grafana phản ánh rõ hiện tượng **tail latency** do 3% request rơi vào nhánh `MOCK_SLOW_MS=1500ms`.*
2. *Trên panel Token rate, **input tokens/s luôn cao hơn gấp đôi output tokens/s** vì ở bản v2 (RAG), mỗi request đều ghép thêm `SYSTEM_PROMPT` + đoạn tài liệu `context` từ Knowledge Base + câu hỏi vào input prompt, trong khi câu trả lời output ngắn gọn.*
3. *Nginx chặn `location = /metrics { return 404; }` để không lộ thông tin nhạy cảm về kiến trúc nội bộ, lưu lượng, chi phí LLM và tên model ra Internet; chỉ Prometheus nằm trong cùng mạng nội bộ Docker `obs_net` mới scrape trực tiếp `agent:8000/metrics` qua DNS Service Discovery).*

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`severity: critical`) | **~75 giây** (15s cửa sổ rate vượt 5% + `for: 1m`) | Panel **Error rate (5xx)** trên hàng Golden Signals chuyển sang màu đỏ (> 5%) & panel **HTTP requests/s theo status** xuất hiện dải `503`. |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`severity: warning`) | **~135 giây** (15s để bucket p95 vượt 1s + `for: 2m`) | Panel **p95 latency** (Golden Signals) đổi sang màu đỏ (~1.7s) và biểu đồ **HTTP latency (/ask) — p50 / p95 / p99 vs average** thấy đường p95 tách hẳn lên trên avg. |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`severity: warning`) và `AgentHighLatencyP95` | **~135–150 giây** (`for: 2m` khi tốc độ chi tiêu vượt $2/giờ) | Panel **Cost ước tính / giờ** tăng vọt ~16.7 lần (vượt ngưỡng $2/h) và panel **LLM call latency (p50 / p95 / p99)** tăng gấp ~2.5 lần do `latency_factor=2.5`. |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`severity: critical`) | **~35–40 giây** (1 chu kỳ scrape 5s timeout + `for: 30s`) | Panel **Instances up** giảm đi 1 (ví dụ từ 3 xuống 2) và panel **Requests/s theo instance** thấy đường traffic của instance bị pause rơi về 0 (Locust ghi nhận vài lỗi 504 lúc Nginx chờ timeout 10s trước khi failover). |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** (tất cả đều `inactive` / xanh) | **Không bao giờ firing** | Panel **Retrieval hit ratio** rơi về `0%`, **Token/s (input)** giảm gần một nửa, và bảng **Phiên bản đang chạy** đổi từ `v2` sang `v1`, nhưng mọi panel Golden Signals hạ tầng đều xanh. |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

- Sự cố ở Thí nghiệm E là **suy giảm chất lượng câu trả lời (Quality / Silent Regression)** chứ không phải lỗi hạ tầng: HTTP vẫn trả `200 OK`, latency thậm chí còn nhanh hơn và tốn ít tiền hơn vì bỏ qua bước RAG retrieval, nên các alert dựa trên Golden Signals (`5xx`, `latency`, `up`, `cost`) hoàn toàn không phát hiện được.
- Để bắt được loại sự cố này trong production, cần kết hợp **3 lớp bảo vệ**:
  1. **Trước khi deploy (CI/CD Quality Gate):** Chạy tự động `eval/run_eval.py` trên Golden Dataset trong pipeline CI để chặn ngay các bản build/config làm tụt accuracy (từ 100% xuống 4.3%).
  2. **Metric nghiệp vụ & RAG Pipeline Alert:** Đặt alert trên metric đặc thù của pipeline AI như **`RetrievalHitRatioTooLow`** (ví dụ: `sum(rate(retrieval_hits_total{hit="true"}[5m])) / sum(rate(retrieval_hits_total[5m])) < 0.5` trong `2m`) hoặc cảnh báo khi số `input_tokens` trung bình mỗi request sụt giảm đột ngột (dấu hiệu mất context RAG).
  3. **Online Evaluation & User Feedback Monitoring:** Chạy **LLM-as-a-Judge** chấm điểm ngẫu nhiên 1–5% luồng hội thoại thực tế (online sampling) kết hợp theo dõi tỷ lệ người dùng bấm nút 👎 (*thumbs-down / regeneration rate*).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được từ Jaeger (`http://localhost:16686`, service `observable-agent`):

- `trace_id`: `388078c5a462dbb6c273b9ffa2b60290`
- Tổng thời gian: **1732.6 ms**
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1688.36 ms**, chiếm **97.45%** tổng thời gian request; trong khi span `agent.retrieve_context` chỉ mất **35.05 ms** ~ 2.02%). Điều này chỉ ra chính xác nút thắt cổ chai nằm ở bước gọi LLM upstream chứ không phải ở bước tìm kiếm Knowledge Base hay xử lý HTTP của FastAPI.
- Dòng log tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-25T12:00:04.681252+00:00", "level": "INFO", "service": "observable-agent", "instance": "8888e53140dc", "event": "llm_call", "trace_id": "388078c5a462dbb6c273b9ffa2b60290", "span_id": "5ab669c4316087c1", "request_id": "badf1d96ab46", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1688.3}
{"ts": "2026-11-25T12:00:04.682912+00:00", "level": "INFO", "service": "observable-agent", "instance": "8888e53140dc", "event": "http_request", "trace_id": "388078c5a462dbb6c273b9ffa2b60290", "span_id": "5ab669c4316087c1", "request_id": "badf1d96ab46", "method": "POST", "route": "/ask", "status": 200, "ms": 1732.6}
```

*(Và một dòng log của **trace lỗi** `error=true` tương ứng trong Jaeger để đối chiếu ảnh `jaeger-error-trace.png`):*
```json
{"ts": "2026-11-25T12:00:00.988688+00:00", "level": "INFO", "service": "observable-agent", "instance": "8888e53140dc", "event": "llm_error", "trace_id": "670f8ce94bd0aa17c38bf78ac09996e3", "span_id": "91856b18b271314c", "request_id": "a0a6278dc740", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu trích xuất chính xác từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`)*

| Số instance | Endpoint | Requests | RPS | avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|---|---|---|
| **1** | `POST /ask` | 6415 | **53.71** | 413.83 | **230** | **1500** | **2200** | **53** (0.83%) |
| **1** | `Aggregated` | 7055 | **59.07** | 387.16 | **220** | **1400** | **2200** | **53** (0.75%) |
| **3** | `POST /ask` | 6845 | **57.20** | 307.72 | **210** | **1000** | **1700** | **69** (1.01%) |
| **3** | `Aggregated` | 7556 | **63.14** | 283.15 | **210** | **890** | **1700** | **69** (0.91%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

1. **Scale từ 1 lên 3 instances CÓ cải thiện rõ rệt độ trễ xếp hàng (Queueing Latency):**
   - Với `100 concurrent users` của Locust dồn vào **1 instance** duy nhất (giới hạn `0.5 CPU`), event loop bị nghẽn nhẹ làm cả `GET /health` cũng bị kéo chậm theo (`avg = 119.8 ms`, `p95 = 580 ms`) và `POST /ask` có `avg = 413.83 ms`, `p95 = 1500 ms`, `p99 = 2200 ms`.
   - Khi scale lên **3 instances** (tải mỗi instance giảm còn ~33 users), hiện tượng nghẽn CPU/event-loop tại tầng ứng dụng biến mất: độ trễ `GET /health` giảm mạnh (`p50` còn `9 ms`, `avg` còn `46.56 ms`), còn với `POST /ask` thì `avg` giảm **25.6%** (từ `413.83 ms` xuống `307.72 ms`), **`p95` giảm từ `1500 ms` xuống `1000 ms`** (`Aggregated p95` giảm từ `1400 ms` xuống `890 ms`), và **`p99` giảm từ `2200 ms` xuống `1700 ms`** (đúng bằng ngưỡng trần tự nhiên của `MOCK_SLOW_MS = 1500ms` + base latency ~200ms).
2. **Tại sao RPS chỉ tăng nhẹ (từ `59.07` lên `63.14 req/s`) và `p50` gần như giữ nguyên quanh `210 ms`? Nút thắt (Bottleneck) nằm ở đâu?**
   - **Thứ nhất — Nút thắt độ trễ nằm ở Upstream LLM I/O (`chat mock-llm-small`):** Mỗi request `/ask` bắt buộc phải chờ `search_knowledge_base` (~20ms) + `mock_llm.generate` (~150–180ms, và 3% request mất ~1700ms). Việc scale ngang thêm container FastAPI chỉ giúp giải quyết CPU/queueing tại tầng web server của chúng ta, chứ **không làm cho API của OpenAI/Anthropic (hay Mock LLM) trả lời nhanh hơn** cho một request đơn lẻ (do đó `p50` không thể thấp hơn ~200ms và `p99` không thể thấp hơn ~1700ms).
   - **Thứ hai — Giới hạn Throughput bởi Pacing (`wait_time`) của 100 Locust Users:** Trong `locustfile.py`, mỗi user ảo sau khi nhận kết quả đều nghỉ `wait_time = between(0.5, 2.0)` (trung bình nghỉ `1.25 giây`). Theo Định luật Little, với $N = 100$ users và chu kỳ mỗi vòng lặp $T_{\text{cycle}} = T_{\text{wait}} + T_{\text{response}} \approx 1.25\text{s} + 0.28\text{s} = 1.53\text{s}$, thông lượng tối đa mà 100 users này có thể sinh ra là $\text{RPS}_{\max} = \frac{100}{1.53} \approx 65.3\text{ req/s}$. Ở mức 3 instances, hệ thống đã đạt `63.14 req/s` (sát trần lý thuyết của 100 users có think-time).

---

## 6. Kết luận

- **3 điều học được về Benchmark & Observability:**
  1. **Không bao giờ đánh giá hiệu năng qua Average Latency hay đánh giá chi phí qua Cost/Request:** Average che giấu hoàn toàn **tail latency** (`p95`/`p99`) của nhóm người dùng chịu trải nghiệm tệ nhất; tương tự, một kiến trúc RAG (v2) dù tốn gấp đôi token mỗi câu nhưng lại giúp **Cost per Correct Answer** rẻ hơn 12 lần so với bản không có retrieval (v1).
  2. **Observability hạ tầng (Metrics/Traces/Logs) và Đánh giá chất lượng AI (Eval) là hai mảnh ghép bắt buộc phải đi cùng nhau:** Prometheus/Grafana phát hiện rất nhanh lỗi 5xx, nghẽn latency, sập container hay đốt tiền LLM (`LLMCostBurnRateHigh`), nhưng hoàn toàn "mù" trước lỗi suy giảm chất lượng câu trả lời (như khi tụt về v1 ở Thí nghiệm E) — thứ chỉ có Golden Dataset Evaluation & Quality Gate mới chặn được.
  3. **Sức mạnh của sự liên kết 3 trụ cột (Metrics → Traces → Logs qua `trace_id`):** Khi Grafana báo động `p95` tăng cao, ta dùng Jaeger lọc trace chậm nhất để biết chính xác span nào là thủ phạm (`chat mock-llm-small` chiếm 97.45% thời gian thay vì đổ lỗi cho code Python hay Vector DB), rồi dùng `trace_id` truy ngược ra dòng log JSON chứa đầy đủ thông số token và chi phí của đúng request đó.

- **Nếu đưa agent này lên production thật, các metric / alert cần bổ sung thêm:**
  1. **LLM Streaming Metrics:** `llm_time_to_first_token_seconds` (**TTFT** — thời gian tới token đầu tiên) và `llm_inter_token_latency_seconds` (**ITL** / tokens per second), vì với ứng dụng chat streaming, người dùng cảm nhận độ mượt qua TTFT chứ không chỉ tổng thời gian hoàn tất câu trả lời.
  2. **RAG & Guardrail Quality Metrics:** `rag_retrieval_similarity_score` (histogram điểm tương đồng cosine của tài liệu lấy ra từ Vector DB), `rag_empty_context_ratio` (tỷ lệ không tìm thấy tài liệu liên quan), và `agent_user_feedback_total{rating="thumbs_up|thumbs_down"}`.
  3. **Security & Cache Efficiency Metrics:** `rate_limit_rejected_total` (phát hiện sớm bot/abuse hoặc DDoS), `cost_guard_blocked_total` (số request bị chặn do chạm trần ngân sách `402`), và `redis_semantic_cache_hit_ratio` để tối ưu chi phí gọi LLM lặp lại.

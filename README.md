# 自适应测验选题 API（Adaptive Quiz / CAT）

基于 **Python + FastAPI + SQLite** 的计算机化自适应测验（Computerized Adaptive Testing）服务。

- 题库每题保存 **区分度 a**、**难度 b** 与 **曝光次数 exposure**（2PL IRT 模型）
- 提交答案后，服务端在全部历史作答上执行**一次 warm-started Newton 更新**估计能力值 θ
- 下一题在「本会话未作答 且 曝光未超上限」的候选题中，按 **Fisher 信息量最大**选择；信息量相同取 **稳定最小的 item_id**（确定性平局规则）
- **`response_id` 幂等**：重复提交返回首次结果，不重复更新能力值、不重复增加曝光
- 提供会话进度查询、答题记录查询、题库曝光监控接口
- 一键 `docker compose up` 后可用 curl 或内置演示脚本直接调用

## 目录结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由与选题/更新事务
│   ├── irt.py         # 2PL 概率、信息量、一次 Newton 更新、选题规则
│   ├── database.py    # SQLite 连接、建表、题库初始化
│   ├── seed.py        # 初始题库（15 题，含 a/b 参数）
│   ├── schemas.py     # Pydantic 请求/响应模型
│   └── config.py      # 环境变量配置
├── tests/             # pytest 单元 + API 测试（15 个）
├── demo.py            # 仅用标准库的端到端演示脚本
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── requirements-dev.txt
```

## 算法说明

### 2PL 项目反应理论模型

对题 j（区分度 aⱼ、难度 bⱼ）和能力 θ：

```
Pⱼ(θ) = sigmoid(aⱼ·(θ − bⱼ))                      # 答对概率
Iⱼ(θ) = aⱼ²·Pⱼ(θ)·(1 − Pⱼ(θ))                     # Fisher 信息量
```

### 能力估计：一次 Newton 更新（MLE）

每收到一次作答（u∈{0,1}），在该会话**全部历史作答**上，以当前 θ 为初值只走一步：

```
g(θ) = Σ aⱼ·(uⱼ − Pⱼ)                 # 对数似然梯度
h(θ) = Σ aⱼ²·Pⱼ(θ)·(1 − Pⱼ(θ))        # 负二阶导（观测信息）
θ_new = clip(θ + g/h, −4, 4)
```

当 h < 1e-10（如极容易题全对、极难题全错，MLE 趋于无穷）时梯度步不稳定，
保持原 θ 不变，避免数值发散。能力估计截断在 `[−4, 4]`。

### 选题规则（带曝光控制）

候选题 SQL（在 `BEGIN IMMEDIATE` 写事务内执行）：

```sql
SELECT id, a, b FROM items
 WHERE exposure < :exposure_cap
   AND id NOT IN (SELECT item_id FROM responses WHERE session_id = :sid)
```

随后在 Python 中取 `Iⱼ(θ)` 最大者；信息量差 ≤ 1e-15 视为平局，取 **字典序最小的 item_id**，
保证任意环境下结果确定、可复现。选中即原子地 `exposure = exposure + 1`
（曝光在**施测时**计数；幂等重放不会重复计数）。

无候选题时会话结束，`finish_reason` 为 `no_available_items`；
达到最大题数时为 `max_items_reached`。

### 幂等

`responses` 表主键为 `(session_id, response_id)`。提交时先查首次结果快照
（`result_json`），命中则直接返回并带 `"replayed": true`，不执行任何写操作；
事务内还会再查一次以应对并发，数据库主键是最终防线。

## 快速开始（Docker Compose）

```bash
docker compose up --build
```

服务启动在 http://localhost:8000 ：

- Swagger 文档：http://localhost:8000/docs
- OpenAPI：http://localhost:8000/openapi.json
- SQLite 数据持久化在命名卷 `cat-data`（容器内 `/data/cat.db`）

### 调用示例（curl）

**1. 健康检查**

```bash
curl -s http://localhost:8000/health
# {"status":"ok","items":15,"sessions":0}
```

**2. 创建会话**（同时返回按初始能力选出的第一题）

```bash
curl -s -X POST http://localhost:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"max_items": 5}' | python3 -m json.tool
```

```json
{
  "session_id": "SES-a51f0b73a7c1",
  "status": "in_progress",
  "theta": 0.0,
  "answered_count": 0,
  "max_items": 5,
  "exposure_cap": 5,
  "current_item": {
    "item_id": "ITM-009",
    "stem": "数据 2, 4, 4, 6, 9 的中位数是？",
    "options": [
      {"index": 0, "text": "4"},
      {"index": 1, "text": "5"},
      {"index": 2, "text": "6"},
      {"index": 3, "text": "9"}
    ]
  },
  "finish_reason": null,
  "created_at": "2026-09-23T01:36:04.466343Z"
}
```

> 面向考生的题目载荷不含正确答案。

**3. 提交答案**（服务端判分、Newton 更新 θ、选出下一题）

```bash
SID=SES-a51f0b73a7c1
curl -s -X POST http://localhost:8000/sessions/$SID/responses \
  -H 'Content-Type: application/json' \
  -d '{"response_id": "resp-0001", "selected_index": 0}' | python3 -m json.tool
```

```json
{
  "replayed": false,
  "response_id": "resp-0001",
  "item_id": "ITM-009",
  "selected_index": 0,
  "answer_index": 0,
  "correct": true,
  "score": 1,
  "probability": 0.372852,
  "theta_before": 0.0,
  "theta_after": 2.063098,
  "answered_count": 1,
  "next_item": { "item_id": "ITM-014", "...": "..." },
  "status": "in_progress",
  "finish_reason": null
}
```

**4. 重复 response_id（网络重试场景）**：同样的请求再发一次，返回首次结果，
`replayed: true`，θ、答题数、曝光次数均不再变化。

**5. 查询会话进度**

```bash
curl -s http://localhost:8000/sessions/$SID/progress | python3 -m json.tool
```

**6. 查询答题记录**

```bash
curl -s http://localhost:8000/sessions/$SID/responses | python3 -m json.tool
```

**7. 查看题库参数与曝光情况**（管理用，不返回答案；可按会话标注已施测题）

```bash
curl -s "http://localhost:8000/items?session_id=$SID" | python3 -m json.tool
```

### 一键演示脚本

`demo.py` 只依赖 Python 标准库，自动完成：健康检查 → 建会话 → 逐题作答 →
重复 `response_id` 验证幂等 → 进度/记录/曝光查询。

```bash
# Docker 启动后，在宿主机直接运行：
BASE=http://localhost:8000 python3 demo.py

# 或在容器内：
docker compose exec adaptive-quiz python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

## 本地运行（无 Docker）

需要 Python 3.11+：

```bash
pip install -r requirements.txt
export CAT_DB_PATH=./data/cat.db     # 可选，默认 /data/cat.db
uvicorn app.main:app --reload --port 8000
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/health` | 健康检查（题数、会话数） |
| POST | `/sessions` | 创建会话，返回首题；body 可选 `max_items`、`exposure_cap` |
| GET  | `/sessions/{sid}/progress` | 会话进度（θ、已答/剩余题数、当前题、结束原因） |
| POST | `/sessions/{sid}/responses` | 提交答案（`response_id` + `selected_index`），返回判分、新 θ、下一题 |
| GET  | `/sessions/{sid}/responses` | 按作答顺序返回全部答题记录 |
| GET  | `/items` | 题库参数与曝光计数（支持 `?session_id=`） |

主要状态码：`201` 会话已创建；`200` 正常（含幂等重放）；`404` 会话不存在；
`409` 会话已结束仍提交新答案；`422` 请求体校验失败。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CAT_DB_PATH` | `/data/cat.db` | SQLite 文件路径 |
| `CAT_MAX_ITEMS` | `10` | 默认每会话最大作答题数（建会话时可覆盖） |
| `CAT_EXPOSURE_CAP` | `5` | 单题全局曝光上限（建会话时可覆盖） |
| `CAT_INITIAL_THETA` | `0` | 初始能力值 |
| `CAT_THETA_BOUND` | `4` | 能力估计截断边界 |

## 测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

覆盖：IRT 数值（概率/信息量/Newton 更新/平局规则）、首题选择与曝光计数、
答对后 θ 上升且题目自适应变难、重复 `response_id` 幂等且不重复计曝光、
曝光上限排除、达到最大题数后 `409`、会话内题目不重复。

## 设计要点与边界

- **每请求一个 SQLite 连接**；写操作使用 `BEGIN IMMEDIATE` 串行化，
  「检查曝光余量 → 选题 → 曝光 +1」在同一事务内原子完成，配合
  `busy_timeout` 与 WAL 模式应对并发。
- 曝光是**全局**口径（跨所有会话累计），这是 CAT 曝光控制的通常做法；
  同时每会话通过 `responses` 排除已作答题。
- 题目在**施测时**计曝光（首题在创建会话时即计数），符合"展示给考生即占用曝光"的语义。
- 能力估计用纯 MLE 的一步 Newton；全对/全错导致的无穷 MLE 用「h 过小时不更新」
  与 θ 截断兜底。如需 MAP（含先验）可在 `app/irt.py` 中扩展。
- 重置数据：`docker compose down -v`（删除卷）后重新启动即可。

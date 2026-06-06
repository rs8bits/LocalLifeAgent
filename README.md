# LocalLife Agent

本地短时活动规划与执行 Agent Demo（美团 AI 黑客松赛题「本地探索：周末闲时活动规划」）。

用户输入一句自然语言需求，系统可以理解意图、查询本地生活工具、生成活动方案，并在用户确认后模拟执行预约 / 下单。

## 当前交付范围（已完成）

- **阶段 0**：项目骨架（FastAPI 后端、Next.js 前端、启动脚本）
- **阶段 1**：Mock Data 与 Mock API（活动、餐厅、饮品、配送、路线、天气、团购券、记忆、订单）
- **阶段 2**：Tool Interface 与基础规划（BaseTool、Intent Parser、Planner、Scorer）
- **阶段 3**：Agent API 与 Human-in-the-loop（规划、确认、Session 管理）
- **阶段 4**：可演示前端 Demo（流式过程、方案卡片、修改基准、确认执行、转发消息）
- **阶段 5**：LangGraph 多 Agent 结构（输入安全、记忆、改写、意图、规划、反思、风控、执行、消息）
- **阶段 6**：Reflection、Guardrails 与 Memory（质量检查、安全边界校验、用户记忆读取）
- **阶段 7**：标签对齐 + LLM 方案组合器（吃/喝/玩/外卖闪送分类与标签解析 → 精准候选检索 → 严格 JSON action 输出）
- **阶段 8**：多轮修改语义一致性（保留/替换/新增/删除槽位、人数修改、额外活动、配送和饮品 action 对齐、反思重试）

## 技术栈

| 层面 | 技术 |
|------|------|
| 前端 | Next.js + React + TypeScript + Tailwind CSS |
| 后端 | FastAPI + Pydantic + Uvicorn |
| Agent | LangGraph + DeepSeek API（无 Key 时规则兜底） |
| 数据 | 本地 JSON Mock Data |

## 本地 Python venv 启动方式

```bash
# 1. 初始化虚拟环境并安装依赖
./scripts/setup_backend.sh

# 2. 启动后端
./scripts/run_backend.sh
```

首次运行会自动创建 `.venv/`、升级 pip、安装所有依赖。

## 后端启动命令

```bash
# 方式一：使用脚本
./scripts/run_backend.sh

# 方式二：手动启动
source .venv/bin/activate
.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

启动后访问：
- 健康检查: http://127.0.0.1:8000/health
- API 文档: http://127.0.0.1:8000/docs

## Mock API 列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/mock/activities` | 查询活动（支持 party_type/radius_km/child_age/indoor/tag/tags_any，scene 仅兼容旧调用） |
| GET | `/api/mock/restaurants` | 查询餐厅（支持 party_type/radius_km/party_size/tag/tags_any/available/max_queue_minutes，scene 仅兼容旧调用） |
| GET | `/api/mock/routes` | 查询路线（支持 origin/destination/transport） |
| GET | `/api/mock/weather` | 查询天气（支持 date/location） |
| GET | `/api/mock/deals` | 查询团购券（支持 poi_id） |
| GET | `/api/mock/drinks` | 查询饮品店（咖啡/奶茶/酒吧等） |
| GET | `/api/mock/delivery/items` | 查询外卖/闪送商品 |
| POST | `/api/mock/delivery/quote` | 估算外卖/闪送费用和时效 |
| POST | `/api/mock/delivery/orders` | 创建 Mock 外卖/闪送订单 |
| POST | `/api/mock/bookings/activity` | 预约活动 |
| POST | `/api/mock/bookings/restaurant` | 预约餐厅 |
| POST | `/api/mock/bookings/drink` | 预约饮品店 |
| POST | `/api/mock/orders` | 创建 Mock 订单 |

## 示例 curl

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 查询亲子同行、5km内、适合5岁儿童的活动
curl "http://127.0.0.1:8000/api/mock/activities?party_type=family_with_child&radius_km=5&child_age=5"

# 查询情侣纪念日餐厅
curl "http://127.0.0.1:8000/api/mock/restaurants?party_type=couple&tags_any=%E7%BA%AA%E5%BF%B5%E6%97%A5&available=true"

# 预约活动
curl -X POST http://127.0.0.1:8000/api/mock/bookings/activity \
  -H "Content-Type: application/json" \
  -d '{"activity_id":"act_001","user_id":"user_001","people":3,"time":"14:00"}'

# 创建订单
curl -X POST http://127.0.0.1:8000/api/mock/orders \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user_001","order_type":"deal","payload":{"poi_id":"rest_001","deal_id":"deal_001","quantity":3}}'
```

## 运行测试

```bash
.venv/bin/pytest backend/tests -v
```

目前共 301 个后端测试，覆盖 Mock API、工具、输入安全、改写、意图解析、标签对齐、LLM 方案组合兜底、评分、规划、反思风控、流式 API 和确认执行。

## DeepSeek 配置（可选）

系统在不配置 DeepSeek API Key 时也能正常运行，会使用规则引擎兜底。如需启用 LLM 增强的意图解析：

```bash
cp .env.example .env
# 编辑 .env 填入真实的 API Key
```

`.env.example` 内容：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=90
DEEPSEEK_MAX_RETRIES=2
DEEPSEEK_RETRY_BACKOFF_SECONDS=0.8
```

`.env` 已被 `.gitignore` 忽略，不会提交到仓库。
网络瞬断、超时、429 或 5xx 会按 `DEEPSEEK_MAX_RETRIES` 自动重试；鉴权失败不会重试。

## 已实现的 Agent 模块

### Tool Interface (`backend/tools/`)

统一工具基类 `BaseTool`，所有工具返回统一的 `ToolResult`。已实现：

| 工具 | 说明 |
|------|------|
| `search_activities` | 搜索活动（支持 party_type/radius_km/child_age/indoor/tag/tags_any） |
| `search_restaurants` | 搜索餐厅（支持 party_type/radius_km/party_size/tag/tags_any/available/max_queue_minutes） |
| `estimate_route` | 估算路线（支持 origin/destination/transport） |
| `get_weather` | 查询天气（支持 date/location） |
| `get_deals` | 查询团购券（支持 poi_id） |
| `get_tag_catalog` / `resolve_tags` | 查询标签目录并将自然语言/英文偏好对齐到业务标签 |
| `search_places` | 统一搜索吃/喝/玩等场所候选 |
| `search_delivery_items` | 搜索外卖/闪送商品 |
| `estimate_delivery` | 估算配送费用和时效 |

工具主路径使用 `party_type` + `tags` 检索；`scene` / `suitable_scenes` 只保留为旧调用兼容字段。

### Intent Parser (`backend/agent/intent_parser.py`)

从自然语言中提取结构化意图：同行人画像 `party_type`、统一 `tags`、时间窗口、人数、儿童年龄、距离偏好、饮食偏好、拍照需求、排队容忍度等。支持 LLM 优先解析 + 规则兜底。

### Scorer (`backend/agent/scorer.py`)

对候选方案进行可解释评分（0～1），家庭和朋友场景使用不同权重公式。每个方案的评分维度都会输出 `score_reasons`。

### Planner / Plan Composer (`backend/agent/planner.py`, `backend/agent/plan_composer.py`)

核心规划流程：
1. 读取用户长期记忆，用户显式输入优先于记忆
2. 解析意图并对齐到 `play` / `eat` / `drink` / `delivery` 领域标签
3. 依次查询天气、场所/商品候选、路线、团购券
4. LLM 输出严格 JSON 方案，本地校验 ID、槽位、timeline 和 actions
5. LLM 失败或结果非法时使用本地兜底组合
6. Reflection / Guardrails 对不合理方案触发一次可修复重试
7. 对每个方案评分并排序，所有工具调用记录在 `tool_logs` 中

Planner 不会调用预约、订位或下单工具。

## Agent API

基础 URL: `http://127.0.0.1:8000`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent/plan` | 规划阶段：生成候选方案（不预约/不下单） |
| POST | `/api/agent/plan/stream` | 规划阶段 SSE：实时输出节点事件、工具日志和候选方案 |
| POST | `/api/agent/confirm` | 确认阶段：执行预约、订位、Mock 订单 |
| POST | `/api/agent/confirm/stream` | 确认阶段 SSE：实时输出执行和消息生成事件 |
| GET | `/api/agent/session/{session_id}` | 查询 session 详情 |

### 规划示例

```bash
curl -X POST http://127.0.0.1:8000/api/agent/plan \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user_001","message":"下午带老婆孩子去亲子乐园，孩子5岁，老婆减肥"}'
```

响应包含：`session_id`、`intent`、`plans`（候选方案）、`tool_logs`、`errors`。

### 确认示例

```bash
curl -X POST http://127.0.0.1:8000/api/agent/confirm \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>","plan_id":"plan_001"}'
```

确认后生成活动预约、餐厅订位和团购券 Mock 订单，返回 `share_message` 可转发消息。

### 约束

- `/api/agent/plan` 不写入 `bookings.json` / `orders.json`
- `/api/agent/confirm` 才会执行预约和下单
- 所有订单为 Mock 订单，不涉及真实支付
- 重复确认同一 session 不会重复写入

## 前端 Demo 启动

前端是完整 Demo 界面，使用 Next.js + TypeScript + Tailwind CSS。

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:3000`。

## 完整 Demo 操作步骤

1. 启动后端：`./scripts/run_backend.sh`
2. 新终端启动前端：`cd frontend && npm run dev`
3. 浏览器打开 `http://127.0.0.1:3000`
4. 点击示例输入，或直接输入家庭、朋友、约会、长辈、本地配送等需求
5. 点击"开始规划"→ 看到实时流式过程（意图解析→工具调用→质量检查→安全校验）
6. 查看候选方案卡片（含人数、分数、时间线、活动/餐饮/饮品/配送、推荐理由、风险提示）
7. 点击某个方案的"确认并安排"→ 看到确认流式过程（预约→订位→订单）
8. 查看执行结果和转发消息，可复制

## LangGraph 多 Agent 结构

系统使用 LangGraph 编排规划与确认两个阶段，流程如下：

```
input_safety → memory → rewrite → intent → planner → reflection → guardrails
                                      ↑                         |
                                      └──── retry when allowed ─┘

确认阶段：executor → message_llm → guardrails
```

| 节点 | 职责 | 流式事件 |
|------|------|----------|
| Input Safety Node | 输入安全检查，阻断违法/暴力/色情/仇恨/Prompt 注入等风险 | `input_safety_start`, `input_safety_done` |
| Memory Node | 读取用户长期记忆（位置/孩子年龄/饮食偏好/距离偏好） | `memory_loaded` |
| Rewrite Node | 合并原始输入与上下文，生成更稳定的规划输入 | `rewrite_start`, `rewrite_done` |
| Intent Node | 解析自然语言意图（LLM 优先 + 规则兜底） | `intent_start`, `intent_done` |
| Planner Node | 使用 Tag Resolver 输出的 `domain_specs` 只检索必要领域，交给 LLM 组合 JSON 方案，本地校验并兜底 | `tool_start`, `tool_done`, `planner_start`, `composer_start`, `composer_done`, `plan_delta` |
| Reflection Node | 规则检查 + LLM 语义反思，检查方案是否真正满足用户意图，必要时触发重试 | `reflection_start`, `reflection_done` |
| Guardrails Node | 安全校验（POI/action 来源、阶段检查、支付承诺、儿童安全） | `guardrails_start`, `guardrails_done` |
| Executor Node | 确认阶段执行预约+订位+Mock 订单 | `booking_start`, `booking_done`, `order_start`, `order_done` |
| Message LLM / Message Node | 生成并校验可转发消息 | `message_done` |

## Reflection 检查项

规划完成后对每个方案自动检查：规则层负责稳定结构化检查，LLM Reflection 负责语义层检查（例如“唱歌”是否真的匹配 KTV，“喝酒”是否真的匹配酒吧/精酿）。

1. 是否满足用户明确要求的领域（活动/餐厅/饮品/外卖闪送）
2. 总时长是否适合 4～6 小时
3. 距离是否超过用户偏好半径（1.5 倍阈值）
4. 家庭场景是否适合儿童年龄
5. 减脂/低卡需求是否被满足
6. 排队是否过久（超过容忍上限 2 倍）
7. 天气不佳时是否优先室内
8. 是否存在路线
9. 活动/餐厅/饮品是否可预约/有位，配送时效是否过长
10. 用户明确要求的活动/餐饮/饮品/配送是否出现在 timeline 和 actions 中
11. 不可执行环节 → 写入风险提示；可修复的需求缺失 → 返回规划节点重新生成

## Guardrails 检查项

安全边界校验（显式代码检查，不依赖 prompt）：

1. 所有 POI / 配送商品 / 团购券 ID 必须存在于对应 JSON 数据文件
2. 规划阶段不得出现 booking_id / order_id
3. share_message 不得包含"真实支付成功"等违规内容
4. 家庭场景必须满足儿童年龄要求

检查不通过 → `blocked: true`，方案不返回给用户。

## 流式 API (SSE)

### POST /api/agent/plan/stream

规划流式事件序列：`intent_start` → `intent_done` → `memory_loaded` → `tag_resolve_start`/`tag_resolve_done` → `place_search_start`/`place_search_done` → `composer_start`/`composer_done` → `plan_delta` → `reflection_start`/`reflection_done` → `guardrails_start`/`guardrails_done` → `plan_done`

### POST /api/agent/confirm/stream

确认流式事件序列：`confirm_start` → `booking_start`/`booking_done` → `order_start`/`order_done` → `message_done` → `confirm_done`

前端使用 `fetch()` + `ReadableStream` 读取 SSE，每个事件实时展示在"实时过程"区域。

## 数据文件说明

所有业务数据存放在 `backend/data/`，为本地 JSON 文件：

| 文件 | 内容 | 数量 |
|------|------|------|
| `activities.json` | 活动（亲子乐园/公园/展览/KTV/密室/电竞/LiveHouse/citywalk/影院/酒店下午茶等） | 16 条 |
| `restaurants.json` | 餐厅（健康轻食/云南菜/火锅/烤肉/日料/咖啡甜品/亲子/情侣纪念日/长辈包间/商务宴请等） | 13 条 |
| `drinks.json` | 饮品店（奶茶/咖啡/茶饮/酒吧/酒店茶廊） | 7 条 |
| `delivery_items.json` | 外卖/闪送商品（轻食/奶茶/蛋糕/鲜花/水果/礼盒/纪念日花束） | 8 条 |
| `delivery_orders.json` | 外卖/闪送订单记录（运行时写入） | 初始为空 |
| `tag_catalog.json` | 吃/喝/玩/外卖闪送标签目录与 aliases | 1 份 |
| `routes.json` | 路线（开车/地铁/打车） | 5 条 |
| `weather.json` | 天气（晴天/雨天 × 不同区域） | 4 条 |
| `deals.json` | 团购券 | 13 条 |
| `user_memory.json` | 用户记忆样例（家庭/朋友/聚会三种画像） | 3 条 |
| `bookings.json` | 预约记录（运行时写入） | 初始为空 |
| `orders.json` | 订单记录（运行时写入） | 初始为空 |

活动、餐厅和团购券数据已补充接近本地生活平台的业务字段，例如评分、评价数、月销量、营业时间、剩余库存、预约说明、排队状态、服务设施、退款规则和核销方式。所有字段仍然是 Mock Data，仅用于 Demo，不代表真实平台库存、价格或交易结果。

## 当前交付状态

- 后端 Agent、Mock API、Mock Data、前端 Demo、测试和设计文档均已完成。
- 真实交易、真实地图、真实库存和真实支付未接入，当前仅作为本地 Demo。
- 可选后续优化：接入真实业务 API/MCP、扩充更多城市和商圈数据、补充前端 E2E 测试、增加持久化数据库。

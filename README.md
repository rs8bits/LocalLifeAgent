# LocalLife Agent

本地短时活动规划与执行 Agent Demo（美团 AI 黑客松赛题「本地探索：周末闲时活动规划」）。

用户输入一句自然语言需求，系统可以理解意图、查询本地生活工具、生成活动方案，并在用户确认后模拟执行预约 / 下单。

## 当前完成范围

- **阶段 0**：项目骨架（FastAPI 后端、基础前端配置、启动脚本）
- **阶段 1**：Mock Data 与 Mock API（8 类业务数据、7 个查询/写入接口）
- **阶段 2**：Tool Interface 与基础规划（BaseTool、Intent Parser、Planner、Scorer）

## 技术栈

| 层面 | 技术 |
|------|------|
| 前端 | Next.js + React + Tailwind CSS（阶段 4 实现） |
| 后端 | FastAPI + Pydantic + Uvicorn |
| Agent | 计划使用 LangGraph + DeepSeek API |
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
| GET | `/api/mock/activities` | 查询活动（支持 scene/radius_km/child_age/indoor/tag） |
| GET | `/api/mock/restaurants` | 查询餐厅（支持 scene/radius_km/party_size/tag/available/max_queue_minutes） |
| GET | `/api/mock/routes` | 查询路线（支持 origin/destination/transport） |
| GET | `/api/mock/weather` | 查询天气（支持 date/location） |
| GET | `/api/mock/deals` | 查询团购券（支持 poi_id） |
| POST | `/api/mock/bookings/activity` | 预约活动 |
| POST | `/api/mock/bookings/restaurant` | 预约餐厅 |
| POST | `/api/mock/orders` | 创建 Mock 订单 |

## 示例 curl

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 查询家庭场景、5km内、适合5岁儿童的活动
curl "http://127.0.0.1:8000/api/mock/activities?scene=family&radius_km=5&child_age=5"

# 查询家庭场景、健康标签、可用的餐厅
curl "http://127.0.0.1:8000/api/mock/restaurants?scene=family&tag=%E5%81%A5%E5%BA%B7&available=true"

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

目前共 89 个测试，覆盖 Mock API、工具、意图解析、评分和规划。

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
DEEPSEEK_MODEL=v4flash
```

`.env` 已被 `.gitignore` 忽略，不会提交到仓库。

## 已实现的 Agent 模块

### Tool Interface (`backend/tools/`)

统一工具基类 `BaseTool`，所有工具返回统一的 `ToolResult`。已实现：

| 工具 | 说明 |
|------|------|
| `search_activities` | 搜索活动（支持 scene/radius_km/child_age/indoor/tag） |
| `search_restaurants` | 搜索餐厅（支持 scene/radius_km/party_size/tag/available/max_queue_minutes） |
| `estimate_route` | 估算路线（支持 origin/destination/transport） |
| `get_weather` | 查询天气（支持 date/location） |
| `get_deals` | 查询团购券（支持 poi_id） |

工具兼容 `suitable_scenes` 字段，`general` 场景的活动/餐厅也可以进入家庭或朋友候选。

### Intent Parser (`backend/agent/intent_parser.py`)

从自然语言中提取结构化意图：场景、时间窗口、人数、儿童年龄、距离偏好、饮食偏好、拍照需求、排队容忍度等。支持 LLM 优先解析 + 规则兜底。

### Scorer (`backend/agent/scorer.py`)

对候选方案进行可解释评分（0～1），家庭和朋友场景使用不同权重公式。每个方案的评分维度都会输出 `score_reasons`。

### Planner (`backend/agent/planner.py`)

核心规划流程：
1. 读取用户长期记忆
2. 解析意图（用户输入优先于记忆）
3. 依次查询天气 → 活动 → 餐厅 → 路线 → 团购券
4. 组合 2～3 个候选方案
5. 对每个方案评分并排序
6. 所有工具调用记录在 `tool_logs` 中

Planner 不会调用预约、订位或下单工具。

## 数据文件说明

所有业务数据存放在 `backend/data/`，为本地 JSON 文件：

| 文件 | 内容 | 数量 |
|------|------|------|
| `activities.json` | 活动（亲子乐园/公园/展览/商场/咖啡店/桌游/citywalk/影院） | 8 条 |
| `restaurants.json` | 餐厅（健康轻食/云南菜/火锅/烤肉/日料/咖啡甜品/亲子/排队长/无位） | 10 条 |
| `routes.json` | 路线（开车/地铁/打车） | 5 条 |
| `weather.json` | 天气（晴天/雨天 × 不同区域） | 4 条 |
| `deals.json` | 团购券 | 5 条 |
| `user_memory.json` | 用户记忆样例（家庭/朋友/聚会三种画像） | 3 条 |
| `bookings.json` | 预约记录（运行时写入） | 初始为空 |
| `orders.json` | 订单记录（运行时写入） | 初始为空 |

活动、餐厅和团购券数据已补充接近本地生活平台的业务字段，例如评分、评价数、月销量、营业时间、剩余库存、预约说明、排队状态、服务设施、退款规则和核销方式。所有字段仍然是 Mock Data，仅用于 Demo，不代表真实平台库存、价格或交易结果。

## 下一阶段计划

- **阶段 3**：Agent API 与 Human-in-the-loop（`/api/agent/plan`、`/api/agent/confirm`）
- **阶段 4**：前端 Demo（Next.js 页面、方案卡片、确认交互）
- **阶段 5**：LangGraph 多 Agent 编排
- **阶段 6**：Reflection、Guardrails 与 Memory
- **阶段 7**：测试与演示打磨

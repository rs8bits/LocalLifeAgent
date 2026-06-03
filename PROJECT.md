# LocalLife Agent：本地短时活动规划与执行 Agent

本项目用于美团 AI 黑客松赛题「本地探索：周末闲时活动规划」。目标是做一个能理解自然语言、调用本地生活工具、生成短时活动方案，并在用户确认后模拟执行预约 / 下单的 Agent Demo。

---

## 1. 项目目标

用户输入一句自然语言，例如：

> 今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，孩子 5 岁，老婆最近在减肥，帮我安排一下。

系统需要完成：

1. 理解用户意图；
2. 判断家庭 / 朋友等场景；
3. 查询附近活动、餐厅、饮品、配送商品、路线、天气、排队和预约情况；
4. 生成 2～3 个可执行的 4～6 小时活动方案；
5. 等待用户确认；
6. 用户确认后模拟预约、订位或下单；
7. 生成可转发给家人或朋友的消息。

本项目不是简单搜索推荐，而是 Planning + Tool Use + Execution 的本地生活 Agent。

当前实现状态（2026-06-03）：端到端 Demo 已完成，包含 FastAPI 后端、Next.js 前端、LangGraph Agent、Mock API / Mock Data、SSE 流式过程、多轮修改、Reflection / Guardrails、确认执行、后端测试和 `docs/design.md` 设计文档。

---

## 2. 技术栈

### 前端

- Next.js
- React
- TypeScript
- Tailwind CSS

### 后端

- FastAPI
- Pydantic
- Uvicorn

### Agent

- LangGraph
- DeepSeek API
- 规则兜底与本地校验

### 数据与工具

- JSON Mock Data
- FastAPI Mock API
- 本地模拟预约、下单、排队、路线和库存
- 本地模拟饮品店、外卖 / 闪送商品、配送报价和配送订单
- Tool Interface 可替换为 MCP / 真实业务 API

---

## 3. 支持场景

### 3.1 家庭场景

典型输入：

> 今天下午想和老婆孩子出去玩几个小时，别太远，孩子 5 岁，老婆最近在减肥。

重点约束：

- 孩子年龄；
- 是否适合亲子和安全；
- 是否适合室内；
- 餐厅是否清淡健康、适合减脂；
- 是否有儿童椅；
- 排队是否短；
- 距离是否近。

### 3.2 朋友场景

典型输入：

> 今天下午想和 4 个朋友出去玩，2 男 2 女，别太远，想吃点好吃的，最好还能拍照。

重点约束：

- 4 人同行；
- 活动适合社交；
- 有拍照点；
- 餐厅氛围好；
- 饭后可以继续活动；
- 距离不要太远。

---

## 4. 系统架构

```text
Next.js Frontend
  ↓
FastAPI Backend
  ↓
LangGraph Orchestrator
  ↓
Agent Nodes
  ├── Input Safety
  ├── Memory
  ├── Rewrite
  ├── Intent Parser
  ├── Planner / Plan Composer
  ├── Reflection
  ├── Guardrails
  ├── Executor
  └── Message Generator
  ↓
Tool Interface
  ↓
Mock APIs
  ├── Activity API
  ├── Restaurant API
  ├── Drink API
  ├── Delivery API
  ├── Route API
  ├── Weather API
  ├── Deal API
  ├── Booking API
  └── Order API
  ↓
JSON Mock Data
```

生产化时可替换为：

```text
Agent → Tool Interface → MCP Server → Real Business API
```

---

## 5. 核心流程

### 5.1 规划阶段

接口：`POST /api/agent/plan`

要求：

- 解析用户输入；
- 查询 Mock Data；
- 生成候选方案；
- 展示工具调用日志；
- 不预约、不订位、不下单。

返回核心字段：

```json
{
  "session_id": "session_001",
  "intent": {},
  "plans": [],
  "tool_logs": []
}
```

### 5.2 确认执行阶段

接口：`POST /api/agent/confirm`

要求：

- 根据 `session_id` 和 `plan_id` 找到候选方案；
- 执行 Mock 预约、订位、团购券下单或配送下单；
- 返回执行结果；
- 生成可转发消息。

返回核心字段：

```json
{
  "status": "success",
  "orders": [],
  "share_message": "搞定啦，下午 2 点出发..."
}
```

---

## 6. Agent 设计

项目采用轻量 Multi-Agent + Orchestrator 设计。Agent 不一定是独立进程，但在代码结构和 LangGraph 节点上需要区分职责。

| 节点 | 职责 |
|---|---|
| Input Safety Agent | 检查违法、暴力、色情、仇恨、Prompt 注入等输入风险 |
| Memory Agent | 读取长期记忆；用户显式输入优先于记忆 |
| Rewrite Agent | 合并原始输入与上下文，生成稳定规划输入 |
| Intent Agent | 解析时间、人群、人数、距离、预算、活动/餐饮/饮品/配送偏好 |
| Planner Agent | 标签对齐、候选召回、LLM 方案组合、本地兜底、路线/团购券丰富、评分 |
| Reflection Agent | 检查需求覆盖、时间线、actions 可见性、顺序、儿童/长辈/减脂/排队/配送风险 |
| Guardrails Agent | 校验 POI/action 来源、执行阶段、儿童安全、订单号边界和支付承诺 |
| Executor Agent | 仅在用户确认后执行 Mock 预约、订位、团购券订单和配送订单 |
| Message Agent | 生成并校验用户展示文案和可转发消息 |

建议统一状态对象包含：

```python
class AgentState(TypedDict):
    session_id: str
    user_id: str
    user_message: str
    intent: dict
    user_profile: dict
    candidate_activities: list
    candidate_restaurants: list
    candidate_drinks: list
    candidate_delivery_items: list
    candidate_routes: list
    plans: list
    revision_patch: dict | None
    selected_plan_id: str | None
    tool_logs: list
    reflection_result: dict
    guardrail_result: dict
    execution_result: dict | None
    share_message: str | None
    errors: list
```

---

## 7. Tool 与 Mock API

### 7.1 Tool Interface

所有工具统一实现：

```python
class BaseTool:
    name: str
    description: str

    async def run(self, **kwargs) -> dict:
        ...
```

### 7.2 Mock API

Mock API 使用 FastAPI 实现，只读写本地 JSON，不访问真实外部服务。

```text
GET  /api/mock/activities
GET  /api/mock/restaurants
GET  /api/mock/drinks
GET  /api/mock/delivery/items
POST /api/mock/delivery/quote
POST /api/mock/delivery/orders
GET  /api/mock/routes
GET  /api/mock/weather
GET  /api/mock/deals
POST /api/mock/bookings/activity
POST /api/mock/bookings/restaurant
POST /api/mock/bookings/drink
POST /api/mock/orders
```

### 7.3 Mock Data

目录：`backend/data/`

```text
activities.json
restaurants.json
drinks.json
delivery_items.json
delivery_orders.json
tag_catalog.json
routes.json
weather.json
deals.json
user_memory.json
bookings.json
orders.json
```

数据至少覆盖：

- 16 个活动；
- 13 个餐厅；
- 7 个饮品店；
- 8 个外卖 / 闪送商品；
- 5 条路线；
- 13 个团购券；
- 4 条天气样例；
- 3 个用户记忆样例；
- 成功和失败预约案例；
- 家庭、朋友、长辈、约会、距离过远、儿童不适合、餐厅无位、排队过长、配送覆盖不足等异常样例。

---

## 8. 页面设计

当前页面包含：

- 输入区；
- Agent 回复区；
- 工具调用日志区；
- 方案卡片区；
- 确认并安排按钮；
- 执行结果区；
- 可复制转发消息。

方案卡片包含：

- 方案名称；
- 推荐标签；
- 识别人数；
- 时间线；
- 主活动和额外活动；
- 餐厅；
- 饮品和外卖 / 闪送；
- 路线；
- 人均预算；
- 排队时间；
- 预约状态；
- 推荐理由；
- 风险提醒；
- 确认按钮。

---

## 9. 异常处理

当前支持：

| 异常 | 处理方式 |
|---|---|
| 输入安全风险 | 阻断规划并返回安全提示 |
| LLM 调用失败或 JSON 非法 | 使用规则兜底，并对 LLM 输出做本地 schema / ID / action 校验 |
| Mock API 无数据 | 返回空结果、放宽软过滤或给出可理解提示 |
| 标签过窄 | 逐步放宽软条件，不编造不存在的 POI |
| 明确需求缺失 | Reflection / Guardrails 标记 retryable，返回规划节点重新生成一次 |
| 餐厅无位 | 自动选择同商圈备选餐厅或写入风险提示 |
| 排队过久 | 家庭场景降权或更换餐厅 |
| 活动不适合孩子 | 按 `suitable_age` 过滤 |
| 距离过远 | 过滤或降低排序 |
| 天气不佳 | 优先推荐室内活动 |
| 多轮修改误删旧需求 | 通过 keep / replace / add / remove / locked 槽位约束保留或替换 |
| 饮品 / 配送 action 隐藏 | 校验 timeline、selected_refs 和 actions 一致性 |
| 预约失败 | 执行阶段尝试备选方案 |
| plan_id 不存在 | 返回明确错误 |

---

## 10. 项目目录

```text
LocalLifeAgent/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── types/
│   └── package.json
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── llm/
│   ├── agent/
│   ├── tools/
│   ├── mock_api/
│   ├── schemas/
│   ├── memory/
│   ├── tests/
│   └── data/
│
├── docs/
│   └── design.md
│
├── AGENT.md
├── PLAN.md
├── PROJECT.md
└── README.md
```

---

## 11. 成功标准

当前交付已达到：

1. 可以启动前端；
2. 可以启动后端；
3. 用户输入自然语言后，可以返回结构化意图；
4. 可以生成候选方案，并在无数据时返回明确错误或风险提示；
5. 每个方案都来自 Mock API 数据；
6. 用户确认后，可以生成 Mock 预约 / 订单；
7. 可以展示工具调用日志；
8. 可以生成可转发消息；
9. 支持输入安全、LLM 失败、无数据、预约失败、多轮修改和语义缺失等异常处理案例；
10. 设计文档不超过 2 页。

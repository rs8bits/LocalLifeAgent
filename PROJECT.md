# LocalLife Agent：本地短时活动规划与执行 Agent

本项目用于美团 AI 黑客松赛题「本地探索：周末闲时活动规划」。目标是做一个能理解自然语言、调用本地生活工具、生成短时活动方案，并在用户确认后模拟执行预约 / 下单的 Agent Demo。

---

## 1. 项目目标

用户输入一句自然语言，例如：

> 今天下午是空的，想和老婆孩子出去玩几个小时，别离家太远，孩子 5 岁，老婆最近在减肥，帮我安排一下。

系统需要完成：

1. 理解用户意图；
2. 判断家庭 / 朋友等场景；
3. 查询附近活动、餐厅、路线、天气、排队和预约情况；
4. 生成 2～3 个可执行的 4～6 小时活动方案；
5. 等待用户确认；
6. 用户确认后模拟预约、订位或下单；
7. 生成可转发给家人或朋友的消息。

本项目不是简单搜索推荐，而是 Planning + Tool Use + Execution 的本地生活 Agent。

---

## 2. 技术栈

### 前端

- Next.js
- React
- Tailwind CSS
- shadcn/ui（可选）
- Zustand 或 React Context

### 后端

- FastAPI
- Pydantic
- Uvicorn

### Agent

- LangGraph
- LangChain Core（可选）
- DeepSeek API

### 数据与工具

- JSON Mock Data
- FastAPI Mock API
- 本地模拟预约、下单、排队、路线和库存
- 预留 MCP Tool Adapter

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
  ├── Intent Parser
  ├── Planner
  ├── Tool Executor
  ├── Reflection
  ├── Guardrails
  ├── Memory Manager
  └── Human-in-the-loop Confirm Node
  ↓
Tool Interface
  ↓
Mock APIs
  ├── User Profile API
  ├── Activity API
  ├── Restaurant API
  ├── Route API
  ├── Weather API
  ├── Deal API
  ├── Booking API
  └── Order API
  ↓
JSON Mock Data
```

未来可替换为：

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
- 执行 Mock 预约、订位、下单；
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
| Intent Agent | 解析时间、人群、距离、预算、偏好，并合并用户记忆 |
| Planner Agent | 制定工具调用计划，组合候选活动、餐厅和路线 |
| Executor Agent | 执行工具调用，记录日志，并在确认后执行预约 / 下单 |
| Reflection Agent | 检查方案时间、路线、餐厅、儿童适配、距离和可执行性 |
| Guardrails Agent | 校验 POI 来源、执行阶段、儿童安全和支付承诺 |
| Message Agent | 生成用户展示文案和可转发消息 |

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
    candidate_routes: list
    plans: list
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
GET  /api/mock/routes
GET  /api/mock/weather
GET  /api/mock/deals
POST /api/mock/bookings/activity
POST /api/mock/bookings/restaurant
POST /api/mock/orders
```

### 7.3 Mock Data

目录：`backend/data/`

```text
activities.json
restaurants.json
routes.json
weather.json
deals.json
user_memory.json
orders.json
```

数据至少覆盖：

- 8 个活动；
- 10 个餐厅；
- 5 条路线；
- 5 个团购券；
- 2 种天气；
- 3 个用户记忆样例；
- 成功和失败预约案例；
- 家庭、朋友、距离过远、儿童不适合、餐厅无位、排队过长等异常样例。

---

## 8. 页面设计

至少包含：

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
- 时间线；
- 活动地点；
- 餐厅；
- 路线；
- 人均预算；
- 排队时间；
- 预约状态；
- 推荐理由；
- 风险提醒；
- 确认按钮。

---

## 9. 异常处理

必须支持：

| 异常 | 处理方式 |
|---|---|
| LLM 调用失败 | 使用规则兜底 |
| Mock API 无数据 | 返回空结果和可理解提示 |
| 餐厅无位 | 自动选择同商圈备选餐厅 |
| 排队过久 | 家庭场景降权或更换餐厅 |
| 活动不适合孩子 | 按 `suitable_age` 过滤 |
| 距离过远 | 过滤或降低排序 |
| 天气不佳 | 优先推荐室内活动 |
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

MVP 必须达到：

1. 可以启动前端；
2. 可以启动后端；
3. 用户输入自然语言后，可以返回结构化意图；
4. 可以生成至少 2 个候选方案；
5. 每个方案都来自 Mock API 数据；
6. 用户确认后，可以生成 Mock 预约 / 订单；
7. 可以展示工具调用日志；
8. 可以生成可转发消息；
9. 至少包含一个异常处理案例；
10. 设计文档不超过 2 页。

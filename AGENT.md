# LocalLife Agent 开发执行约束

本文档是本项目的开发执行约束，面向 Codex / Claude Code 等开发助手使用。

项目背景、产品范围和系统架构以 `PROJECT.md` 为准；阶段计划和任务拆分以 `PLAN.md` 为准。本文只保留开发时必须遵守的规则，避免和项目说明重复。

---

## 1. 协作规则

- 默认使用简体中文沟通。
- Codex 主要负责阅读、分析、方案、任务拆分、审查、测试和总结。
- Claude Code 主要负责较大规模代码实现。
- 涉及写代码、改代码、新建文件、重构、补测试、修 bug 时，优先在项目根目录生成 `TEMP_TASK_*.md`，由用户调用 Claude Code 执行。
- 很小的修改可以由 Codex 直接完成，例如少量文档调整、单文件小修复、短测试补充。
- `TEMP_TASK_*.md` 使用完成后必须删除，不提交到仓库。
- 完成编码、审查和测试后只创建本地提交，不自动 `git push`。

---

## 2. 开发原则

### 2.1 Demo 优先

优先保证端到端 Demo 能跑通，再逐步补强架构完整性。

核心流程：

```text
用户输入
  ↓
后端解析
  ↓
Agent 规划
  ↓
工具调用
  ↓
返回候选方案
  ↓
用户确认
  ↓
Mock 预约 / 下单
  ↓
返回执行结果和转发消息
```

不要一开始陷入复杂 UI、复杂数据库、真实地图接口或真实交易系统。

### 2.2 Mock Data 是事实来源

所有业务数据必须来自本地 Mock Data 或 Mock API。

禁止让 LLM 凭空编造：

- 餐厅、活动、路线和商圈；
- 价格、排队时间、库存和预约状态；
- 订单号、团购券和预约成功结果。

如果数据不存在，返回 fallback、空结果或可理解的错误信息。

### 2.3 LLM 只负责推理和表达

LLM 可以负责：

- 意图解析；
- 方案解释；
- 推荐理由；
- 转发消息生成；
- Reflection 检查。

LLM 不可以作为业务事实来源。

---

## 3. 架构执行要求

### 3.1 后端

- 使用 FastAPI + Pydantic。
- API route 保持薄层，不把核心业务逻辑写死在路由里。
- 数据结构先定义在 `backend/schemas/`。
- 异常不能导致程序崩溃，需要返回用户可理解的信息。

### 3.2 Agent

- 优先使用 LangGraph；如果时间不足，可以先用清晰的模块结构模拟节点流程。
- 至少区分以下职责：
  - Intent：解析用户需求并合并记忆；
  - Planner：生成工具调用计划和候选方案；
  - Executor：调用工具，区分 planning mode / execution mode；
  - Reflection：检查方案质量，最多重试一次；
  - Guardrails：用代码校验业务边界；
  - Message：生成用户展示文案和转发消息。
- Guardrails 必须显式实现来源检查和执行阶段检查，不能只依赖 prompt。

### 3.3 工具

- 所有关键业务能力通过统一 Tool Interface 执行。
- Tool 返回值要可追踪、可测试，并写入 `tool_logs`。
- 预约、订位、下单只允许在用户确认后执行。

建议工具：

| 工具 | 用途 |
|---|---|
| `search_activities` | 搜索活动 |
| `search_restaurants` | 搜索餐厅 |
| `estimate_route` | 估算路线 |
| `get_weather` | 获取天气 |
| `get_deals` | 获取团购券 |
| `check_availability` | 检查可预约时间 |
| `book_activity` | 预约活动 |
| `reserve_restaurant` | 订位餐厅 |
| `create_mock_order` | 创建模拟订单 |
| `generate_share_message` | 生成转发消息 |

### 3.4 LLM 配置

- 默认接入 DeepSeek API，但模型名必须从 `.env` 读取，不在代码中硬编码。
- 统一封装 LLM Client，例如 `backend/llm/deepseek_client.py`。
- LLM 调用失败时必须提供规则兜底，尤其是意图解析和方案生成。

环境变量：

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=
```

---

## 4. Human-in-the-loop 约束

必须严格区分两个阶段：

- `/api/agent/plan`：只生成方案，不预约、不订位、不下单。
- `/api/agent/confirm`：用户确认 `plan_id` 后，才允许执行预约、订位、下单。

确认前禁止调用：

- `book_activity`
- `reserve_restaurant`
- `create_mock_order`

---

## 5. 代码风格

### Python

- 使用 type hints。
- 使用 Pydantic models。
- 工具函数要可单测。
- 函数保持清晰短小。
- Prompt 放在 `backend/agent/prompts/`，不要硬编码在节点逻辑中。

### TypeScript

- 使用明确类型。
- API 调用放在 `frontend/lib/api.ts` 或同等职责文件。
- 方案卡片、工具日志、执行结果等 UI 组件独立拆分。
- UI 优先清晰可演示，不追求复杂动效。

### 命名

- Python 文件使用 `snake_case`。
- React 组件使用 `PascalCase`。
- Agent 节点命名为 `backend/agent/nodes/{role}_node.py`。
- Tool 命名为 `backend/tools/{domain}_tool.py`。
- Schema 命名为 `backend/schemas/{domain}.py`。

---

## 6. 必测场景

至少覆盖：

- 家庭场景意图解析；
- 朋友场景意图解析；
- 儿童年龄过滤；
- 餐厅健康偏好；
- 排队时间降权；
- 用户确认前不生成订单；
- 用户确认后生成 Mock 预约 / 订单；
- Mock API 无数据或预约失败时的 fallback。

---

## 7. 汇报要求

每次完成实现、审查或测试后，用中文说明：

- 改了什么；
- 有没有风险；
- 测试是否通过；
- 后续建议是什么。

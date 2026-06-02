# LocalLife Agent 设计文档

## 1. 目标与边界

LocalLife Agent 面向“本地短时活动规划 + 确认执行”场景。用户输入自然语言需求后，系统完成意图解析、标签对齐、Mock 场所/商品召回、方案组合、风险检查、多轮修改；用户确认后再执行 Mock 预约、团购券订单和配送订单。

系统全量基于 Mock Data，所有价格、库存、预约、订单和配送结果仅用于 Demo。规划阶段只生成候选方案和 actions，不产生真实 `booking_id` / `order_id`；确认阶段才写入 Mock JSON 文件。技术栈为 FastAPI、LangGraph、DeepSeek API、Next.js 和 Tailwind。LLM 用于增强，关键路径均有规则兜底和本地校验。

## 2. Agent 结构设计

核心状态为 `AgentState`，包含用户输入、`Intent`、候选数据、方案、工具日志、反思结果、Guardrails 结果、执行结果和 SSE 事件队列。主要结构定义在 `backend/agent/state.py`、`backend/agent/schemas.py`。

规划阶段 LangGraph：

```text
input_safety -> memory -> rewrite -> intent -> planner -> reflection -> guardrails
                                      ^                         |
                                      |---- retry when allowed -|
```

节点职责：

| 节点 | 说明 |
| --- | --- |
| `input_safety` | 识别违法、暴力、色情、仇恨、Prompt 注入等风险，命中后阻断。 |
| `memory` | 读取用户长期记忆；记忆标签只参与评分，不做硬过滤。 |
| `rewrite` | 整理原始输入和记忆上下文；LLM 不可用时走规则。 |
| `intent` | 解析同行人画像、时间、人数、餐次、活动/餐饮/饮品/配送偏好、儿童年龄、距离和预算。 |
| `planner` | 标签对齐、天气查询、候选召回、方案组合、多轮约束应用、路线/团购券丰富、评分。 |
| `reflection` | 检查需求覆盖、时间线、路线、儿童/长辈/减脂/排队/配送风险。 |
| `guardrails` | 校验 POI/action ID、订单号边界、儿童年龄；可修复问题触发重试。 |

确认执行阶段：

```text
executor -> message_llm -> guardrails
              ^              |
              |-- retry -----|
```

`executor` 按 plan.actions 调用 Mock API；`message_llm` 生成可转发消息；执行阶段 Guardrails 防止出现“真实支付成功”“保证有位”等误导性表述。

多轮修改由 `revision.py` 生成 `revision_patch`，包含 `keep_slots`、`replace_slots`、`add_slots`、`remove_slots`、`locked_slots` 和 `intent_patch`。配送商品、活动偏好、否定/保留/替换语义集中在 `semantic_rules.py`，避免把逻辑写死成某个商品、餐厅或活动特例。

## 3. 工具调用链路

工具继承 `BaseTool`，统一返回 `ToolResult(tool, status, message, data, error)`，注册在 `backend/tools/registry.py`。规划节点只调用读工具，并把调用写入 `tool_logs`，便于前端展示推理链路。

规划链路：

```text
parse_intent
-> resolve_domain_tags
-> get_weather
-> search_places(play/eat/drink) + search_delivery_items(delivery)
-> compose_plan_specs_with_llm
-> validate_plan_specs
-> 本地兜底组合
-> estimate_route + get_deals
-> score_plan
-> reflection + guardrails
```

`tag_resolver` 将意图对齐到 `play/eat/drink/delivery` 四个领域，输出 `domain_specs` 和 `domain_required`。场所搜索使用 `party_type`、距离、人数、儿童年龄、天气室内偏好、排队容忍和标签 OR 召回；无结果时逐步放宽软过滤。方案组合优先让 DeepSeek 输出严格 JSON，本地校验 ID、action 和锁定槽位；LLM 失败或输出非法时，使用 `_build_diverse_plans` / `_build_delivery_only_plans` 兜底。

确认链路：

```text
/api/agent/confirm
-> execute_plan
-> book_activity / book_restaurant / book_drink
-> create_order / create_delivery_order
-> 生成 share_message
-> message guardrails
-> 写回 session
```

## 4. 异常处理机制

系统采用分层防护：输入阻断、LLM 降级、本地校验、可修复重试、风险提示。

| 层级 | 处理方式 |
| --- | --- |
| 输入安全 | 空消息返回 HTTP 400；安全违规返回 blocked 和 safe_message。 |
| LLM | API Key 缺失、超时、网络错误、JSON 失败时，Intent/Rewrite/Tag/Composer/Message 全部降级规则路径。 |
| 意图解析 | `_valid_llm_field` 过滤零值/占位字段；距离等字段只有用户明确提及时才覆盖。 |
| 标签/召回 | 标签过窄时放宽软条件；有方案则写 `risk_tips`，required 且无方案才写 `errors`。 |
| 方案组合 | `validate_plan_specs` 丢弃编造 ID、非法 action、遗漏锁定槽位的 LLM 结果；无合法结果走本地兜底。 |
| Reflection | 时间、路线、儿童年龄、排队、配送等问题写入风险提示，不直接阻断。 |
| Guardrails | 编造 POI/action ID、规划阶段出现订单号为 fatal，blocked；儿童年龄和转发消息问题为 retryable。 |
| 执行 | 单个预约/下单失败不影响其他 action，汇总为 `success`、`partial_success` 或 `failed`。 |
| API | session/plan 不存在返回 HTTP 404；重复确认直接返回已有执行结果。 |

## 5. 交付范围

当前交付包含后端 Agent、前端界面、Mock API、Mock Data、测试和本文档。关键代码路径：

- Agent 编排：`backend/agent/graph.py`
- API 入口：`backend/agent/api.py`
- 规划节点：`backend/agent/nodes/planner_node.py`
- 多轮修改：`backend/agent/revision.py`、`backend/agent/semantic_rules.py`
- 工具层：`backend/tools/registry.py`、`backend/tools/mock_tools.py`
- Mock API 与数据：`backend/mock_api/`、`backend/data/`
- 前端：`frontend/`

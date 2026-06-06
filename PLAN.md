# LocalLife Agent 开发计划

目标：先完成可演示的端到端 MVP，再补齐 Agent 架构、风控检查、记忆和异常案例。所有阶段都坚持 Mock Data 优先，禁止 LLM 编造业务事实。

当前状态（2026-06-03）：阶段 0～8 已完成并形成可演示交付。本文件保留实施拆分和验收口径，便于复盘；后续工作仅剩可选增强，不影响当前交付。

---

## 阶段 0：项目骨架（已完成）

目标：让前后端项目能启动，并明确目录边界。

任务：

1. 初始化 `backend/` FastAPI 项目。
2. 初始化 `frontend/` Next.js + Tailwind 项目。
3. 增加基础配置文件和启动脚本。
4. 建立 `backend/schemas/`、`backend/agent/`、`backend/tools/`、`backend/mock_api/`、`backend/data/` 目录。
5. 编写 `README.md` 的最小启动说明。

验收：

- 后端可启动并返回健康检查结果。
- 前端可启动并展示基础页面。
- README 能说明如何本地启动。

---

## 阶段 1：Mock Data 与 Mock API（已完成）

目标：先把业务事实层做稳，后续 Agent 只能使用这些数据。

任务：

1. 创建活动、餐厅、饮品、配送商品、路线、天气、团购券、用户记忆和订单 JSON。
2. 数据覆盖家庭、朋友、餐厅无位、排队过长、距离过远、儿童不适合、预约失败等案例。
3. 实现 Mock API：
   - `GET /api/mock/activities`
   - `GET /api/mock/restaurants`
   - `GET /api/mock/drinks`
   - `GET /api/mock/delivery/items`
   - `POST /api/mock/delivery/quote`
   - `POST /api/mock/delivery/orders`
   - `GET /api/mock/routes`
   - `GET /api/mock/weather`
   - `GET /api/mock/deals`
   - `POST /api/mock/bookings/activity`
   - `POST /api/mock/bookings/restaurant`
   - `POST /api/mock/bookings/drink`
   - `POST /api/mock/orders`
4. 为 Mock API 增加基础 schema 和错误返回。

验收：

- 能通过 API 查询到活动、餐厅、饮品、配送商品、路线、天气和团购券。
- 能模拟预约成功和失败。
- 能模拟创建团购券订单和配送订单。

---

## 阶段 2：Tool Interface 与基础规划（已完成）

目标：让后端可以通过工具查询 Mock API，并生成第一版候选方案。

任务：

1. 实现 `BaseTool`。
2. 实现活动、餐厅、饮品、配送、路线、天气、团购券、预约和订单工具。
3. 实现 `tool_logs` 记录。
4. 实现基础 Intent 解析规则兜底。
5. 实现简单 Planner：
   - 家庭场景优先亲子、安全、近距离、健康餐厅；
   - 朋友场景优先社交、拍照、氛围、餐饮体验；
   - 所有候选必须来自 Mock Data。
6. 实现可解释 scoring。

验收：

- 给定家庭输入，可以生成至少 2 个候选方案。
- 给定朋友输入，可以生成至少 2 个候选方案。
- 每个方案包含时间线、活动、餐厅、路线、预算、推荐理由和风险提醒。
- `tool_logs` 可展示每次工具调用结果。

---

## 阶段 3：Agent API 与 Human-in-the-loop（已完成）

目标：打通规划和确认执行两个核心接口。

任务：

1. 实现 `POST /api/agent/plan` 和 `POST /api/agent/plan/stream`。
2. 实现 session 保存，记录用户输入、意图、候选方案和工具日志。
3. 实现 `POST /api/agent/confirm` 和 `POST /api/agent/confirm/stream`。
4. 确认前禁止调用预约、订位、下单工具。
5. 确认后执行活动预约、餐厅/饮品订位、团购券订单和配送订单创建。
6. 生成执行结果和可转发消息。

验收：

- `/api/agent/plan` 只返回方案，不生成订单。
- `/api/agent/confirm` 可以根据 `plan_id` 执行 Mock 预约 / 下单。
- 不存在的 `plan_id` 返回明确错误。

---

## 阶段 4：前端 Demo（已完成）

目标：完成黑客松演示所需的主流程页面。

任务：

1. 实现自然语言输入区和示例输入。
2. 展示 Agent 回复。
3. 展示工具调用日志。
4. 展示候选方案卡片。
5. 实现“确认并安排”按钮。
6. 展示执行结果、订单信息和可复制转发消息。
7. 增加 loading、error 和空状态。

验收：

- 用户可以从前端输入需求并看到候选方案。
- 用户可以点击确认并看到执行结果。
- 工具日志能帮助评委理解 Agent 的工作过程。

---

## 阶段 5：LangGraph 与多 Agent 结构（已完成）

目标：把 MVP 的流程整理成清晰的 Agent 节点。

任务：

1. 定义 `AgentState`。
2. 实现 LangGraph Orchestrator。
3. 拆分节点：
   - Input Safety Agent
   - Memory Agent
   - Rewrite Agent
   - Intent Agent
   - Planner Agent
   - Reflection Agent
   - Guardrails Agent
   - Executor Agent
   - Message Agent
4. 保留规则兜底，避免 LLM 不可用时 Demo 失效。

验收：

- Agent 流程可以通过 LangGraph 或等价编排运行。
- 节点职责清晰，便于在演示中说明 Multi-Agent 设计。

---

## 阶段 6：Reflection、Guardrails 与 Memory（已完成）

目标：补强方案质量、执行边界和用户偏好。

任务：

1. Reflection 检查：
   - 时长是否满足 4～6 小时；
   - 是否距离过远；
   - 是否包含活动和餐厅；
   - 是否适合孩子或朋友场景；
   - 路线是否合理；
   - 是否存在不可执行环节。
2. Reflection 不通过时最多重试一次。
3. Guardrails 检查：
   - POI 是否来自 Mock Data；
   - 是否提前预约 / 下单；
   - 是否输出真实支付承诺；
   - 是否夸大预约结果。
4. 实现长期记忆读取：
   - 常用位置；
   - 孩子年龄；
   - 饮食偏好；
   - 排队和距离偏好。
5. 用户显式输入优先于长期记忆。

验收：

- 不适合儿童、过远、无位、排队过长等情况能被过滤、降权或提示。
- 确认前不会产生订单。
- 用户记忆能影响推荐结果。

---

## 阶段 7：测试与演示打磨（已完成）

目标：降低 Demo 翻车风险，并准备可讲解亮点。

任务：

1. 增加后端测试：
   - `test_intent_parser.py`
   - `test_scorer.py`
   - `test_tools.py`
   - `test_plan_flow.py`
2. 覆盖家庭和朋友两条主流程。
3. 覆盖确认前不下单、确认后生成订单。
4. 覆盖一个预约失败 fallback 案例。
5. 整理 README：
   - 项目简介；
   - 技术栈；
   - 启动方式；
   - 环境变量；
   - Demo 输入；
   - Agent 架构；
   - Mock API 说明；
   - 赛题亮点；
   - 后续优化。
6. 准备不超过 2 页的 `docs/design.md`。

验收：

- 关键测试通过。
- README 能让别人独立启动 Demo。
- 演示路径稳定，异常案例可控。

---

## 阶段 8：语义一致性与多轮修改打磨（已完成）

目标：解决多轮修改时“新增需求误删旧活动”“否定语义写死到某个商品”“timeline 和 actions 不一致”等问题。

任务：

1. 抽象通用语义规则，覆盖保留、替换、新增、删除、锁定槽位和人数覆盖。
2. 多轮修改支持 `keep_slots`、`replace_slots`、`add_slots`、`remove_slots`、`locked_slots` 和 `intent_patch`。
3. 将主活动、额外活动、餐饮、饮品、配送统一到 timeline、selected_refs 和 actions。
4. Reflection / Guardrails 对需求缺失、隐藏 action、饭后饮品顺序等可修复问题触发一次重新生成。
5. 前端方案卡片显示识别人数，并展示额外活动、饮品和配送。

验收：

- “下午桌游，晚饭后喝酒”等明确需求不会被上一轮上下文覆盖或删除。
- “不要某个商品/餐厅/活动”按领域和槽位泛化处理，不写死成鲜花等特例。
- 方案不可执行或不满足明确需求时，会返回规划节点重试，而不是直接展示明显不合理结果。

---

## 优先级

### P0：已完成

- FastAPI 后端启动；
- Next.js 前端启动；
- Mock Data；
- Mock API；
- 基础工具调用；
- `/api/agent/plan`；
- `/api/agent/confirm`；
- 前端输入、方案展示和确认执行；
- 用户确认后 Mock 预约 / 订单。

### P1：已完成

- LangGraph；
- Reflection；
- Guardrails；
- Tool logs；
- Memory；
- DeepSeek 意图解析。

### P2：已完成/部分转为可选

- 多轮对话：已支持基于上一轮方案的修改基准；
- 更精致的 UI：已完成可演示卡片、流式过程、修改基准、确认执行；
- 更多异常案例：已覆盖输入安全、LLM 失败、无数据、预约失败、语义缺失、风控阻断；
- 设计文档和演示说明：已完成 `docs/design.md` 与 README 更新。

### 可选后续增强

- MCP Adapter；
- 真实地图 / 真实交易 / 真实库存 API；
- 前端 E2E 测试；
- 持久化数据库；
- 更多城市、商圈和真实业务字段。

---

## 当前交付结论

1. 阶段 0～8 已完成，当前仓库具备完整代码、Mock 数据、测试和设计文档。
2. 规划阶段只读工具和 Mock Data；确认阶段才写入预约、订单和配送订单。
3. LLM 不可用时可规则兜底，LLM 输出必须经过本地校验、Reflection 和 Guardrails。
4. 后续若接真实业务 API，优先从 Tool Interface / MCP Adapter 替换 Mock API，保持 Agent 编排不变。

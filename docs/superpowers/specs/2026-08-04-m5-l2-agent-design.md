# M5 — L2 Python Agent 层设计

> 里程碑：M5（P1）。在 M1–M4 已完成的 L1 只读知识库底座之上，构建 L2 Agent 层——"大脑"：拆解问题 → 多跳检索编排 → 自评重试 → 带引用总结返回，并对外暴露成 OpenAI 兼容端点供 L3 调用。
> 关联文档：[architecture_3layer.md](../../architecture_3layer.md) §3、[CLAUDE.md](../../CLAUDE.md) 硬约束 4/5。
> 状态：设计定稿，待落实现计划。

---

## 一、定位与范围

**L2 是"大脑"**：不持有知识，只持有"怎么找知识、找够了没、怎么答"的推理能力。用 Python 实现（`openai` SDK 驱动工具循环 + FastAPI 暴露 OpenAI 兼容端点），对外暴露成 OpenAI 兼容端点，让 L3 Open WebUI 把它当成一个叫 `kb-agent` 的模型来调。

**为什么 Python（不是 pi/TypeScript）**：L1 全栈 Python、DeepSeek 配置已在 Python 侧、`openai`/`fastapi`/`httpx` 依赖已就位，引入 TS/Node 工具链的跨语言重写成本不划算。L1 是语言无关的只读底座，pi 作为另一个潜在消费者保留可能，但不再是 L2 实现（详见 architecture_3layer.md §3.1/§3.4）。

**范围（M5 做）**：
- `config.py`（环境变量可覆盖的 L1/LLM 配置）
- `l1_client.py`（薄 httpx 客户端，封装 L1 的 6 个 GET 端点）
- `tools.py`（5 工具：JSON schema + 执行函数，薄封装 l1_client）
- `agent.py`（~80 行工具循环：openai SDK stream → 解析 tool_calls → 派发 → 回填 → 自评收敛）
- `prompts.py`（system prompt：拆解/多跳/自评/引用+gap）
- `server.py`（FastAPI：`POST /v1/chat/completions` 流式 SSE + `GET /v1/models` + `GET /health`）
- `tests/`（单测 mock LLM/L1 + e2e 真 L1+真 LLM）

**范围（M5 不做，留后续）**：
- 多模态、权限按部门隔离（L1 侧能力，M5 不接入）、模型路由/大小模型分工、`python-dotenv`/`.env` 加载（避免 key 落盘风险）。

---

## 二、目录结构

```
l2_agent/
├── __init__.py
├── config.py        # L1_BASE_URL / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 等（env 可覆盖）
├── l1_client.py     # 薄 httpx 客户端，封装 L1 的 6 个 GET 端点
├── tools.py         # 5 工具定义（OpenAI function-calling JSON schema + 执行函数）
├── agent.py         # 工具循环：stream LLM → 解析 tool_calls → 派发 → 回填 → 自评收敛
├── prompts.py       # system prompt（拆解/多跳/自评/引用+gap 标注）
├── server.py        # FastAPI: POST /v1/chat/completions（流式 SSE）+ GET /v1/models + GET /health
└── tests/
    ├── test_l1_client.py
    ├── test_tools.py
    ├── test_agent.py
    ├── test_server.py
    └── test_e2e_agent.py   # 真 L1 + 真 LLM（-m e2e）
```

`pyproject.toml`：M5 复用仓库既有 `openai`/`fastapi`/`httpx`/`uvicorn` 依赖（M4 已声明），不新增运行时依赖。开发依赖 `pytest`（已有）。

---

## 三、5 工具（薄封装 L1 REST）

工具边界严格只读（硬约束 2）：前 4 个工具调 L1 的 GET 端点，第 5 个 `grade_relevance` 是本地自评、不调 L1。工具执行后回填给 LLM 的是**精简结构化 JSON**，不是 L1 原始响应（控制多跳上下文膨胀）。

| 工具 | L1 端点 | 作用 | 返回给 LLM 的精简出参 |
|---|---|---|---|
| `list_categories` | `GET /categories` | 浏览分类（source/entity/concept/process） | `[{type, count}]` |
| `list_documents` | `GET /documents?type=&page=&page_size=` | 列候选文档 | `{items:[{slug,type,title,section_count,updated}], page, total}` |
| `grep_docs` | `GET /search?q=&top_k=` | BM25 精确召回 | `{query, total, hits:[{doc_id,section_id,title,snippet,score}]}`（snippet ≤500 字符 × ≤10 条） |
| `read_section` | `GET /documents/{slug}` | 加载原文，客户端过滤到目标 section_id | `{slug, section_id, title, body}`（仅目标 section 的 body，带行号） |
| `grade_relevance` | （本地，无 L1 调用） | 结构化自评 | `{sufficient:bool, missing:[str], next_action:str}` |

### 工具 schema（OpenAI function-calling 格式）

```json
[
  {
    "type": "function",
    "function": {
      "name": "list_categories",
      "description": "列出知识库的所有分类及其文档数，用于定位检索范围。",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_documents",
      "description": "列出某分类下的文档清单（分页），用于缩小候选范围。",
      "parameters": {
        "type": "object",
        "properties": {
          "type": {"type": "string", "enum": ["source","entity","concept","process"]},
          "page": {"type": "integer", "default": 1},
          "page_size": {"type": "integer", "default": 50}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "grep_docs",
      "description": "用 BM25 在知识库全文精确召回片段，返回命中 section 的 snippet+score+来源。",
      "parameters": {
        "type": "object",
        "properties": {
          "q": {"type": "string", "description": "检索查询词"},
          "top_k": {"type": "integer", "default": 10}
        },
        "required": ["q"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_section",
      "description": "加载某文档某 section 的原文 body（带行号），用于精确读取已召回的内容。",
      "parameters": {
        "type": "object",
        "properties": {
          "slug": {"type": "string", "description": "文档 slug"},
          "section_id": {"type": "string", "description": "section 标识，如 s0/s1"}
        },
        "required": ["slug", "section_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "grade_relevance",
      "description": "自评当前已检索信息是否充分回答用户问题。每个检索回合后调用。",
      "parameters": {
        "type": "object",
        "properties": {
          "sufficient": {"type": "boolean", "description": "信息是否已充分回答用户问题"},
          "missing": {"type": "array", "items": {"type": "string"}, "description": "仍缺失的信息点"},
          "next_action": {"type": "string", "description": "若不充分，下一步检索动作"}
        },
        "required": ["sufficient", "missing", "next_action"]
      }
    }
  }
]
```

### 执行函数设计点

- 前 4 个工具调 `l1_client` 后精简（去掉 `source` 等冗余字段，截断超长字段）。
- `read_section`：调 `GET /documents/{slug}` 拿到全文档的 `sections`，客户端按 `section_id` 过滤出目标 section，只回填该 section 的 `body`（带行号），不回填整篇文档。
- `grep_docs`：snippet 截断 ≤500 字符，hits 上限 10 条。
- `grade_relevance`：**本地执行，无 L1 调用**——它的"执行"只是把 LLM 自己产出的结构化 `{sufficient,missing,next_action}` 原样返回为 tool result，循环控制器读 `sufficient` 字段决定收敛分支。这让重试决策可观测、可测。

---

## 四、Agent 工具循环 + 自评重试

用 `openai` SDK 的 tool-calling 能力驱动，循环控制器自写（~80 行），不依赖任何 agent 框架。

### 控制流（单次用户提问）

```
run_agent(messages) →
  loop (max_turns=MAX_TURNS=10):
    1. 调 LLM: client.chat.completions.create(model, messages, tools=TOOLS, stream=True)
       → 流式产出 assistant message（text deltas + tool_calls）
    2. 把 assistant message 追加进 messages
    3. 若无 tool_calls → 循环结束（LLM 已产出最终答案文本），break
    4. 逐个执行 tool_calls：
       - 前 4 个工具 → 调 l1_client，取精简结果
       - grade_relevance → 不调 L1，返回结构化判定
       每个 tool result 追加进 messages（role=tool, tool_call_id=...）
    5. 检查本回合是否调过 grade_relevance：
       - 若 sufficient=true → 注入一条 system 指令"信息已充分，请整合带引用答案，勿再检索"，
         下回合 LLM 直接产出最终文本 → 第 3 步 break
       - 若 sufficient=false → 把 missing/next_action 透传给 LLM（已在 tool result 里），
         循环继续，LLM 据此发起下一轮检索
    6. 若达 max_turns 仍未 sufficient → 注入"已达检索上限，基于现有信息整合带引用答案并标注未覆盖"
       → 下回合强制收尾
  return messages（含最终答案 + 全程工具轨迹）
```

### 关键设计点

**1. 自评收敛而非无限重试。** `grade_relevance.sufficient` 是循环的收敛开关：
- `true` → 主动引导 LLM 收尾整合（不再检索），保证不空转。
- `false` + `missing/next_action` → LLM 拿到明确的"缺什么、下一步干嘛"，把召回率从一次性概率事件变成可迭代收敛的确定过程——这是硬约束 4"基于 Agent 非工作流"的技术内核。
- `max_turns=10` 兜底：防 LLM 陷入"检索-自评-再检索"死循环。到上限强制收尾并标注 gap（借鉴 gbrain gap analysis），宁可诚实说"知识库未覆盖 X"，也不硬编。

**2. 多跳天然由 LLM 自主规划。** 不写"先 list_categories 再 grep 再 read_section"的固定流水线。system prompt 给的是能力与原则（"你可用这 5 个工具，自主决定调什么、何时调、调几次，跨文档反复取直到信息充分"），具体调序由 LLM 对当前问题的判断决定。

**3. 工具结果精简回填。** 每个工具执行后回填精简结构化 JSON（§3 表中的精简出参），不是 L1 原始响应。`read_section` 只回填目标 section body，`grep_docs` 截断 snippet 数量与长度。控制多跳累积下的上下文膨胀。

**4. 流式与循环的关系。** LLM 的文本 delta 在每个回合内实时流式产出（SSE 推给 L3）。工具调用本身不流式给前端。循环控制器在"等 LLM 这一回合说完"和"执行工具"之间是同步的，但"LLM 说文本"的过程是流式的。

**5. 最终答案的引用与 gap 标注。** system prompt 强制：整合阶段答案必须带来源引用（`[文档slug §section_id]` 形式，对应 L1 的 doc_id+section_id，可点击回溯），并显式标注"知识库未覆盖：…"。引用来源来自 `grep_docs`/`read_section` 调用记录的 doc_id+section_id，循环控制器在收尾时可汇总成"本次回答依据"附在答案后。

### system prompt 骨架（`prompts.py`）

```
你是企业知识库问答 Agent。你的工具边界严格限定为只读检索知识库（list_categories/
list_documents/grep_docs/read_section/grade_relevance），绝不执行任何写/操作类动作。

工作方式（自主规划，非固定流水线）：
1. 拆解用户问题为可检索子目标。
2. 用工具多跳检索：定位→缩小→精确召回→按需加载原文，跨文档反复取。
3. 每个检索回合后调 grade_relevance 自评：sufficient=false 时据 missing/next_action
   改写查询/换文档/再 grep，把召回收敛到充分。
4. sufficient=true 后整合答案。

答案规范：
- 带来源引用：关键结论后标 [slug §section_id]，对应你 read_section/grep_docs 取到的文档。
- 标注知识缺口：若知识库未覆盖某部分，明确写"知识库未覆盖：…"，不臆造。
- 仅基于已检索到的知识回答，不编造未检索的内容。
```

### 多跳示例（对应 architecture_3layer.md §6 序列图）

问题"数据产品 A 接口怎么调 + 依赖哪张数据表"：
1. LLM 调 `grep_docs(q="产品A 接口")` → 命中 data_product 文档片段
2. `read_section(slug=..., section_id=s0)` → 取接口说明原文
3. `grade_relevance` → `sufficient=false, missing=["依赖的数据表"], next_action="grep 数据表"`
4. `grep_docs(q="产品A 数据表 依赖")` → 命中 data_table 文档
5. `read_section(...)` → 取数据表原文
6. `grade_relevance` → `sufficient=true`
7. 整合：带引用答案 + 引用块 `[产品A接口slug §s0]`、`[数据表slug §s0]`

---

## 五、OpenAI 兼容端点 + 流式 SSE

把整个 Agent 包成 OpenAI 兼容的 `/v1/chat/completions`，L3 Open WebUI 把它当成一个叫 `kb-agent` 的模型调，零感知。

### 端点（`server.py`）

| 路由 | 方法 | 作用 |
|---|---|---|
| `POST /v1/chat/completions` | POST | OpenAI 兼容主端点；支持 `stream: true/false` |
| `GET /v1/models` | GET | 返回 `[{id:"kb-agent", object:"model"}]`，Open WebUI 拉模型列表用 |
| `GET /health` | GET | L2 自身存活 + 依赖探测（L1 `/health` 可达、LLM 端点可配） |

### 请求/响应映射

- **入参**：`messages`（多轮对话历史直接透传给 LLM 作为上下文）、`stream`、`model`（忽略——L2 固定用配置的 LLM 模型）、`temperature`（透传）。
- **非流式响应**：标准 `ChatCompletion` 结构。`choices[0].message.content` = Agent 循环产出的最终带引用答案；`usage` 里附带 `tool_calls_count`（本回答调了几次 L1 工具，供观测，不破坏 OpenAI schema）。
- **流式响应**：SSE `text/event-stream`。每个 token 产出 `data: {"choices":[{"delta":{"content":"..."}}]}`，结束发 `data: [DONE]`。

### 流式关键设计

**只流最终答案，工具过程不流给前端。**
- Agent 循环逐回合调 LLM（`stream=True`）。中间回合（还在检索/自评阶段）的 token delta 不外吐：它们是 LLM 的"思考草稿"，前端看会困惑。
- 循环控制器维护内部缓冲：每回合收完 delta 后判断——若该回合产生了 `tool_calls`（还在干活），丢弃文本 delta；若该回合无 tool_calls 且 sufficient 已达（进入整合收尾），这一回合的 token delta 才实时外吐成 SSE。
- 收尾回合的引用/gap 标注随 LLM 文本自然流出，L3 用 Open WebUI 原生 markdown 渲染。

> 前端体验 = 用户提问后稍等（L2 在后台多跳检索），然后最终答案整段流式打出。不暴露中间检索轨迹，但答案末尾的"本次回答依据：[slug §section_id]"引用块可见。

### 多轮对话

L3 发来的 `messages` 已含历史。L2 把历史原样作为前缀传给 LLM（让 LLM 知道上下文），但新一轮的工具调用从当前用户消息开始独立循环（不把上一轮的工具 result 带进来——那些是上一轮已收敛的检索，不该污染本轮上下文）。若本轮问题依赖上一轮答案，LLM 会从历史 messages 读到并自主决定是否重新检索。

### 错误处理（HTTP 层）

- **L1 不可达**（工具调 `l1_client` 超时/连接拒绝）→ Agent 循环捕获，把错误塞回给 LLM 作为 tool result（`{"error":"L1 service unreachable"}`），让 LLM 自行决定重试或如实告诉用户"知识库暂时不可用"。不直接 500——保持 Agent 的自主性。
- **LLM 端点错误**（鉴权失败/限流）→ 直接 502 返回，附清晰错误信息（配置问题，Agent 重试无意义）。
- **工具参数 malformed**（LLM 产出的 tool_call 参数不符 schema）→ 返回结构化错误给 LLM，LLM 通常下一回合修正参数重试。

---

## 六、LLM 接线与配置

复用既有 DeepSeek 配置，全部走环境变量可覆盖，真 key 永不进仓库。

### 配置项（`config.py`）

| 配置项 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `L1_BASE_URL` | `L1_BASE_URL` | `http://127.0.0.1:8011` | L1 KB Service 地址（M4 的 `kb-serve`） |
| `LLM_BASE_URL` | `LLM_BASE_URL` | `https://api.deepseek.com/v1` | LLM OpenAI 兼容端点 |
| `LLM_API_KEY` | `LLM_API_KEY` | —（必填，从交互式 shell 取） | DeepSeek key |
| `LLM_MODEL` | `LLM_MODEL` | `deepseek-v4-flash` | 推理与生成模型 |
| `LLM_TIMEOUT` | `LLM_TIMEOUT` | `60` | 单次 LLM 调用超时（秒） |
| `L1_TIMEOUT` | `L1_TIMEOUT` | `10` | 单次 L1 调用超时（秒） |
| `MAX_TURNS` | `MAX_TURNS` | `10` | Agent 循环最大回合（§4 兜底） |
| `LLM_TEMPERATURE` | `LLM_TEMPERATURE` | `0.3` | 推理温度（偏低，保检索编排稳定） |

### 接线要点

**1. 单一 LLM 客户端。** `agent.py` 启动时构造一个 `openai.OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=LLM_TIMEOUT)`，全程复用。拆解、自评、整合全走这一个客户端、同一个 `deepseek-v4-flash` 模型——不引入第二个模型/端点（YAGNI；M5 不做模型路由或大小模型分工）。

**2. Key 的获取与隔离（守红线）。**
- 单测：mock LLM（monkeypatch `client.chat.completions.create`），不碰真 key、不联网。
- e2e：用真 key。取 key 方式 = `bash -lic 'echo $LLM_API_KEY'` 读交互式 shell 的环境（`~/.bashrc` 已 export），绝不在任何提交文件里写 `sk-...`。e2e 脚本里通过 `os.environ["LLM_API_KEY"]` 注入，key 只活在运行时内存。
- `.env` 文件：M5 不引入 python-dotenv / `.env` 加载（避免 key 落盘成 `.env` 误提交的风险）。key 只从真实环境变量来。

**3. L1 客户端复用 httpx。** `l1_client.py` 用一个共享 `httpx.Client(base_url=L1_BASE_URL, timeout=L1_TIMEOUT)`，6 个 GET 方法薄封装：`get_categories()` / `get_documents(type,page,page_size)` / `get_search(q,top_k)` / `get_document(slug)` / `get_index()` / `get_health()`。连接复用、超时统一。

**4. 配置加载与 PEP 562。** 跟 L1 的 `config.py` 风格一致（L1 用 `__getattr__` 懒解析 `WIKI_ROOT`）。M5 的 `config.py` 同样做成模块级懒求值 + `os.getenv` 覆盖——monkeypatch `setenv` 即可单测，无需复杂 fixture。

**5. 启动校验。** `server.py` 启动时调一次 `GET /health`（自身）+ 探测 L1 `/health`：
- L1 不可达 → log warning（不阻断启动，L1 可能稍后起来；Agent 调用时再按 §5 错误处理降级）。
- `LLM_API_KEY` 缺失 → fail-fast（没 key Agent 无法工作，早点报错比运行时空转好）。

---

## 七、测试策略

测试分三层，沿用 M1–M4 既有约定（单测 mock、e2e 走真 key/真 L1）。

### 1. 单测层（mock LLM + mock L1，全离线、全确定性）

| 文件 | 覆盖 | 手法 |
|---|---|---|
| `test_l1_client.py` | 6 个 GET 方法的请求构造、超时、错误传播 | mock `httpx.Client`，断言 URL/参数/解析 |
| `test_tools.py` | 5 工具 schema 合法性 + 执行函数：前 4 个调 l1_client 后精简；`read_section` 客户端过滤；`grep_docs` 截断；`grade_relevance` 本地无 L1 调用 | mock l1_client，喂构造响应，断言精简出参形状 |
| `test_agent.py` | 循环控制流：有 tool_calls → 派发 → 回填 → 再循环；`sufficient=true` → 收尾；`sufficient=false` → 继续；`max_turns` 兜底强制收尾并标注 gap | mock LLM `chat.completions.create` 返回脚本化多回合序列（第 1 回合 tool_call、第 2 回合 grade false、第 3 回合 grade true + 最终文本），断言消息序列与收敛分支 |
| `test_server.py` | `/v1/chat/completions` 非流式 + 流式 SSE 格式、`/v1/models`、`/health`、错误码（LLM 错误→502、L1 错误降级不 500） | mock agent.run_agent，FastAPI TestClient |

**关键**：`test_agent.py` 用脚本化 mock 验证控制流——不测"LLM 真的会不会多跳"（那是 e2e 的事），只测"给定 LLM 的某种返回序列，循环控制器是否正确派发/收敛/兜底"。这让循环逻辑 100% 可测、不依赖网络。

### 2. e2e 层（真 L1 + 真 LLM）

`test_e2e_agent.py`——前置：`kb-serve` 起在 8011（真 L1，指向测试 wiki），真 DeepSeek key 从 `bash -lic 'echo $LLM_API_KEY'` 注入。

| 用例 | 验收 |
|---|---|
| 单跳：grep 一个字段名 → 答案含该字段 + 引用 `[slug §section_id]` | 引用可回溯到真实 section |
| 多跳：§四的"接口用法 + 依赖数据表"两跳问题 | 答案同时覆盖两个子目标，引用跨两类文档 |
| gap 标注：问知识库没有的内容 | 答案显式"知识库未覆盖：…"，不臆造 |
| `max_turns`：构造需极多跳的问题 | 到上限强制收尾，答案标注未充分检索 |
| 流式：`stream=true` | SSE 连续 `data: {...}` 末尾 `[DONE]`，最终文本可拼回 |

e2e 不在 CI 强制跑（依赖真 key + 真 L1），本地手动跑或显式 `pytest -m e2e`。

### 3. 约定与红线（沿用既有）

- **真 key 永不进任何提交文件**；e2e 脚本里 key 只从 `os.environ` 取，README/测试代码里只出现占位 `<LLM_API_KEY>`。
- **GPL 红线**：Agent 循环、工具封装全部自写，不引入任何 GPL agent 框架源码。
- **只读边界**：e2e 验证全程只命中 L1 的 6 个 GET 端点，无写入/执行（与 M4 一致，grep 守护）。
- **解释器**：`.venv/bin/python` + `.venv/bin/pytest`。

---

## 八、验收标准（对应 CLAUDE.md P1）

1. 多跳问题能跨文档取全：§四多跳示例的"接口用法 + 依赖数据表"两跳，答案同时覆盖两个子目标。
2. 带引用返回：答案关键结论后标 `[slug §section_id]`，引用可回溯到 L1 真实 section。
3. gap 标注：问知识库未覆盖的内容，答案显式"知识库未覆盖：…"，不臆造。
4. 自评重试可观测：`grade_relevance` 的 `sufficient` 驱动收敛，`max_turns` 兜底强制收尾。
5. OpenAI 兼容：L3 Open WebUI 把 L2 当 `kb-agent` 模型调，流式 SSE 答案正常打出。
6. 只读边界：全程只命中 L1 的 6 个 GET 端点，无写入/执行。
7. 单测全绿（mock），e2e 手动跑通（真 key + 真 L1）。

---

## 九、依赖与里程碑

- **依赖**：M4（L1 只读 REST API，已完成）。`openai`/`fastapi`/`httpx`/`uvicorn` 已在仓库 pyproject（M4 声明），M5 不新增运行时依赖。
- **里程碑**：M5 = P1（L2 Python Agent）。完成后进入 P2（L3 Open WebUI 集成 + 打磨）。

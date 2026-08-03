# M3 增量摄入与自更新闭环（设计）

> 关联：[PRD §9 自更新闭环](2026-07-30-p0-self-updating-kb-platform-design.md)、[M2 wiki 层设计](2026-07-31-m2-wiki-compounding-layer-design.md)。
> 本设计以 M2 已落地的 wiki 层为底座，补齐 PRD §9 增量摄入能力。M2 的 `source_identity`（绝对 md 路径）与 `sources: []` bug **不动**，M3 旁路建增量层。

---

## 一、范围与不做

### M3 做（手动增量闭环，对齐 PRD §9 但砍掉 watch）

1. **`hash.json`** —— raw 层变更检测（键=slug，值=raw 字节 sha256 + raw 相对路径 + ingested_at）。
2. **`ingest_log.jsonl`** —— append-only 时序日志（ingest add/modify/delete + lint + rebuild 行）。
3. **`kb ingest` 升级** —— 扫 raw/ 对比 hash.json 得 add/modify/delete 三态，delete 精准反向清 wiki 页，add/modify 走 clean→ingest（clean 仍手动，ingest 内部对 modify = delete-then-add 消 orphan）。
4. **`kb lint`** —— 五项确定性自检 → `lint_report.json` + 终端摘要。
5. **`kb rebuild`** —— 清生成物从 raw 全量重建。

### M3 不做

- **`kb watch`**（常驻监听 / 持久化队列 / 状态机 / 崩溃恢复 / 去抖动 / 自写抑制）—— 全砍，手动闭环。
- **向量 / `vectors/` / 稳定键删除** —— M2 无向量；lint 的"向量一致性"转为"wiki 页↔index.md 对齐"。
- **不碰 M2 身份模型** —— `source_identity`（绝对 md 路径）+ `sources: []` bug 原样保留，增量层旁路。
- **不引入新外部依赖** —— 无 watchdog。

### 关键约束（已确认）

- 变更检测基准 = 新增 `hash.json`（方案 A），`ingest-cache.json` 保留为 wiki 层跳过缓存，两者并存。
- delete 用 `ingest-cache[identity].paths[]` 作为唯一权威页列表做精准反向清理。
- add/modify 需手动 `kb clean` 生成/更新 md；delete 顺手删 md。
- DEEPSEEK `deepseek-v4-flash`，单测 mock / e2e 真key；GPL 红线（llm_wiki 只借鉴工程方法，用 Python 重实现）。
- 独立项目：不外依赖其他目录；仅文档查询不执行动作（M3 写生成物属离线摄入脚本，非 Agent 工具）。

---

## 二、身份模型与 raw→wiki 页映射（旁路层）

不动 M2 的 `source_identity`（绝对 md 路径），M3 在其外建一条旁路映射链：

```
raw 相对路径  ──doc_id──▶  hash.json 键（slug）   （M3 新增，raw 层权威）
                ║
                ║  (raw_path 与 md 文件名共享 doc_id 前缀)
                ▼
md 文件名      ──identity──▶  ingest-cache 键      （M2 既有，wiki 层跳过缓存）
   {doc_id}__{hash8}.md          └─ paths[] ──▶ wiki 页列表（唯一权威正向索引）
```

### 关键约定

- **`doc_id`** 沿用 M1 `make_doc_id`（`slug(raw相对路径) + '__' + sha256(raw字节)[:8]`）。
- **hash.json 的键只用 slug 部分**（如 `data_table_order_detail`），**不含 `__hash8`** —— 同一 raw 路径重清洗后 hash8 会变，slug 才是稳定身份。slug = `doc_id` 去掉 `__{8位hex}` 后缀。
- **`raw_path`**：相对 `raw_root` 的 POSIX 路径（`data_table/order_detail.xlsx`）。
- **raw → md 的链接**：M1 `clean_one` 写 `md/{category}/{doc_id}__{hash8}.md`。M3 通过 **glob `md/**/{slug}__*.md`** 反查 md 文件（slug 去掉 `__hash8`）。旁路，不改 M1/M2 代码。
- **md → wiki 页**：用 md 文件的**绝对路径字符串**作为 `source_identity` 查 `ingest-cache`（与 M2 cache key 一致），取 `paths[]`。
- **delete 路径**：raw 没了 → 从 hash.json 得 `slug` → glob 找到 md 文件 → md 绝对路径 = `source_identity` → 查 `ingest-cache[identity].paths[]` → 精准删这些 wiki 页。

### 精准反向清理规则

遍历 `paths[]` 每个 wiki 页：

- 若该页 `sources` frontmatter 只含被删源 → **整页删**。
- 若是多源页（`sources` 含其他源）→ **保留页，只删该源的 `## 来源补充: {identity}` 段落** + 从 `sources[]` 移除该 identity + `updated=today`。
- **因现状 `sources: []` 全坏**，实际行为退化为：**按 `paths[]` 全删** + lint 报孤儿兜底（L3）。delete 后 `rebuild_index` 重算。
- 删 wiki 页后：删 md 文件、删 `ingest-cache[identity]`、删 `hash.json[slug]`、`ingest_log.jsonl` 追加 `delete` 行。

### ingest_log.jsonl 行格式（对齐 PRD §9.7）

```json
{"ts":"2026-08-03","type":"ingest","doc_id":"data_table_order_detail","action":"add","source":"data_table/order_detail.xlsx"}
{"ts":"2026-08-03","type":"ingest","doc_id":"data_table_order_detail","action":"modify","source":"data_table/order_detail.xlsx"}
{"ts":"2026-08-03","type":"delete","doc_id":"data_table_order_detail","source":"data_table/order_detail.xlsx"}
{"ts":"2026-08-03","type":"lint","issues":5,"errors":1,"warnings":3,"info":1}
{"ts":"2026-08-03","type":"rebuild"}
```

`ts` 用 `config.today()` 日期粒度（不引入实时时钟，与 M2 一致、可测试）。

### hash.json 格式

```json
{
  "data_table_order_detail": {
    "hash": "sha256:a3f9c1e2...",
    "path": "data_table/order_detail.xlsx",
    "ingested_at": "2026-08-03"
  }
}
```

---

## 三、增量三态流程（kb ingest 升级）

`kb ingest` 从"吃 md、按 cache 跳过"升级为"扫 raw、三态分发"。

### 入口判别

`kb ingest <path>` 自动判别：
- path 在 `raw_root` 下 → **raw 三态模式**（默认主路径）。
- path 在 `md_root` 下 → **M2 直摄入模式**（向后兼容）。

### raw 三态模式流程

```
扫 path 下的 raw 文件（SUPPORTED_EXTS）
对每个 raw 文件：
  doc_id = make_doc_id(raw_root, f)          # M1
  slug   = doc_id 的 slug 部分
  h      = sha256(raw 字节)
  对比 hash.json[slug]:
    ├─ 无记录 + 文件存在         → ADD
    ├─ 有记录 + hash 变了         → MODIFY
    ├─ 有记录 + hash 不变         → SKIP（不动）
    └─ hash.json 有记录 + 文件没了 → DELETE（扫描后统一处理删除集）
```

### ADD / MODIFY 处理（需 md 就绪）

- 先 glob `md/**/{slug}__*.md` 找 md 文件。
- **找不到 md** → warn 提示"请先 `kb clean <raw>`"，记 `ingest_log` action=`skipped_no_md`，continue（不崩批次）。
- **找到 md** → 调 M2 `ingest_source(md_path, identity=md绝对路径, ...)`。
  - **ADD**：cache 必然 miss，正常摄入。
  - **MODIFY 关键点**：M2 `ingest_source` 对 cache hit 会 early-return `skipped_cached`，但 cache 存的是**旧 md 文本哈希**。用户已 `kb clean` 重生成 md（raw 变→md 变）→ 新 md 文本哈希 ≠ cache 哈希 → cache miss → 自然重摄入。**modify 不需强制 invalidate cache**——只要 md 被 clean 重写，cache 自动失效。这是方案 A "并存"的妙处。
  - 但 modify 时旧 wiki 页会变 orphan（M2 不删旧 slug 页）。**M3 在 modify 时先做一次"该源的精准清理"**：用 `ingest-cache[identity].paths[]` 删旧页，再 ingest 新页。即 **modify = delete-then-add**（复用 delete 清理逻辑）。这样 modify 不留 orphan。
- 摄入成功后：更新 `hash.json[slug] = {hash, path, ingested_at}`，append `ingest_log` action=`add`/`modify`。

### DELETE 处理（扫描后统一）

- 扫完所有现存 raw 文件后，`hash.json` 里不在"现存 slug 集"的条目 = 已删除。
- 对每个删除项：执行 §二 的精准反向清理（删 wiki 页 + 删 md + 删 cache 条目 + 删 hash 条目 + append delete 行）。
- `rebuild_index(wiki_root, today)` 一次。

### 失败容错

沿用 M2 Task8-fix 的 try/except 模式：
- 单文件 ADD/MODIFY 异常 → `[ERR]` + `failed += 1` + continue，不崩批次。
- DELETE 异常 → `[ERR]` + continue。
- 末尾摘要：`完成: 新增 N, 修改 M, 删除 D, 跳过 S, 失败 F (共 C 文件)`。

### 原子性（对齐 PRD §9.2 "单文档事务"）

- 单份 raw 的"hash 更新 + wiki 写 + cache 更新 + log 追加"作为逻辑事务。任一步失败 → 该文档 failed，不更新 hash.json（下次重跑视为未完成）。
- 实现上：先做 wiki/cache 写，**最后才更新 hash.json + log**——hash.json 落盘即代表该文档事务成功。

---

## 四、kb lint（五项确定性自检）

**命令：** `kb lint [--wiki-root] [--raw-root] [--md-root] [--cache-path] [--hash-path]`

**输出：** `lint_report.json`（落盘，可 CI/diff）+ 终端人读摘要。`error` 级项 → 退出码 1。

### 五项（适配 wiki 层，无向量）

| # | 检查项 | 方法 | 严重度 |
|---|---|---|---|
| **L1** | **格式校验** | `index.md` 可解析（首行 `# Wiki Index`、各 `## {type}` 段、`- [[slug\|title]]` 行合法）；`log.md` 首行 `# Wiki Log`；`ingest_log.jsonl` 每行合法 JSON 且含 `ts/type`；`hash.json`/`ingest-cache.json` 合法 JSON | error |
| **L2** | **wiki 页 ↔ index.md 对齐** | 扫盘上所有有效 type 的 wiki 页集合 `P_disk`；解析 `index.md` 列出的 slug 集合 `P_index`。`P_disk - P_index` = index 漏列（warn）；`P_index - P_disk` = index 列了不存在的页（error，幽灵引用） | error/warn |
| **L3** | **孤儿页** | entity/concept/process 页若**无任何其他页的 `related[]` 指向它** → warn。source 页不报孤儿（入口）。因 `sources: []` 坏，**L3 退化为仅用 `related[]` 反向索引**。 | warn |
| **L4** | **缺交叉引用** | 两页 `tags[]` Jaccard 重叠 ≥ 阈值（默认 0.5）但互不在对方 `related[]` → warn。只对 entity/concept 页跑。 | warn |
| **L5** | **数据缺口** | 某 type 下页数异常少：`sources=0` 或 `process=0` 或任一 type 目录缺失 → info。 | info |

### lint_report.json 格式

```json
{
  "ts": "2026-08-03",
  "errors": 1,
  "warnings": 3,
  "info": 1,
  "issues": [
    {"code": "L2_GHOST", "level": "error", "page": "entity_foo", "msg": "index.md 列出但磁盘无此页"},
    {"code": "L3_ORPHAN", "level": "warn", "page": "concept_bar", "msg": "无 related 指向"},
    {"code": "L5_GAP", "level": "info", "type": "process", "msg": "process 类型 0 页"}
  ]
}
```

### 实现要点

- 纯确定性脚本，不调 LLM（对齐 PRD §9.4 "P0 用确定性脚本"）。
- 复用 M2 `frontmatter.parse` 读每页 frontmatter（取 type/tags/related/sources）。
- L3/L4 因 `sources: []` 现状坏掉：L3 退化为仅看 `related[]` 反向索引（扫所有页 `related`，建"被指向集"，不在其中的非 source 页 = 孤儿）；L4 只用 `tags`，不受 sources bug 影响。
- 阈值（Jaccard 0.5）放模块常量，可调。
- 末尾 append `ingest_log.jsonl` 一行 `{"type":"lint","issues":N,"errors":E,"warnings":W,"info":I}`。

---

## 五、kb rebuild（全量重建兜底）

**命令：** `kb rebuild [--raw-root] [--md-root] [--wiki-root] [--cache-path] [--hash-path] [--yes]`

**流程（对齐 PRD §9.5）：**

1. 清空生成物：`md/`、`wiki/`（保留目录壳）、`.cache/ingest-cache.json`、`hash.json`、`ingest_log.jsonl`。`raw/` 不动。
2. 全量 `kb clean raw/`（raw→md，M1 `clean_one` 逐份）。
3. 全量 `kb ingest md/`（md→wiki，走 M2 `ingest_source`；因 cache 已清，全部重跑）。
4. 全量重建 `hash.json`：扫 raw/ 逐份算 sha256 + slug 填入。
5. `rebuild_index` + append `ingest_log` 一行 `{"type":"rebuild","ts":...}`。

**安全门：** 需 `--yes` 确认（清空生成物不可逆），否则仅 dry-run 打印将清什么。原子性：先清再重建，失败可重跑（raw 是真相源，幂等）。

---

## 六、模块、文件、测试、CLI

### 新增文件

```
l1_kb/ingest/
├── incremental/
│   ├── __init__.py
│   ├── hash_store.py      # hash.json 读写：load/save/upsert/remove，键=slug
│   ├── ingest_log.py      # ingest_log.jsonl append：append_ingest/modify/delete/lint/rebuild
│   ├── change_detect.py   # 扫 raw/ 对比 hash.json → {add,modify,delete,skip} 四集
│   ├── delete.py          # 精准反向清理：paths[]→删 wiki 页(+md+cache+hash)+rebuild_index
│   └── ingest_flow.py     # 三态编排：add/modify/delete 分发，事务（hash.json 最后落盘）
├── lint/
│   ├── __init__.py
│   ├── checker.py         # L1-L5 五项检查
│   └── report.py          # lint_report.json 落盘 + 终端摘要
```

`cli/kb.py` 加 `lint`、`rebuild` 子命令；`ingest` 子命令加 raw 三态分支（自动判别 path 在 raw_root 还是 md_root）。

### config.py 新增

- `HASH_PATH`（默认 `.cache/hash.json`）
- `INGEST_LOG_PATH`（默认 `knowledge_base/ingest_log.jsonl`）

### 测试（单测全 mock LLM，e2e 用真 key）

- `test_hash_store.py`：load/save/upsert/remove、slug 键、原子写。
- `test_change_detect.py`：四态判定（add/modify/delete/skip）、raw 删除检测、空目录。
- `test_delete.py`：按 paths[] 删 wiki 页 + 删 md + 删 cache + 删 hash + log delete 行；多源页保留（现状退化全删，断言行为）；rebuild_index 后无幽灵。
- `test_ingest_flow.py`：add（无 md→warn 不崩）、modify=delete-then-add 消 orphan、delete、skip、单文件失败不崩批次、事务（hash 最后落盘）。
- `test_lint.py`：L1 格式、L2 漏列/幽灵、L3 孤儿、L4 缺交叉、L5 数据缺口；error→退码 1；report.json schema。
- `test_rebuild.py`：清生成物→全量重建→hash.json 重建；`--yes` 门；raw 不动。
- e2e `test_m3_incremental_e2e.py`（真 key）：clean→ingest(add)→改 raw→clean→ingest(modify)→删 raw→ingest(delete)→lint→search 仍命中。

### 依赖

无新增（pytest 已有；不引 watchdog）。

---

## 七、验收（对齐 PRD §16 M3）

1. **增量只处理变更**：改一份 raw → `kb clean` + `kb ingest` 只重处理那一份（hash.json 其余 SKIP）。
2. **delete 精准反向清理**：删一份 raw → 该源 wiki 页消失、md 消失、cache/hash 条目消失、`ingest_log` 有 delete 行、`rebuild_index` 后无幽灵。
3. **modify 消 orphan**：改 raw 重摄入后旧 slug 页不残留（delete-then-add）。
4. **lint 五项**：构造幽灵页/孤儿页/缺交叉/数据缺口 → `lint_report.json` 正确分类；error→退码 1。
5. **rebuild 幂等**：`kb rebuild --yes` 后 wiki 与单份摄入一致；raw 不动；可重复跑。
6. **e2e**：真 key 走完 add→modify→delete→lint→search 全链，search 在 add/modify 后命中、delete 后不命中。
7. **全测绿**（单测 mock + e2e 真key），GPL 红线零 llm_wiki 源码导入。

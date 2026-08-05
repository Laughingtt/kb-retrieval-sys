# kb_eval 完整测试评估报告

> 生成时间：2026-08-05 ｜ 数据：`kb_eval/raw`（7 份合成文档）→ `kb clean` → `kb ingest` → `kb_eval/wiki`（11 页）｜ LLM：DeepSeek（真 key）｜ L1 服务：`127.0.0.1:8011`（`WIKI_ROOT=kb_eval/wiki`）

---

## 一、评估总览

| 指标 | 结果 |
|---|---|
| 用例总数 | 10 |
| 通过数 | **10** |
| 成功率 | **100.0%** |
| 平均工具调用次数 | 9.7 次/题 |
| 平均耗时 | 14.2 秒/题 |
| 用例覆盖 | 单跳(4) · 多跳(4) · gap 未覆盖(2) |

**结论**：L1 清洗→L2 Agent 检索→带引用总结 全链路在合成知识库上验证通过。覆盖字段查询、口径查询、流程编号、跨文档多跳、字段关联、宽表分组、指标溯源、知识库未覆盖 gap 标注等典型场景。

---

## 二、每次检索：用例 × 工具调用链 × 成功

| 用例 | 类别 | 工具调用链（按顺序） | 次数 | 耗时 | 成功 |
|---|---|---|---|---|---|
| T1 | 单跳-字段查询 | `list_categories` → `grep_docs` → `read_section` → `read_section` → `grade_relevance` | 5 | 11.2s | ✅ |
| T2 | 单跳-口径查询 | `list_categories` → `grep_docs` → `grep_docs` → `read_section` ×3 → `grade_relevance` | 7 | 9.6s | ✅ |
| T3 | 单跳-流程编号 | `list_categories` → `grep_docs` → `read_section` ×4 → `grade_relevance` | 7 | 8.2s | ✅ |
| T4 | 多跳-跨文档 | `list_categories` → `list_documents` ×3 → `read_section` → `grep_docs` → `read_section` ×6 → `grade_relevance` | 13 | 15.4s | ✅ |
| T5 | 多跳-字段关联 | `list_categories` → `grep_docs` → `read_section` ×5 → `grade_relevance` | 8 | 11.7s | ✅ |
| T6 | 单跳-宽表分组 | `list_categories` → `grep_docs` → `read_section` ×8 → `grade_relevance` | 11 | 15.9s | ✅ |
| T7 | 多跳-指标溯源 | `list_categories` → `grep_docs` ×2 → `read_section` ×3 → `grep_docs` ×2 → `grade_relevance` | 9 | 20.1s | ✅ |
| T8 | gap-未覆盖 | `list_categories` → `grep_docs` ×2 → `list_documents` ×3 → `grep_docs` ×5 → `read_section` → `grade_relevance` | 13 | 19.7s | ✅ |
| T9 | gap-未覆盖 | `list_categories` → `grep_docs` ×2 → `list_documents` ×4 → `grep_docs` ×4 → `grade_relevance` | 12 | 13.9s | ✅ |
| T10 | 多跳-指标+来源 | `list_categories` → `list_documents` ×3 → `grep_docs` → `read_section` ×4 → `grep_docs` → `read_section` → `grade_relevance` | 12 | 15.9s | ✅ |

**工具调用统计（全 10 题）**：`list_categories` 10 次（每题首轮摸库）｜`grep_docs` 32 次（主力检索）｜`read_section` 39 次（精读取字段/口径）｜`list_documents` 13 次（多跳/gap 时穷举文档清单）｜`grade_relevance` 10 次（每题收敛自评，均判定 sufficient 后收尾）。

**观察**：
- 单跳题工具次数 5–7；多跳题 8–13；gap 题 12–13（需穷尽检索多关键词后才能确证"未覆盖"，符合 Agent 自主多跳 + gap 标注设计）。
- 每题均以 `grade_relevance`（本地自评，不调 L1）作为收敛门，判定 `sufficient=true` 后进入最终答案回合，验证了"自评重试"闭环。
- 答案均带 `[doc_id §section]` 形式引用（如 `[concepts_metrics_dictionary__f6398716 §s3]`）。

---

## 三、清洗后的 wiki（`kb_eval/wiki`，11 页）

### 3.1 页面清单与分类

| 类型 | 页数 | 页面 |
|---|---|---|
| source（原件摘要） | 7 | process_data_asset_request / concepts_metrics_dictionary / data_product_api_doc / data_product_order_dashboard / data_table_order_master / data_table_order_wide / data_table_order_detail |
| entity（业务实体） | 2 | entity_order_wide（订单宽表）/ entity_order_detail（订单明细表） |
| concept（业务概念） | 2 | concept_line_total（行小计）/ concept_gift_line（赠品行） |
| process | 0 | （LLM 将流程文档归纳为 source 类型，lint 报 L5_GAP info，非 bug） |

> `kb ingest` 的 LLM 两步归纳：第 1 步把 7 份 md → 7 张 source 摘要页；第 2 步从字段/口径中提炼出 2 个 entity + 2 个 concept，共 11 页。`kb index` 重建 `wiki/index.md`，`kb lint` 0 error / 1 warning(L4_XREF) / 1 info(L5_GAP)。

### 3.2 index.md（自动生成的导航）

```
## 原件摘要
- [[process_data_asset_request__9f289891|公司数据资产申请流程]]
- [[concepts_metrics_dictionary__f6398716|指标口径字典]]
- [[data_product_api_doc__0108a811|数据产品 API 文档]]
- [[data_product_order_dashboard__bc1a6114|数据产品：订单分析看板]]
- [[data_table_order_master__c1af9ac2|订单主表字段说明]]
- [[data_table_order_wide__35959b78|订单宽表字段说明]]
- [[data_table_order_detail__9159e82a|订单明细表字段说明]]
## 业务实体
- [[entity_order_wide|订单宽表]]  - [[entity_order_detail|订单明细表]]
## 业务概念
- [[concept_line_total|行小计]]  - [[concept_gift_line|赠品行]]
```

### 3.3 清洗产物示例：宽表分组（F4 生效）

原始 Excel `order_wide.xlsx` 共 30 列（>20 阈值），ExcelCleaner 按**字段前缀分组**拆为子 section（豁免 200 行二次切分）：

```
## order_wide — order        (order_id / order_name / order_status)
## order_wide — amount       (amount_total / amount_tax / amount_discount)
## order_wide — time         (time_create / time_pay / time_ship)
## order_wide — extra        (extra_0 ~ extra_14，15 列扩展)
## order_wide — Unnamed: 24~29  (6 列未命名，单独成组)
```

T6 查询"宽表多少字段/怎么分组"时，Agent 跨 8 个子 section 精读后正确回答"具名 24 + 未命名 6 = 30，按 order/amount/time/extra 四组 + 未命名组"，验证宽表清洗 + 检索联动。

---

## 四、用例与答案摘要

| 用例 | 问题 | 答案要点（均带引用） |
|---|---|---|
| T1 | order_pay_amount 含义 | decimal(12,2) 实付金额 = order_total_amount − discount_amount；GMV 取此字段而非总额 |
| T2 | GMV 口径+纳入状态 | sum(order_pay_amount) where status in (PAID, SHIPPED, DONE)；不含退款/PENDING/赠品 |
| T3 | 数据资产申请流程编号+步数 | PRC-2024-010，6 步（提交→上级→DataOwner→安全合规→开通→续期） |
| T4 | 看板接入方式+API路径+流程编号 | 3 种：Web看板/API/数据导出；API 路径 /api/v1/orders，流程编号 PRC-2024-003 |
| T5 | line_total 计算+DQ规则 | line_total = qty × unit_price − discount_amount；DQ 规则 line_total<0 告警 |
| T6 | 宽表字段数+分组 | 30 列（具名24+未命名6），按 order/amount/time/extra 分组 |
| T7 | 退货率口径+状态 | 退货订单数(status=RETURNED)/已发货订单数(status in SHIPPED,DONE,RETURNED) |
| T8 | 员工薪酬体系 | **知识库未覆盖**——多轮穷尽检索 0 命中，明确标注 |
| T9 | 报销流程审批层级 | **知识库未覆盖**——检索命中的均为数据领域流程，明确标注 |
| T10 | 复购率算法+来源表+周期 | 购买≥2次用户数/有购买用户数；源表 dws_user_repurchase_m；按月 |

---

## 五、可复现

```bash
# 1. 造数据（已就绪于 kb_eval/raw/）
.venv/bin/python kb_eval/make_wide_xlsx.py        # 生成宽表 xlsx

# 2. 清洗 → 归纳 → 索引 → lint
.venv/bin/kb clean   kb_eval/raw   --md-root kb_eval/md
.venv/bin/kb ingest  kb_eval/raw   --md-root kb_eval/md   --wiki-root kb_eval/wiki   # 真实 DeepSeek
.venv/bin/kb index   --wiki-root kb_eval/wiki
.venv/bin/kb lint    --wiki-root kb_eval/wiki

# 3. 起 L1（指向 kb_eval wiki）
WIKI_ROOT=kb_eval/wiki .venv/bin/kb-serve &

# 4. 跑评估（直接调 AgentLoop，捕获 trace）
LLM_API_KEY=$DEEPSEEK_API_KEY .venv/bin/python kb_eval/run_eval.py
# → kb_eval/results.json + 本报告
```

**产物文件**：`kb_eval/cases.json`（用例集）｜`kb_eval/results.json`（机读结果，含每题完整 trace+answer）｜`kb_eval/report.md`（本报告）｜`kb_eval/md/`（7 份清洗 md）｜`kb_eval/wiki/`（11 页归纳 wiki）。

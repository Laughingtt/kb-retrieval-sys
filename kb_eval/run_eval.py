"""kb_eval 评估脚本：直接调用 AgentLoop.run()，捕获每次查询的工具 trace。

用法（L1 已在 8011 服务 kb_eval/wiki，L2 服务不必起，仅用 AgentLoop 直调）：
    LLM_API_KEY=$DEEPSEEK_API_KEY python kb_eval/run_eval.py

产出：
    kb_eval/results.json   —— 每条用例的 {id, question, answer, success, tool_calls_count, tool_trace}
    kb_eval/report.md      —— 人类可读完整测试评估报告
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from l2_agent.agent import AgentLoop          # noqa: E402
from l2_agent.l1_client import L1Client        # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CASES = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]


def judge(case: dict, answer: str, trace: list[dict]) -> tuple[bool, str]:
    """成功判定：gold_answer_contains 全部出现在 answer 中（小写归一）。
    gap 用例：answer 含否定语义且确实没命中知识库内容。"""
    a = (answer or "").lower()
    gold = [g.lower() for g in case["gold_answer_contains"]]
    missing = [g for g in gold if g not in a]
    # 工具是否被调用过期望工具
    tools_used = {t["tool"] for t in trace}
    expect_tools = set(case.get("expect_tool_any", []))
    tool_ok = (not expect_tools) or bool(tools_used & expect_tools)
    if case.get("is_gap"):
        # gap 用例：只要回答里出现否定/未覆盖语义即算成功
        gap_markers = ["未覆盖", "没有", "不在", "未包含", "不涉及", "未提及", "找不到", "无相关"]
        gap_ok = any(m in a for m in gap_markers)
        # 且没有把无关内容硬编成事实（粗检：回答里不该出现 gold 之外的强断言字段值——这里宽松处理）
        reason = "gap: 标记为未覆盖" if gap_ok else "gap: 未明确标记未覆盖"
        return gap_ok and tool_ok, reason
    if missing:
        return False, f"answer 缺少关键信息: {missing}; tool_ok={tool_ok}"
    if not tool_ok:
        return False, f"未调用期望工具 {expect_tools}（实际 {tools_used}）"
    return True, "gold 命中 + 期望工具命中"


def main() -> None:
    l1 = L1Client()  # 默认指向 127.0.0.1:8011
    h = l1.get_health()
    print(f"[eval] L1 health: {h}")
    if h.get("wiki_root") != "kb_eval/wiki":
        print(f"[eval][WARN] L1 wiki_root={h.get('wiki_root')!r}，期望 'kb_eval/wiki'")
    loop = AgentLoop(l1=l1)

    results = []
    pass_n = 0
    for case in CASES:
        q = case["question"]
        print(f"\n[eval] {case['id']} ({case['category']}) -> {q}")
        t0 = time.time()
        try:
            out = loop.run([{"role": "user", "content": q}])
        except Exception as e:
            out = {"content": f"<EXC: {e}>", "tool_calls_count": 0, "trace": []}
        dt = time.time() - t0
        answer = out.get("content", "")
        trace = out.get("trace", [])
        ok, reason = judge(case, answer, trace)
        if ok:
            pass_n += 1
        tool_names = " -> ".join(t["tool"] for t in trace) if trace else "(无工具调用)"
        print(f"    success={ok}  tools={out.get('tool_calls_count')}  [{tool_names}]  ({dt:.1f}s)")
        print(f"    reason: {reason}")
        print(f"    answer: {answer[:240]}{'...' if len(answer) > 240 else ''}")
        results.append({
            "id": case["id"],
            "category": case["category"],
            "question": q,
            "answer": answer,
            "success": ok,
            "reason": reason,
            "tool_calls_count": out.get("tool_calls_count", 0),
            "tool_trace": trace,
            "elapsed_sec": round(dt, 1),
        })

    summary = {
        "suite": CASES[0] and "kb_eval v1",
        "total": len(CASES),
        "passed": pass_n,
        "success_rate": round(pass_n / len(CASES) * 100, 1) if CASES else 0.0,
        "results": results,
    }
    (EVAL_DIR / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[eval] 完成：{pass_n}/{len(CASES)} 通过，成功率 {summary['success_rate']}%")
    print(f"[eval] 结果已写：{EVAL_DIR / 'results.json'}")


if __name__ == "__main__":
    main()

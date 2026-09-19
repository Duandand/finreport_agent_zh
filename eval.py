import csv
import json
import re
from agent import run_agent


REJECT_KEYWORDS = [
    "未收录", "未找到", "无法回答", "无数据", "不提供", "不做投资建议",
    "没有收录", "无法预测", "无法提供", "未在", "没有相关", "请谨慎",
    "抱歉"
]

def is_reject_answer(answer: str) -> bool:
    # 任意一个关键词命中即算拒答
    return any(k in answer for k in REJECT_KEYWORDS)

def check_number_in_answer(value: str, answer: str) -> bool:
    # todo: 空值或 "-" 也算正确吗？目前算正确
    if not value or value == "-":
        return True
    pattern = r"(?<![\d.])" + re.escape(value) + r"(?![\d.])"
    return bool(re.search(pattern, answer))


def evaluate(csv_path="testset.csv"):
    results = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            q = row["question"]
            try:
                out = run_agent(q)
            except Exception as e:
                out = {"answer": f"[CRASH] {e}", "citations": [], "steps": -1}

            answer = out.get("answer", "")
            citations = out.get("citations", [])
            steps = out.get("steps", -1)

            if str(row["should_reject"]).lower() == "true":
                ok = is_reject_answer(answer)
            else:
                val = row.get("expected_value", "")
                ok = check_number_in_answer(val, answer)

            results.append({
                "id": row["id"],
                "category": row["category"],
                "question": q,
                "expected": row.get("expected_value", ""),
                "answer": answer,
                "citations": citations,
                "steps": steps,
                "ok": ok,
            })

    # 汇总
    total = len(results)
    passed = sum(r["ok"] for r in results)
    print(f"\n{'='*40}")
    print(f"总正确率: {passed}/{total} = {passed/total:.1%}")
    print(f"{'='*40}")
    for cat in ["fact", "compute", "compare", "reasoning", "mixed", "reject"]:
        sub = [r for r in results if r["category"] == cat]
        if sub:
            p = sum(r["ok"] for r in sub)
            print(f"  {cat:10s}: {p}/{len(sub)}")

    # 失败清单
    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"\n=== 失败 {len(failed)} 题 ===")
        for r in failed:
            print(f"[{r['category']}] {r['question']}")
            print(f"  期望: {r['expected']}")
            print(f"  实际: {r['answer'][:120]}")
            print(f"  步数: {r['steps']}")
            print()

    # 平均步数
    avg_steps = sum(r["steps"] for r in results if r["steps"] > 0) / max(1, sum(1 for r in results if r["steps"] > 0))
    print(f"平均步数: {avg_steps:.1f}")

    # 保存
    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"结果已保存到 eval_results.json")

    return results


if __name__ == "__main__":
    evaluate()
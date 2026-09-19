import json
from tools import *
from prompt import SYSTEM
import requests, json

BASE_URL = "http://127.0.0.1:11434"

TOOLS = {
    "search_text": search_text,
    "search_table": search_table,
    "query_metric": query_metric,
    "read_table": read_table,
    "compute": compute,
    "verify_citation": verify_citation,
}

def call_llm(messages):
    resp = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": "qwen3.5:9b-q4_K_M",
            "messages": messages,
            "stream": False,
            "think": False
        },
        timeout=200,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def strip_think(text: str) -> str:
    """去掉 <think>...</think> 块"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.replace("<think>", "").replace("</think>", "").strip()


def parse_action(text: str) -> dict:
    """从模型输出里提取 JSON action"""
    text = strip_think(text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"未找到 JSON: {text[:200]}")
    return json.loads(text[start:end + 1])

def run_agent(question, max_step=8):

    history = [{"role": "system", "content": SYSTEM},
               {"role": "user", "content": question}]
    seen_actions = []   # 检测重复工具调用
    search_fail_streak = 0   # search_text 连续失败计数
    for step in range(max_step):
        resp = call_llm(history)
        print(resp)
        print("*"*20)

        try:
            action = parse_action(resp)
        except (ValueError, json.JSONDecodeError) as e:
            # 解析失败，让模型重试，不崩
            history.append({"role": "assistant", "content": resp})
            history.append({
                "role": "user",
                "content": f"你的输出不是合法 JSON，错误：{e}。请严格只输出一个 JSON 对象，不要解释。"
            })
            continue

        history.append({"role": "assistant", "content": resp})

        if action["action"] == "final":
            return {
                "action": "final",
                "answer": action.get("answer", ""),
                "citations": action.get("citations", []),
                "steps": step + 1,
            }

        # 参数缺失兜底
        tool_name = action.get("action", "")
        tool_args = action.get("args", {}) or {}

        # 重复动作检测
        sig = (tool_name, json.dumps(tool_args, sort_keys=True, ensure_ascii=False))
        if sig in seen_actions:
            obs = {
                "error": f"重复调用 {tool_name}，参数相同。请换参数或换工具，或输出 final。"
            }
        else:
            seen_actions.append(sig)
            fn = TOOLS.get(tool_name)
            if not fn:
                obs = {"error": f"unknown tool: {tool_name}",
                       "available_tools": list(TOOLS.keys())}
            else:
                try:
                    obs = fn(**tool_args)
                except TypeError as e:
                    obs = {"error": f"参数错误: {e}",
                           "expected_args": getattr(fn, "__annotations__", {})}
                except Exception as e:
                    obs = {"error": f"工具执行失败: {e}"}
            print(obs)
            print("#"*20)

        # search_text 连续失败计数
        if tool_name == "search_text" and isinstance(obs, dict) and obs.get("error"):
            search_fail_streak += 1
        elif tool_name == "search_text":
            search_fail_streak = 0

        # 关键：每轮都重述原问题，防止目标漂移
        obs_str = json.dumps(obs, ensure_ascii=False)
        reminder = (
            f"工具 {tool_name} 返回：{obs_str}\n\n"
            f"【原始问题提醒】用户问的是：{question}\n"
            f"请基于工具结果继续，或输出 final 回答原始问题。"
            f"不要偏离原始问题。"
        )
        if search_fail_streak >= 2:
            reminder += "\n【警告】search_text 已连续失败两次，禁止再用 search_text，请用 query_metric 或直接 final。"

        history.append({
            "role": "tool", # 用tool回传
            "content": reminder,
            "name": tool_name,
        })

    return {
        "action": "final",
        "answer": "步数超限，未能完成",
        "citations": [],
        "steps": max_step,
    }

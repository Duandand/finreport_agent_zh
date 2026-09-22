import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import re
import json
import pdfplumber
import pandas as pd
import torch
import numpy as np
from FlagEmbedding import BGEM3FlagModel

import faiss


MODEL_PATH = os.getenv("BGE_M3_PATH", "BAAI/bge-m3")
_model = BGEM3FlagModel(MODEL_PATH, use_fp16=True)
_index = faiss.read_index("index/faiss.index")
_chunks = [json.loads(l) for l in open("data/chunks.jsonl")]
_metrics = pd.read_csv("data/metrics.csv")
_metrics["period"] = _metrics["period"].astype(str)

# 短词不要做子串替换（「收入」会误伤「营业收入」）
_ALIAS_SUBSTRING_SKIP = {"收入"}

METRIC_ALIAS = {
    "营收": "营业收入",
    "收入": "营业收入",
    "净利润": "归母净利润",
    "归母净利": "归母净利润",
    "经营现金流": "经营活动现金流净额",
    "现金流": "经营活动现金流净额",
    "经营活动现金流": "经营活动现金流净额",
    "经营活动产生的现金流量净额": "经营活动现金流净额",
    "经营活动产生的现金流净额": "经营活动现金流净额",
    "经营性现金流": "经营活动现金流净额",
    "归母权益": "归母所有者权益",
    "所有者权益": "归母所有者权益",
    "总资产": "资产总计",
    "总负债": "负债合计",
    "负债率": "资产负债率",
    "净利率": "净利率",
    "毛利率": "毛利率",
    "营收同比增速": "营业收入同比",
    "营收同比": "营业收入同比",
    "营业收入同比增速": "营业收入同比",
    "净利润同比": "归母净利润同比",
    "净利润同比增长": "归母净利润同比",
    "归母净利润同比增长": "归母净利润同比",
    "经营现金流同比": "经营现金流同比",
    "经营现金流同比下降": "经营现金流同比",
    "经营活动现金流净额同比": "经营现金流同比",
}

_YOY_CANONICAL = {
    "经营活动现金流净额同比": "经营现金流同比",
    "经营活动产生的现金流量净额同比": "经营现金流同比",
}


_CANONICAL_METRICS = set(METRIC_ALIAS.values()) | set(_YOY_CANONICAL.values())


def _canonical_metric(metric: str) -> str:
    m = str(metric).strip()
    # 输入本身就是 canonical 名时，短路返回，避免子串替换把已存在的前缀再拼一次
    if m in _CANONICAL_METRICS:
        return m
    if m in METRIC_ALIAS:
        return METRIC_ALIAS[m]
    for alias, canonical in sorted(METRIC_ALIAS.items(), key=lambda x: -len(x[0])):
        if alias in _ALIAS_SUBSTRING_SKIP:
            continue
        if alias in m:
            m = m.replace(alias, canonical)
            break
    m = re.sub(r"同比(增长|下降|增速|增长率|增幅|降幅)$", "同比", m)
    return _YOY_CANONICAL.get(m, m)


def search_text(query, top_k=3):
    vec = _model.encode(
        [query], return_dense=True, return_sparse=False, return_colbert_vecs=False,
    )["dense_vecs"]
    qv = np.asarray(vec, dtype="float32")
    faiss.normalize_L2(qv)
    scores, idx = _index.search(qv, top_k)
    return [
        {"page": _chunks[i]["page"],
         "text": _chunks[i]["text"][:300],   # 截断，减少干扰
         "score": round(float(s), 3)}
        for s, i in zip(scores[0], idx[0])
    ]


def search_table(query, top_k=5):
    q = _canonical_metric(query)

    hits = []
    for _, row in _metrics.iterrows():
        score = 0
        if row["metric"] in q:
            score += 2
        if str(row["period"]) in q or q.replace("年", "") in str(row["period"]):
            score += 1
        if row["company"] in q:
            score += 1
        if score > 0:
            d = row.to_dict()
            d["_score"] = score
            hits.append(d)

    hits.sort(key=lambda x: -x["_score"])
    return hits[:top_k]


def read_table(table_id, rows=None, cols=None):
    if not table_id or table_id == "null":
        return {"error": "table_id 不能为空。请先用 search_text 找到具体表格，再传 table_id。"}
    try:
        df = pd.read_csv(f"data/tables/{table_id}.csv")
    except FileNotFoundError:
        return {"error": f"表格 {table_id} 不存在"}
    if rows: df = df.iloc[rows]
    if cols: df = df[cols]
    return df.to_dict(orient="records")


def _normalize_period(p):
    """统一成 metrics.csv 周期：2026H1 / 2025H1；全年/年报不成 H2。"""
    p = str(p).strip()
    m = re.match(r"(\d{4}).*?(H1|h1|半年|中期)", p)
    if m:
        return f"{m.group(1)}H1"
    m = re.match(r"(\d{4}).*?(H2|h2|下半年)", p)
    if m:
        return f"{m.group(1)}H2"
    m = re.match(r"(\d{4})(H[12])$", p, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}"
    m = re.match(r"(\d{4}).*?(全年|年报|年度|FY|fy)", p)
    if m:
        return f"{m.group(1)}FY"
    return p


def query_metric(company, metric, period):
    metric = _canonical_metric(metric)
    period = _normalize_period(period)

    df = _metrics[
        (_metrics.company == company) &
        (_metrics.metric == metric) &
        (_metrics.period == period)
    ]
    if df.empty:
        return {
            "error": "未找到该指标",
            "company": company, "metric": metric, "period": period,
            "available_metrics": _metrics[
                (_metrics.company == company) & (_metrics.period == period)
            ]["metric"].tolist(),
        }
    return df.to_dict(orient="records")



def compute(formula, variables):
    try:
        if formula == "yoy":
            cur, prev = variables["cur"], variables["prev"]
            if prev == 0:
                return {"error": "分母为 0"}
            return {
                "formula": "yoy",
                "value": round((cur - prev) / abs(prev) * 100, 2),
                "unit": "%",
                "detail": f"({cur} - {prev}) / |{prev}|",
            }

        if formula == "cagr":
            start, end, n = variables["start"], variables["end"], variables["n"]
            if start <= 0 or n <= 0:
                return {"error": "参数非法"}
            return {
                "formula": "cagr",
                "value": round(((end / start) ** (1 / n) - 1) * 100, 2),
                "unit": "%",
                "detail": f"({end}/{start})^(1/{n}) - 1",
            }

        if formula == "ratio":
            a, b = variables["a"], variables["b"]
            if b == 0:
                return {"error": "分母为 0"}
            return {
                "formula": "ratio",
                "value": round(a / b * 100, 2),
                "unit": "%",
                "detail": f"{a} / {b}",
            }

        if formula == "diff":
            a, b = variables["a"], variables["b"]
            return {
                "formula": "diff",
                "value": round(a - b, 2),
                "unit": variables.get("unit", ""),
                "detail": f"{a} - {b}",
            }

        return {"error": f"unknown formula: {formula}"}

    except KeyError as e:
        return {"error": f"缺少参数: {e}"}


def verify_citation(claim, evidence):
    # 检查 claim 里的数字是否出现在 evidence 中
    # 只提取带小数或完整数字，避免 "23" 匹配 "23.11"
    nums = re.findall(r"\d+\.\d+|\d+", claim)
    ev = " ".join(str(e) for e in evidence)

    missing = []
    for n in nums:
        # 用正则边界匹配，避免子串误命中
        pattern = r"(?<![\d.])" + re.escape(n) + r"(?![\d.])"
        if not re.search(pattern, ev):
            missing.append(n)

    return {
        "verified": len(missing) == 0,
        "missing_numbers": missing,
        "total_checked": len(nums),
    }
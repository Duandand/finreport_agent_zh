# FinReport Agent (zh)

> 基于 ReAct + RAG 的轻量级中文财报问答智能体 —— 本地部署，支持工具调用、指标查询、数值计算与引用溯源。

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Model](https://img.shields.io/badge/LLM-Qwen3.5--9B-orange)](https://ollama.com/)
[![Embedding](https://img.shields.io/badge/Embedding-bge--m3-yellow)](https://huggingface.co/BAAI/bge-m3)

---

## 项目简介

**FinReport Agent** 是一个面向中文上市公司财报的智能问答原型，把 LLM 从"文本生成器"升级为"会调工具的财报分析师"。

它解决单轮 RAG 在财报场景的三个痛点：

| 痛点 | 单轮 RAG | FinReport Agent |
|---|---|---|
| 数值幻觉 | LLM 凭记忆编数字 | 所有数字强制走指标库 |
| 计算缺失 | 无法算同比 / 差值 / 占比 | 内置 `compute` 工具 |
| 引用造假 | 引用页码靠生成 | 引用来自工具真实返回 |

核心设计理念：**能查表就不生成，能预计算就不心算。**

---

## 核心特性

### 1. ReAct 多步推理循环
Agent 通过 `Observe → Think → Act → Observe → ... → Final` 循环自主决策，不依赖固定 Workflow。

```
用户问题
  ↓
问题分类（原因类 / 数值类 / 混合类）
  ↓
选择工具 → 执行 → 观察结果
  ↓
信息足够？ ──No──→ 换工具 / 重试
  │
  Yes
  ↓
最终答案 + 引用
```

### 2. 含6类工具，覆盖财报常见问答场景

| 工具 | 用途 |
|---|---|
| `query_metric` | 精确查询结构化指标（营收、净利润、资产负债率等） |
| `search_text` | 向量检索财报原文，用于原因、风险、战略类问题 |
| `search_table` | 关键词匹配财务表格 |
| `read_table` | 读取指定表格的行列 |
| `compute` | 白名单公式计算（yoy / cagr / ratio / diff） |
| `verify_citation` | 校验结论中的数字是否被证据支持 |

### 3. 结构化指标库，从源头杜绝幻觉
所有数值型问题走 `metrics.csv`，LLM 不参与任何算术。查不到就诚实拒答，而不是硬编一个数字。

```csv
company,period,metric,value,unit,source_table,page,note
寒武纪,2026H1,营业收入,59.96,亿元,合并利润表,62,合并报表
寒武纪,2026H1,归母净利润,23.11,亿元,合并利润表,63,合并报表
寒武纪,2026H1,资产负债率,25.48,%,计算,58,负债合计/资产总计
```

### 4. 强制引用溯源
每个结论必须带 `page` 或 `table_id`，格式严格校验：

```json
{"page": 62, "table_id": null}
```

### 5. 本地轻量部署
- **LLM**：Qwen3.5-9B (Q4_K_M)，通过 Ollama 在 MacBook Pro 24GB 上流畅运行（约 35 tokens/s）
- **Embedding**：bge-m3 + FAISS 本地向量检索
- **零 API 成本**，数据不出本地

### 6. 问题分类优先于工具选择
避免"一看到指标名就归类为数值题"的常见错误。规则锋利：

- 出现「为什么 / 原因 / 风险 / 看法」→ 原因类 → `search_text`
- 纯数值问题 → 数值类 → `query_metric`
- 两者都有 → 混合类 → `query_metric` 取数 → `search_text` 找原因

---


## 快速开始

### 环境要求

- macOS / Linux，内存 ≥ 16GB（推荐 24GB）
- Python 3.10+
- [Ollama](https://ollama.com/) 已安装

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 启动本地 LLM

```bash
ollama pull qwen3.5:9b-q4_K_M
ollama serve
```

### 3. 准备数据

以寒武纪2026年中报为例，下载链接`https://static.cninfo.com.cn/finalpage/2026-08-08/1225464969.PDF`，下载完成后将pdf放入`data/pdfs`目录下：

```bash
# 将财报 PDF 放入 data/pdfs/，更改prepare.py中文件目录
python prepare.py     # 解析 PDF → chunks.jsonl + 表格 + FAISS 索引

# 手动整理 metrics.csv（核心指标库）
```


### 4. 运行 Agent

默认使用 HuggingFace 上的 `BAAI/bge-m3`。
如需指定本地模型路径，设置环境变量：

export BGE_M3_PATH=/your/path/to/bge-m3

```bash
python main.py
```

```
Q: 寒武纪2026H1营业收入是多少？
A: 寒武纪 2026H1 营业收入为 59.96 亿元，来源：合并利润表第 62 页。
引用: [{'page': 62, 'table_id': None}]

Q: 寒武纪2026H1经营现金流为什么比2025H1下降？
A: 主要系本期对外采购及支付税金较上年同期增加所致。
引用: [{'page': 22, 'table_id': None}]
```

### 5. 运行评测

```bash
python eval.py
```

---

## 项目结构

```
finreport_agent_zh/
├── data/
│   ├── pdfs/              # 原始财报 PDF
│   ├── chunks.jsonl       # 文本切片
│   ├── tables/            # 抽取的表格 CSV
│   └── metrics.csv        # 结构化指标库（核心）
├── index/
│   └── faiss.index        # 向量索引
├── prepare.py             # 数据预处理
├── tools.py               # 工具层
├── prompt.py              # System prompt
├── agent.py               # ReAct 主循环
├── eval.py                # 评测脚本
├── testset.csv            # 评测集
└── main.py                # 入口
```

---

## 技术栈

| 组件 | 选型 | 理由 |
|---|---|---|
| LLM | Qwen3.5-9B Q4_K_M | 中文强、支持 function calling、24GB 内存可跑 |
| 推理框架 | Ollama | 开箱即用，固定端口 11434 |
| Embedding | bge-m3 | 中英双语，长文本友好 |
| 向量库 | FAISS (IndexFlatIP) | 轻量，几千 chunk 无需近似索引 |
| PDF 解析 | pdfplumber | 中文 PDF |
| 编排 | 手写 ReAct 循环 | 理解原理，不依赖框架 |

---

## Roadmap

- [x] ReAct 主循环 + 6 类工具
- [x] 指标库 + 强制引用
- [x] 评测集
- [ ] 多公司 / 多期支持
- [ ] 扫描版财报 OCR 接入
- [ ] LangGraph 状态机重构
- [ ] 成功轨迹 SFT
- [ ] Agent RL（GRPO）

---

## 引用与致谢

- [bge-m3](https://huggingface.co/BAAI/bge-m3) - BAAI 多语言嵌入模型
- [Qwen](https://github.com/QwenLM/Qwen) - 通义千问开源模型
- [Ollama](https://ollama.com/) - 本地 LLM 推理框架
- [FAISS](https://github.com/facebookresearch/faiss) - Facebook 向量检索库

---

## License

MIT License

---

## 免责声明

本项目仅用于技术学习与研究，所有回答基于公开财报数据，**不构成任何投资建议**。
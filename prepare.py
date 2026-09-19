import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

import json
import pdfplumber
import pandas as pd
import torch
import numpy as np
from FlagEmbedding import BGEM3FlagModel

import faiss


CHUNK_SIZE = 512
CHUNK_OVERLAP = 100
os.makedirs("data/tables", exist_ok=True)
os.makedirs("index", exist_ok=True)

def parse_pdf(path):
    chunks, tables = [], []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            for i in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP):
                piece = text[i:i + CHUNK_SIZE]
                if not piece.strip():
                    continue
                chunks.append({
                    "id": f"p{pno}_c{i}",
                    "page": pno,
                    "text": piece,
                })
            for tno, table in enumerate(page.extract_tables()):
                if not table or len(table) < 2:
                    continue
                header = [str(h).replace("\n", " ").strip() if h else f"col{j}"
                          for j, h in enumerate(table[0])]
                df = pd.DataFrame(table[1:], columns=header)
                tid = f"p{pno}_t{tno}"
                df.to_csv(f"data/tables/{tid}.csv", index=False)
                tables.append({"id": tid, "page": pno, "title": header})

    return chunks, tables

def save_chunks(chunks, path="data/chunks.jsonl"):
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"[OK] 写入 {len(chunks)} 条 chunk -> {path}")


def build_index(chunks, model_path,
                batch_size=8, max_length=512):
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = BGEM3FlagModel(model_path, use_fp16=True, device=device)
    print("[OK] 模型加载完成，开始编码文本...")

    index = None
    total = 0
    texts = [c["text"] for c in chunks]

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vecs = model.encode(
            batch,
            batch_size=batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )["dense_vecs"]

        vecs = np.asarray(vecs, dtype="float32")
        faiss.normalize_L2(vecs)

        if index is None:
            index = faiss.IndexFlatIP(vecs.shape[1])

        index.add(vecs)
        total += len(batch)
        print(f"[{total}/{len(texts)}] 已编码")

    faiss.write_index(index, "index/faiss.index")
    print(f"[OK] 索引写入 index/faiss.index，共 {index.ntotal} 条")
    return model

if __name__ == "__main__":
    MODEL_PATH = '/project/model_downloads/bge-m3'
    chunks, tables = parse_pdf("./data/pdfs/寒武纪2026年半年度报告caa90e58c8aa6bcd86952cfa102955a7.pdf")
    save_chunks(chunks)
    print("[OK] 文本抽出完成，chunk数:", len(chunks), "表格数:", len(tables))
    build_index(chunks, model_path=MODEL_PATH)


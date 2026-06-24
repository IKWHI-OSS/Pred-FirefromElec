#!/usr/bin/env python3
"""
저장된 RAG 색인표(index.faiss + chunk_case_idx.npy + case_ids.json)를 직접 검색.

build_rag_index.py 가 만든 산출물을 그대로 읽어, 평가셋 질의를 임베딩→검색→케이스 환원한다.
검색결과는 eval_recall.py 가 채점할 수 있는 형식(qid, retrieved=[caseid...])으로 저장.

★ 맥 세그폴트 회피(메모리 교훈): torch(임베딩)와 faiss(검색)를 한 프로세스에 같이 두면
  각자 libomp를 적재해 충돌→세그폴트. 그래서 두 단계를 분리한다.
    1) embed  : sentence-transformers(torch)만 import → 질의 임베딩을 .npy로 저장(faiss 안 건드림)
    2) search : faiss만 import → .npy + 색인표 읽어 검색(torch 안 건드림)
  빌더와 동일 규칙: 같은 모델, normalize=True(코사인), bge-m3는 접두어 없음. 맥은 1스레드.

사용(두 번 호출):
  python3 search_preview.py embed  --eval eval.jsonl --out-emb /tmp/q.npy --device cpu
  python3 search_preview.py search --index-dir /tmp/idx_smoke --emb /tmp/q.npy --out results.jsonl
"""
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import sys, json, argparse
import numpy as np


def e5_prefix(model_name, kind):
    if "e5" in model_name.lower():
        return "query: " if kind == "query" else "passage: "
    return ""


def cmd_embed(a):
    # torch만 — faiss는 절대 import 안 함(세그폴트 회피).
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(1)
    qs = [json.loads(l) for l in open(a.eval, encoding="utf-8") if l.strip()]
    m = SentenceTransformer(a.model, device=a.device)
    m.max_seq_length = 512
    qpref = e5_prefix(a.model, "query")
    texts = [qpref + q["query"] for q in qs]
    emb = np.asarray(
        m.encode(texts, batch_size=a.batch, normalize_embeddings=True, show_progress_bar=True),
        dtype="float32",
    )
    np.save(a.out_emb, emb)
    json.dump([q["qid"] for q in qs], open(a.out_emb + ".qids.json", "w"))
    print(f"[embed] 질의 {len(qs)}개 임베딩 -> {a.out_emb}", flush=True)


def cmd_search(a):
    # faiss만 — torch/sentence-transformers는 절대 import 안 함.
    import faiss
    if sys.platform == "darwin":
        faiss.omp_set_num_threads(1)
    emb = np.load(a.emb)
    qids = json.load(open(a.emb + ".qids.json"))
    index = faiss.read_index(os.path.join(a.index_dir, "index.faiss"))
    if a.nprobe > 0:
        # OPQ 등은 IndexPreTransform로 감싸 nprobe가 안쪽 IVF에 있음 → extract로 꺼내 설정.
        try:
            faiss.extract_index_ivf(index).nprobe = a.nprobe
        except Exception:
            index.nprobe = a.nprobe
    chunk_case = np.load(os.path.join(a.index_dir, "chunk_case_idx.npy"))
    case_ids = json.load(open(os.path.join(a.index_dir, "case_ids.json")))
    print(f"[index] 청크 {index.ntotal:,} / 케이스 {len(case_ids):,} / nprobe={getattr(index, 'nprobe', '-')}", flush=True)

    D, I = index.search(emb, a.topk_chunks)
    with open(a.out, "w", encoding="utf-8") as fo:
        for qi, qid in enumerate(qids):
            seen, seset = [], set()
            for ci in I[qi]:
                if ci < 0:
                    continue
                cid = case_ids[int(chunk_case[ci])]
                if cid not in seset:
                    seset.add(cid)
                    seen.append(cid)
                if len(seen) >= a.topk_cases:
                    break
            fo.write(json.dumps({"qid": qid, "retrieved": seen}, ensure_ascii=False) + "\n")
    print(f"[search] 질의 {len(qids)}개 검색 완료 -> {a.out}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("embed")
    pe.add_argument("--eval", required=True)
    pe.add_argument("--out-emb", required=True)
    pe.add_argument("--model", default="BAAI/bge-m3")
    pe.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"])
    pe.add_argument("--batch", type=int, default=32)

    ps = sub.add_parser("search")
    ps.add_argument("--index-dir", required=True)
    ps.add_argument("--emb", required=True)
    ps.add_argument("--out", required=True)
    ps.add_argument("--topk-chunks", type=int, default=300)
    ps.add_argument("--topk-cases", type=int, default=10)
    ps.add_argument("--nprobe", type=int, default=0, help=">0이면 검색 시점 nprobe로 덮어씀")

    a = ap.parse_args()
    {"embed": cmd_embed, "search": cmd_search}[a.cmd](a)


if __name__ == "__main__":
    main()

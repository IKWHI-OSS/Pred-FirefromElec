#!/usr/bin/env python3
"""
RAG 설정 행렬 평가 — 청킹 × 인덱스 비교 → recall@k 표 (Pred-FirefromElec)

한 번에: 청크 생성 → BGE-m3 임베딩(1회 로드) → FAISS 색인(flat/IVF-PQ) → 평가질의 검색
→ recall@1/3/5/10·MRR 비교표. 이 표로 청킹 입도·PQ 강도를 '측정으로' 확정한다.

입력:
  rag_units.jsonl          (build_rag_units.py 산출: {id, text, ...})
  eval_set_auto.jsonl      (build_eval_set.py 산출: {qid, query, gold_id, kind, ...})
  [eval_curated.jsonl]     (선택: 손으로 채운 패러프레이즈셋 — 같이 채점)

미니테스트 원리: 전체 247K를 임베딩하지 않고, 평가셋의 정답 케이스 ∪ 무작위 풀(--pool)만
색인해 빠르게 비교한다(정답이 풀에 항상 포함되므로 recall 측정 유효).

사용(Cursor):
  pip install sentence-transformers faiss-cpu --break-system-packages
  python3 eval_matrix.py rag_units.jsonl eval_set_auto.jsonl --pool 8000 \
      --chunkings case tot win --indexes flat ivfpq
  # 배선만 빠르게 확인: --offline (모델·네트워크 없이 가짜 임베더)
"""
import os
# macOS OpenMP 중복 libomp 충돌 → 임베딩 중 SIGSEGV 방지(반드시 torch/numpy import 전에).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import sys, json, argparse, random, hashlib, math
import numpy as np

K_LIST = [1, 3, 5, 10]

# ---------- 데이터 ----------
def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: out.append(json.loads(line))
    return out

def make_chunks(cases, mode):
    """cases: [{id,text}] → [(chunk_text, case_id)]. mode: case|tot|win"""
    chunks = []
    for c in cases:
        cid, text = c["id"], c.get("text", "")
        if mode == "case":
            chunks.append((text, cid))
        elif mode == "tot":  # 줄(=질문/추론노드) 단위
            for ln in text.split("\n"):
                ln = ln.strip()
                if len(ln) >= 10: chunks.append((ln, cid))
        elif mode == "win":  # 문자창 ~1000자(≈512토큰 근사), 오버랩 128
            W, OV = 1000, 128
            i = 0
            while i < len(text):
                seg = text[i:i+W].strip()
                if seg: chunks.append((seg, cid))
                i += (W - OV)
        else:
            raise ValueError(mode)
    return chunks

# ---------- 임베더 ----------
class FakeEmb:
    """오프라인 배선검증용 결정적 해시 임베더(의미 없음, 파이프라인 동작만 확인)."""
    dim = 256
    def encode(self, texts, **kw):
        V = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            h = hashlib.md5(t.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(h[:8], "little"))
            V[i] = rng.standard_normal(self.dim).astype("float32")
        V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
        return V

def load_embedder(offline, model_name, device="cpu"):
    if offline:
        print("[offline] FakeEmb 사용(배선검증 전용)"); return FakeEmb(), FakeEmb.dim
    from sentence_transformers import SentenceTransformer
    # 과거 bge-m3+MPS는 무트레이스백 강제종료(세그폴트)라 CPU 고정이 기본이었으나,
    # torch 2.10.0에서 MPS가 정상 동작(검증) → --device mps로 가속 가능(CPU 62/s → MPS ~155/s).
    m = SentenceTransformer(model_name, device=device)  # 기본 cpu(안정), 명시 시 mps
    m.max_seq_length = 512  # 긴 case 텍스트를 512토큰으로 캡(검색단위엔 충분, 속도/메모리)
    d = m.get_sentence_embedding_dimension()
    print(f"[model] {model_name} dim={d}")
    return m, d

def embed(model, texts, prefix="", bs=32):
    # e5 계열은 query:/passage: 접두어가 필수 — 없으면 검색이 거의 무작위로 붕괴.
    if prefix:
        texts = [prefix + t for t in texts]
    return np.asarray(model.encode(texts, batch_size=bs, normalize_embeddings=True,
                                   show_progress_bar=True), dtype="float32")


def e5_prefixes(model_name):
    """모델별 입력 접두어. e5=query:/passage: 필수, bge-m3 등은 접두어 없음."""
    is_e5 = "e5" in model_name.lower()
    return ("query: ", "passage: ") if is_e5 else ("", "")

# ---------- 인덱스 ----------
def build_search(emb, kind, dim):
    """반환: search(qvecs, k) -> (I) 인덱스 행렬. faiss 있으면 사용, 없으면 numpy flat."""
    try:
        import faiss
        faiss.omp_set_num_threads(1)  # torch↔faiss OpenMP 데드락 회피(macOS) — 인덱스 build 멈춤 방지
        if kind == "flat":
            idx = faiss.IndexFlatIP(dim)
        elif kind == "ivfpq":
            n = emb.shape[0]
            nlist = max(8, min(4096, int(math.sqrt(n))))
            m = 8 if dim % 8 == 0 else 4          # PQ 서브양자화 수
            while dim % m != 0: m -= 1
            quant = faiss.IndexFlatIP(dim)
            idx = faiss.IndexIVFPQ(quant, dim, nlist, m, 8)
            idx.train(emb); idx.nprobe = min(16, nlist)
        else:
            raise ValueError(kind)
        idx.add(emb)
        return lambda q, k: idx.search(q, k)[1], "faiss/" + kind
    except ImportError:
        if kind == "ivfpq":
            sys.stderr.write("[warn] faiss 없음 → ivfpq를 numpy flat으로 대체(오프라인)\n")
        def search(q, k):
            sims = q @ emb.T
            return np.argsort(-sims, axis=1)[:, :k]
        return search, "numpy/flat"

# ---------- 채점 ----------
def recall_rows(I, chunk_cids, queries, name):
    by = {}; agg = {k: 0 for k in K_LIST}; mrr = 0.0; n = len(queries)
    for row, q in zip(I, queries):
        # 청크 인덱스 → 케이스 id, 순서 보존 dedup
        seen = [];
        for ci in row:
            cid = chunk_cids[ci]
            if cid not in seen: seen.append(cid)
        gold = q["gold_id"]
        rank = next((i+1 for i, c in enumerate(seen) if c == gold), None)
        kind = q.get("kind", "?"); d = by.setdefault(kind, {"n":0, **{k:0 for k in K_LIST}})
        d["n"] += 1
        for k in K_LIST:
            hit = 1 if (rank and rank <= k) else 0
            agg[k] += hit; d[k] += hit
        if rank: mrr += 1.0/rank
    res = {"name": name, "n": n, "mrr": mrr/n if n else 0, **{f"r{k}": agg[k]/n if n else 0 for k in K_LIST}, "by": by}
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units"); ap.add_argument("eval_set")
    ap.add_argument("--curated", default=None)
    ap.add_argument("--pool", type=int, default=8000)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--chunkings", nargs="+", default=["case", "tot", "win"])
    ap.add_argument("--indexes", nargs="+", default=["flat", "ivfpq"])
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps", "cuda"])  # mps=맥 GPU 가속(torch2.10+)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(); random.seed(a.seed)

    units = load_jsonl(a.units)
    by_id = {u["id"]: u for u in units}
    queries = load_jsonl(a.eval_set)
    if a.curated and os.path.exists(a.curated):
        queries += [q for q in load_jsonl(a.curated) if not q["gold_id"].startswith("<")]
    gold_ids = {q["gold_id"] for q in queries}

    # 풀 = 정답 케이스 ∪ 무작위 표본
    pool_ids = set(gold_ids)
    rest = [u["id"] for u in units if u["id"] not in pool_ids]
    random.shuffle(rest)
    pool_ids.update(rest[:max(0, a.pool - len(pool_ids))])
    pool = [by_id[i] for i in pool_ids if i in by_id]
    print(f"유닛 {len(units):,} | 평가질의 {len(queries)} | 풀 {len(pool):,} (정답 {len(gold_ids)} 포함)")

    model, dim = load_embedder(a.offline, a.model, a.device)
    print(f"[device] {a.device}")
    qpref, ppref = e5_prefixes(a.model)
    print(f"[prefix] {'e5 감지 → query:/passage: 부착' if qpref else '접두어 없음(bge-m3 등)'}")
    qtexts = [q["query"] for q in queries]
    qvec = embed(model, qtexts, qpref)

    rows = []
    for ck in a.chunkings:
        chunks = make_chunks(pool, ck)
        ctexts = [c[0] for c in chunks]; ccids = [c[1] for c in chunks]
        print(f"\n[chunking={ck}] 청크 {len(chunks):,} → 임베딩…")
        cemb = embed(model, ctexts, ppref)
        for ix in a.indexes:
            search, label = build_search(cemb, ix, cemb.shape[1])
            I = search(qvec, a.topk)
            rows.append(recall_rows(I, ccids, queries, f"{ck}/{ix}/{label.split('/')[0]}"))

    # 비교표
    print("\n" + "=" * 72)
    print(f"{'config':<24}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'R@10':>7}{'MRR':>7}")
    print("-" * 72)
    for r in rows:
        print(f"{r['name']:<24}{r['r1']:>7.3f}{r['r3']:>7.3f}{r['r5']:>7.3f}{r['r10']:>7.3f}{r['mrr']:>7.3f}")
    print("-" * 72)
    print("kind별(auto=상한, curated=실제 의미검색):")
    for r in rows:
        for kind, d in r["by"].items():
            if d["n"]:
                print(f"  {r['name']:<22} {kind:<18} n={d['n']:<4} " +
                      " ".join(f"R@{k}={d[k]/d['n']:.2f}" for k in K_LIST))

if __name__ == "__main__":
    main()

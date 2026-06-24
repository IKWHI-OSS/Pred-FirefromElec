#!/usr/bin/env python3
"""
전량 RAG 인덱스 빌더 — rag_units.jsonl 전량 → tot 청킹 → BGE-m3 임베딩 → IVF-PQ → 저장/업로드.

핵심 제약: tot(줄단위) 청킹은 케이스당 ~135줄 → 24.7만 케이스면 약 3,470만 청크.
1,024차원 float32로 전부 담으면 ~142GB라 RAM 불가. 그래서 '스트리밍 2-pass'로 만든다.

  pass1: 무작위 표본 청크만 임베딩 → IVF-PQ 학습(코드북 결정). 표본만이라 가볍다.
  pass2: 전량 청크를 배치로 임베딩 → 곧장 index.add(PQ 코드만 적재) → 배치 폐기.
         동시에 chunk_i -> case_id 매핑을 add 순서대로 기록(검색결과 -> 케이스 환원용).

산출(--out 디렉토리):
  index.faiss          IVF-PQ 인덱스(PQ 코드만, 압축본)
  chunk_case_idx.npy   int32[N_chunks]: 청크 i가 속한 케이스의 정수 인덱스
  case_ids.json        정수인덱스 -> case_id 문자열 (유일 케이스 24.7만개)
  case_meta.jsonl      case_id별 메타(do/query_*/fuel_type) — 검색결과 표시용
  manifest.json        빌드 파라미터·건수·체크섬

사용:
  # 로컬 스모크(맥, MPS, 앞 200케이스만):
  python3 build_rag_index.py rag_units.jsonl --out idx_smoke --device mps --limit 200
  # 클라우드 전량(GPU VM):
  python3 build_rag_index.py rag_units.jsonl --out idx_full --device cuda \
      --model BAAI/bge-m3 --chunking tot --nlist 8192 --pq-m 32 --gcs-out gs://constgx_electrofire/rag_index/
"""
import os
# macOS OpenMP 중복 libomp 충돌 방지 — torch/faiss import 전에 반드시.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import sys, json, time, math, argparse, random, subprocess, hashlib
import numpy as np


# ---------- 청킹 ----------
def tot_lines(text):
    """tot: 줄(=질문/추론 노드) 단위. 10자 미만은 잡음으로 버림. eval_matrix.py와 동일 규칙."""
    for ln in text.split("\n"):
        ln = ln.strip()
        if len(ln) >= 10:
            yield ln


def iter_chunks(path, chunking, limit=None):
    """rag_units.jsonl을 스트리밍하며 (chunk_text, case_id) 생성. 파일 전체를 메모리에 안 올린다."""
    n_units = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            u = json.loads(line)
            cid, text = u["id"], u.get("text", "")
            if chunking == "tot":
                for ln in tot_lines(text):
                    yield ln, cid
            elif chunking == "case":
                if text.strip():
                    yield text, cid
            elif chunking == "casehdr":
                # 케이스당 글 하나 = 메타 헤더(연료/주제/유형/목적) + 질문 첫 줄.
                # 메타를 본문에 넣어 케이스가 구별되게 함(검색 정확도 ↑). 조각이 케이스 수로 급감.
                hdr = (f"연료유형: {u.get('fuel_type','')} | 주제: {u.get('query_subject','')} | "
                       f"질문유형: {u.get('query_type','')} | 목적: {u.get('query_purpose','')}")
                first = text.split("\n", 1)[0].strip()
                yield f"{hdr}\n{first}", cid
            else:
                raise ValueError(chunking)
            n_units += 1
            if limit and n_units >= limit:
                return


def iter_case_meta(path, limit=None):
    """case_id별 메타데이터(임베딩 대상 아님 — 검색결과 표시용)."""
    META = ("do", "query_purpose", "query_subject", "query_type", "fuel_type", "size")
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            u = json.loads(line)
            yield u["id"], {k: u.get(k) for k in META}
            n += 1
            if limit and n >= limit:
                return


# ---------- 임베더 ----------
def load_embedder(model_name, device):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_name, device=device)
    m.max_seq_length = 512  # 검색 단위엔 512토큰이면 충분(속도/메모리)
    if device == "cuda":
        m = m.half()  # fp16: L4 텐서코어 활용(속도↑). 임베딩 품질 영향 미미. cpu/mps는 fp32 유지(안정).
    d = m.get_sentence_embedding_dimension()
    print(f"[model] {model_name} dim={d} device={device} fp16={device == 'cuda'}", flush=True)
    return m, d


def e5_prefix(model_name, kind):
    """e5 계열만 query:/passage: 접두어 필수. bge-m3는 접두어 없음."""
    if "e5" in model_name.lower():
        return "query: " if kind == "query" else "passage: "
    return ""


def encode(model, texts, prefix, bs):
    if prefix:
        texts = [prefix + t for t in texts]
    return np.asarray(
        model.encode(texts, batch_size=bs, normalize_embeddings=True, show_progress_bar=False),
        dtype="float32",
    )


# ---------- 표본 추출(pass1, IVF-PQ 학습용) ----------
def reservoir_sample(path, chunking, k, limit, seed):
    """전량을 한 번 스트리밍하며 청크 텍스트 k개를 균등 무작위 추출(저수지 표집)."""
    rng = random.Random(seed)
    buf = []
    seen = 0
    for txt, _cid in iter_chunks(path, chunking, limit):
        seen += 1
        if len(buf) < k:
            buf.append(txt)
        else:
            j = rng.randint(0, seen - 1)
            if j < k:
                buf[j] = txt
    print(f"[pass1] 전량 청크 {seen:,} 중 학습표본 {len(buf):,} 추출", flush=True)
    return buf, seen


# ---------- 인덱스 ----------
def build_ivfpq(train_vecs, dim, nlist, pq_m, nbits, nprobe, faiss_threads):
    import faiss
    # macOS: torch와 faiss가 각자 libomp를 적재 → 멀티스레드면 세그폴트(eval_matrix.py 교훈).
    # darwin은 1스레드 고정(안전), 리눅스/CUDA VM은 전체 CPU(빠름).
    nt = faiss_threads if faiss_threads > 0 else (1 if sys.platform == "darwin" else (os.cpu_count() or 1))
    faiss.omp_set_num_threads(nt)
    print(f"[faiss] omp_threads={nt}", flush=True)
    quant = faiss.IndexFlatIP(dim)  # 코사인(정규화된 내적) 기준
    index = faiss.IndexIVFPQ(quant, dim, nlist, pq_m, nbits, faiss.METRIC_INNER_PRODUCT)
    t = time.time()
    index.train(train_vecs)
    index.nprobe = nprobe
    print(f"[train] IVF-PQ 학습 완료 nlist={nlist} m={pq_m} nbits={nbits} ({time.time()-t:.1f}s)", flush=True)
    return index


def gcs_upload(local_dir, gcs_uri):
    print(f"[upload] {local_dir} -> {gcs_uri}", flush=True)
    subprocess.run(["gcloud", "storage", "cp", "-r", local_dir, gcs_uri], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units")
    ap.add_argument("--out", required=True, help="산출 디렉토리")
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--device", default="cuda", choices=["cuda", "mps", "cpu"])
    ap.add_argument("--chunking", default="tot", choices=["tot", "case", "casehdr"])
    ap.add_argument("--index", default="ivfpq", choices=["ivfpq", "flat"],
                    help="flat=압축없는 정확검색(소규모·고품질). casehdr면 보통 flat.")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--add-block", type=int, default=200_000, help="이만큼 모이면 index.add 후 폐기")
    ap.add_argument("--sample", type=int, default=400_000, help="IVF-PQ 학습 표본 청크 수")
    ap.add_argument("--nlist", type=int, default=8192)
    ap.add_argument("--pq-m", type=int, default=32, help="PQ 서브벡터 수(dim 나눠떨어져야)")
    ap.add_argument("--nbits", type=int, default=8)
    ap.add_argument("--nprobe", type=int, default=32)
    ap.add_argument("--faiss-threads", type=int, default=0, help="0=자동(darwin 1, 그외 전체)")
    ap.add_argument("--limit", type=int, default=None, help="앞 N개 유닛만(스모크 테스트)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--gcs-out", default=None, help="완료 후 산출 디렉토리를 업로드할 gs:// 경로")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()

    model, dim = load_embedder(a.model, a.device)
    if a.index == "ivfpq" and dim % a.pq_m != 0:
        sys.exit(f"[error] pq-m({a.pq_m})는 dim({dim})을 나눠떨어뜨려야 함")
    ppref = e5_prefix(a.model, "passage")

    if a.index == "flat":
        # 압축없는 정확검색. 소규모(casehdr=케이스당 1조각, 약 24만)라 학습 불필요·단일 pass.
        import faiss
        nt = a.faiss_threads if a.faiss_threads > 0 else (1 if sys.platform == "darwin" else (os.cpu_count() or 1))
        faiss.omp_set_num_threads(nt)
        index = faiss.IndexFlatIP(dim)  # 코사인(정규화 내적)
        total_est = 0
        print(f"[flat] IndexFlatIP dim={dim} faiss_threads={nt}", flush=True)
    else:
        # --- pass1: 학습표본 임베딩 → IVF-PQ 학습 ---
        sample_txts, total_est = reservoir_sample(a.units, a.chunking, a.sample, a.limit, a.seed)
        min_train = a.nlist * 39
        if len(sample_txts) < min_train:
            print(f"[warn] 학습표본 {len(sample_txts):,} < 권장 {min_train:,} → nlist 자동 축소", flush=True)
            a.nlist = max(64, len(sample_txts) // 39)
        print(f"[pass1] 학습표본 임베딩 {len(sample_txts):,}…", flush=True)
        train_vecs = encode(model, sample_txts, ppref, a.batch)
        index = build_ivfpq(train_vecs, dim, a.nlist, a.pq_m, a.nbits, a.nprobe, a.faiss_threads)
        del train_vecs, sample_txts

    # --- pass2: 전량 임베딩 → add + 매핑 기록 ---
    case_ids = []           # 정수인덱스 -> case_id 문자열
    id_to_idx = {}
    chunk_case_idx = []      # add 순서대로: 청크 -> 케이스 정수인덱스
    block_txt, block_cidx = [], []
    n_chunks = 0

    def flush_block():
        nonlocal n_chunks
        if not block_txt:
            return
        emb = encode(model, block_txt, ppref, a.batch)
        index.add(emb)
        chunk_case_idx.extend(block_cidx)
        n_chunks += len(block_txt)
        rate = n_chunks / (time.time() - t1)
        eta = (total_est - n_chunks) / rate / 3600 if rate else 0
        print(f"[pass2] {n_chunks:,}/{total_est:,} ({rate:.0f}/s, ETA {eta:.1f}h)", flush=True)
        block_txt.clear(); block_cidx.clear()

    t1 = time.time()
    for txt, cid in iter_chunks(a.units, a.chunking, a.limit):
        ci = id_to_idx.get(cid)
        if ci is None:
            ci = len(case_ids); id_to_idx[cid] = ci; case_ids.append(cid)
        block_txt.append(txt); block_cidx.append(ci)
        if len(block_txt) >= a.add_block:
            flush_block()
    flush_block()

    # --- 저장 ---
    import faiss
    faiss.write_index(index, os.path.join(a.out, "index.faiss"))
    np.save(os.path.join(a.out, "chunk_case_idx.npy"), np.asarray(chunk_case_idx, dtype="int32"))
    with open(os.path.join(a.out, "case_ids.json"), "w", encoding="utf-8") as f:
        json.dump(case_ids, f, ensure_ascii=False)
    with open(os.path.join(a.out, "case_meta.jsonl"), "w", encoding="utf-8") as f:
        for cid, meta in iter_case_meta(a.units, a.limit):
            f.write(json.dumps({"id": cid, **meta}, ensure_ascii=False) + "\n")
    manifest = {
        "model": a.model, "dim": dim, "chunking": a.chunking,
        "n_chunks": n_chunks, "n_cases": len(case_ids),
        "nlist": a.nlist, "pq_m": a.pq_m, "nbits": a.nbits, "nprobe": a.nprobe,
        "elapsed_h": round((time.time() - t0) / 3600, 3),
    }
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[done] 청크 {n_chunks:,} | 케이스 {len(case_ids):,} | {manifest['elapsed_h']}h", flush=True)
    print(json.dumps(manifest, ensure_ascii=False), flush=True)

    if a.gcs_out:
        gcs_upload(a.out, a.gcs_out)
        print("[upload] 완료", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
압축 방식 비교용 색인 빌더 (스모크 전용) — Pred-FirefromElec

목적: 같은 임베딩에서 여러 압축(faiss index_factory)을 만들어, 어느 압축이
'품질 살고 크기 작은가'를 한 번의 GPU 스모크로 비교한다. (build_rag_index.py 의 전량 2-pass와 달리
스모크라 임베딩을 통째 RAM에 올린다 — 1.4M×1024×4B≈5.8GB, g2-standard-8 32GB RAM에 들어감.)

산출(--out 아래 압축별 하위폴더, 각 폴더가 자족적):
  <factory>/index.faiss  <factory>/chunk_case_idx.npy  <factory>/case_ids.json
  manifest.json (공통 메타 + factory별 인덱스 바이트수)

빌더 규칙은 build_rag_index.py 와 동일: 같은 모델, normalize=True(코사인), bge-m3 접두어 없음, fp16(cuda).

사용(스모크 VM):
  python build_index_compare.py rag_units.jsonl --out idx_cmp --device cuda --limit 10000 \
    --gcs-out gs://constgx_electrofire/rag_index/compare/
"""
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
import sys, json, time, argparse, random, subprocess, re
import numpy as np

# 비교할 압축들(faiss index_factory 문자열). dim=1024 기준.
#  IVF8192,PQ32      = 현재(벡터당 32바이트, 128배 압축) — 품질 붕괴 재현용 기준선
#  OPQ32,...,PQ32    = 같은 32바이트 + 회전(OPQ)로 품질 회복 시도(크기 동일)
#  OPQ64,...,PQ64    = 64바이트 + 회전(유력 후보)
#  IVF8192,SQ8       = 8비트 스칼라양자(벡터당 1024바이트, 4배 압축) — 고품질 기준
DEFAULT_FACTORIES = "IVF8192,PQ32|OPQ32,IVF8192,PQ32|OPQ64,IVF8192,PQ64|IVF8192,SQ8"


def tot_lines(text):
    for ln in text.split("\n"):
        ln = ln.strip()
        if len(ln) >= 10:
            yield ln


def iter_chunks(path, limit):
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            u = json.loads(line)
            cid = u["id"]
            for ln in tot_lines(u.get("text", "")):
                yield ln, cid
            n += 1
            if limit and n >= limit:
                return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--nlist", type=int, default=8192)
    ap.add_argument("--nprobe", type=int, default=64)
    ap.add_argument("--sample", type=int, default=400_000, help="IVF/OPQ 학습 표본 청크 수")
    ap.add_argument("--factories", default=DEFAULT_FACTORIES, help="'|'로 구분한 index_factory 목록")
    ap.add_argument("--gcs-out", default=None)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()

    from sentence_transformers import SentenceTransformer
    import faiss
    nt = os.cpu_count() or 1
    faiss.omp_set_num_threads(nt)

    m = SentenceTransformer(a.model, device=a.device)
    m.max_seq_length = 512
    if a.device == "cuda":
        m = m.half()
    dim = m.get_sentence_embedding_dimension()
    print(f"[model] {a.model} dim={dim} device={a.device} fp16={a.device=='cuda'} faiss_threads={nt}", flush=True)

    # 1) 전량(스모크) 임베딩을 통째로 모으기
    texts, cids = [], []
    for txt, cid in iter_chunks(a.units, a.limit):
        texts.append(txt)
        cids.append(cid)
    print(f"[chunks] {len(texts):,} 조각 임베딩 시작", flush=True)
    emb = np.asarray(
        m.encode(texts, batch_size=a.batch, normalize_embeddings=True, show_progress_bar=False),
        dtype="float32",
    )
    print(f"[chunks] 임베딩 완료 {emb.shape} ({time.time()-t0:.0f}s)", flush=True)

    # case_id -> 정수 인덱스, chunk -> case 정수 매핑(공통)
    case_ids, id_to_idx, chunk_case = [], {}, []
    for cid in cids:
        ci = id_to_idx.get(cid)
        if ci is None:
            ci = len(case_ids); id_to_idx[cid] = ci; case_ids.append(cid)
        chunk_case.append(ci)
    chunk_case = np.asarray(chunk_case, dtype="int32")

    # 학습 표본(공통)
    rng = random.Random(42)
    idx = list(range(len(texts)))
    rng.shuffle(idx)
    train = emb[np.asarray(idx[: a.sample])]

    manifest = {"model": a.model, "dim": dim, "n_chunks": len(texts), "n_cases": len(case_ids),
                "nlist": a.nlist, "nprobe": a.nprobe, "variants": {}}

    # 2) 압축별 인덱스 생성
    for fac in a.factories.split("|"):
        fac = fac.strip()
        safe = re.sub(r"[^A-Za-z0-9]+", "_", fac).strip("_")
        d = os.path.join(a.out, safe)
        os.makedirs(d, exist_ok=True)
        t = time.time()
        index = faiss.index_factory(dim, fac, faiss.METRIC_INNER_PRODUCT)
        index.train(train)
        index.add(emb)
        try:
            faiss.extract_index_ivf(index).nprobe = a.nprobe
        except Exception:
            pass
        fp = os.path.join(d, "index.faiss")
        faiss.write_index(index, fp)
        np.save(os.path.join(d, "chunk_case_idx.npy"), chunk_case)
        with open(os.path.join(d, "case_ids.json"), "w", encoding="utf-8") as f:
            json.dump(case_ids, f, ensure_ascii=False)
        nbytes = os.path.getsize(fp)
        manifest["variants"][fac] = {"dir": safe, "index_bytes": nbytes}
        print(f"[build] {fac:28s} -> {nbytes/1e6:8.1f} MB ({time.time()-t:.0f}s)", flush=True)

    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(manifest['variants'])}개 압축 / {time.time()-t0:.0f}s", flush=True)

    if a.gcs_out:
        print(f"[upload] {a.out} -> {a.gcs_out}", flush=True)
        subprocess.run(["gcloud", "storage", "cp", "-r", a.out, a.gcs_out], check=True)
        print("[upload] 완료", flush=True)


if __name__ == "__main__":
    main()

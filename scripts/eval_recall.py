#!/usr/bin/env python3
"""
RAG 검색 정확도 채점 — recall@k / MRR (Pred-FirefromElec)

목적: 어떤 검색 설정(청킹 입도 × 임베딩 모델 × flat/IVF-PQ)으로 평가셋 질의를 돌린 결과를 받아
recall@1/3/5/10 과 MRR을 계산한다. 설정별로 이 숫자를 비교해 청킹·PQ를 확정한다.

입력 2개(JSONL):
  --eval     : build_eval_set.py 산출 (qid, gold_id, ...)
  --results  : 검색 결과. 한 줄 = {"qid": ..., "retrieved": ["caseid1","caseid2",...]}  (상위 k, 순위순)
출력: 전체 + kind/subject별 recall@k, MRR. 설정 이름은 --name 으로 표기.

사용:
  python3 eval_recall.py --eval eval_set_auto.jsonl --results results_bge_totnode_pq.jsonl --name "bge-m3/ToT/PQ"
"""
import json, argparse
from collections import defaultdict

KS = [1, 3, 5, 10]

def load(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: r = json.loads(line); out[r["qid"]] = r
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True); ap.add_argument("--results", required=True)
    ap.add_argument("--name", default="config")
    a = ap.parse_args()
    ev = load(a.eval); res = load(a.results)

    agg = {k: 0 for k in KS}; mrr = 0.0; n = 0
    by_kind = defaultdict(lambda: {"n": 0, **{k: 0 for k in KS}})
    missing = 0
    for qid, e in ev.items():
        gold = e["gold_id"]; r = res.get(qid)
        if r is None: missing += 1; continue
        ranked = r.get("retrieved", []); n += 1
        rank = next((i + 1 for i, c in enumerate(ranked) if c == gold), None)
        bk = by_kind[e.get("kind", "?")]; bk["n"] += 1
        for k in KS:
            hit = 1 if (rank is not None and rank <= k) else 0
            agg[k] += hit; bk[k] += hit
        if rank: mrr += 1.0 / rank

    print(f"\n=== {a.name} ===  (평가질의 {n}개, 결과누락 {missing})")
    if n:
        for k in KS: print(f"recall@{k:<2}: {agg[k]/n:.3f}")
        print(f"MRR    : {mrr/n:.3f}")
        print("--- kind별 ---")
        for kind, d in by_kind.items():
            if d["n"]:
                line = " ".join(f"R@{k}={d[k]/d['n']:.2f}" for k in KS)
                print(f"  {kind} (n={d['n']}): {line}")

if __name__ == "__main__":
    main()

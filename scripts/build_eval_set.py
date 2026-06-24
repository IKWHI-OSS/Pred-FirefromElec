#!/usr/bin/env python3
"""
71921 RAG 검색 평가셋 설계·생성 (Pred-FirefromElec)

목적: 청킹 입도·임베딩 모델·양자화(IVF-PQ) 강도를 '추정'이 아니라 recall@k '측정'으로
확정하기 위한 라벨된 평가셋을 만든다.

설계:
- 각 케이스(rag_units.jsonl 한 줄)는 자체 query_text(질문)를 가지므로,
  (질문 → 정답 케이스 id) 쌍을 공짜로 얻는다 = known-item retrieval.
- 층화 표본: (size × do × query_subject)로 고르게 뽑아 도메인 편향 없이 평가.
- ⚠ 누설 주의: query_text가 인덱싱되는 청크 텍스트에 포함되면 자동셋은 '쉬워진다'(상한값).
  → 진짜 의미검색 성능은 별도 '패러프레이즈/실사용 질의'(손으로 작성, 아래 템플릿)로 본다.
- 채점: eval_recall.py (recall@1/3/5/10, MRR).

사용:
  python3 build_eval_set.py rag_units.jsonl --n 120 --out eval_set_auto.jsonl
  # 산출: eval_set_auto.jsonl (자동 known-item) + eval_curated_template.jsonl (손으로 채울 패러프레이즈)
출력 레코드: {qid, query, gold_id, size, do, query_subject, kind}
"""
import sys, json, argparse, random
from collections import defaultdict, Counter

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units"); ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--out", default="eval_set_auto.jsonl"); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    random.seed(a.seed)

    # 1) 적재 + 층화 키
    strata = defaultdict(list)
    n_units = 0
    with open(a.units, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            u = json.loads(line); n_units += 1
            q = (u.get("text", "").split("\n", 1)[0]).strip()   # 첫 줄 = query_text
            if len(q) < 5: continue
            key = (u.get("size",""), u.get("do",""), u.get("query_subject",""))
            strata[key].append({"gold_id": u["id"], "query": q, "size": u.get("size",""),
                                "do": u.get("do",""), "query_subject": u.get("query_subject","")})

    # 2) 층화 비례 표본 (각 층 최소 1개 보장, 라운드로빈으로 N 채움)
    keys = [k for k in strata if strata[k]]
    for k in keys: random.shuffle(strata[k])
    picked = []; idx = {k: 0 for k in keys}
    # 라운드로빈
    while len(picked) < a.n:
        progressed = False
        for k in keys:
            if len(picked) >= a.n: break
            if idx[k] < len(strata[k]):
                picked.append(strata[k][idx[k]]); idx[k] += 1; progressed = True
        if not progressed: break

    with open(a.out, "w", encoding="utf-8") as fo:
        for i, r in enumerate(picked):
            fo.write(json.dumps({"qid": f"auto_{i:04d}", "query": r["query"], "gold_id": r["gold_id"],
                                 "size": r["size"], "do": r["do"], "query_subject": r["query_subject"],
                                 "kind": "auto_known_item"}, ensure_ascii=False) + "\n")

    # 3) 손으로 채울 패러프레이즈/실사용 질의 템플릿 (누설 없는 진짜 의미검색 평가용)
    tmpl = "eval_curated_template.jsonl"
    with open(tmpl, "w", encoding="utf-8") as ft:
        for i in range(15):
            ft.write(json.dumps({"qid": f"cur_{i:04d}", "query": "<여기에 실사용자 말투의 질문>",
                                 "gold_id": "<정답 케이스 id (rag_units.jsonl에서 찾아 기입)>",
                                 "kind": "curated_paraphrase"}, ensure_ascii=False) + "\n")

    print(f"유닛 {n_units:,} / 층 {len(keys)} / 자동셋 {len(picked)}개 → {a.out}")
    print(f"패러프레이즈 템플릿 15행 → {tmpl} (손으로 query·gold_id 채우기)")
    dist = Counter((r["size"], r["query_subject"]) for r in picked)
    print("표본 분포(size, subject) 상위:")
    for kv, c in dist.most_common(10): print(f"  {kv}: {c}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
71921 RAG 임베딩 단위 확정·추출 (Pred-FirefromElec)

목적: '실제 RAG 필드만 색인' 레버 실행 — query_text + tree_of_thought 추론 자연어만 임베딩 텍스트로,
수치 context(weather/terrain/fuel/Infra/occurrence)·짧은 범주값은 메타데이터로 분리.
→ 정제된 임베딩 단위(JSONL) 생성 + 줄어든 토큰·청크 수 재측정(3.3M 과대치 대비).

스키마 근거: scripts/aihub-71921-label-schema.md (labelling_data_info.query.query_text + tree_of_thought).

사용:
  python3 build_rag_units.py ./corpus_dl/aihub-71921 --out rag_units.jsonl --sample 3
출력:
  rag_units.jsonl  (1줄 = 1 case: {id, size, do, query_subject, query_purpose, query_type, fuel_type, text})
  화면: case 수 / 임베딩 토큰 / 예상청크 / 샘플 text
"""
import sys, os, io, re, json, zipfile, argparse, math

CONTEXT_KEYS = {"weather_conditions", "terrain_conditions", "fuel_conditions",
                "Infra_Social", "occurrence_status", "L0_context", "context"}
HANGUL = re.compile(r"[가-힣]")

def make_tok():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s, disallowed_special=()))), "tiktoken/cl100k_base"
    except Exception:
        return (lambda s: int(len(s) * 0.55)), "approx(char*0.55)"

def collect_nl(node, out):
    """tree_of_thought를 걸으며 자연어(한글 포함·길이>=15) 문자열만 수집. 수치 context 서브트리는 스킵."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in CONTEXT_KEYS:
                continue  # 수치 조건 딕셔너리는 임베딩에서 제외
            collect_nl(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_nl(v, out)
    elif isinstance(node, str):
        s = node.strip()
        if len(s) >= 15 and HANGUL.search(s):
            out.append(s)

def _num(v):
    """숫자면 보기 좋은 문자열(불필요한 소수 0 제거), 아니면 None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return str(int(f)) if f == int(f) else str(round(f, 1))

def extract_conditions(info):
    """L0_context의 결정 핵심 수치(풍속·습도·기온·경사·고도·가뭄·화염장)를 짧은 한글 줄로.
    케이스 구별력을 위해 헤더에 넣는다(임베딩 NL 본문에선 L0_context는 여전히 제외)."""
    ctx = {}
    def find_ctx(n):
        if ctx or not isinstance(n, (dict, list)): return
        if isinstance(n, dict):
            if "L0_context" in n and isinstance(n["L0_context"], dict):
                ctx.update(n["L0_context"]); return
            for v in n.values(): find_ctx(v)
        else:
            for v in n: find_ctx(v)
    find_ctx(info)
    if not ctx: return ""
    # 두 스키마 호환: Training=W/T/O 축약, Validation=weather_conditions/... 전체이름.
    def grp(*names):
        for nm in names:
            v = ctx.get(nm)
            if isinstance(v, dict): return v
        return {}
    W = grp("W", "weather_conditions")
    T = grp("T", "terrain_conditions")
    O = grp("O", "occurrence_status")
    parts = []
    for label, val, unit in [
        ("풍속", W.get("wind_speed"), "m/s"), ("습도", W.get("humidity_percent"), "%"),
        ("기온", W.get("temperature"), "도"), ("경사", T.get("slope"), "도"),
        ("고도", T.get("elevation"), "m"),
        ("가뭄", O.get("drought_duration_days") or O.get("drought_days") or W.get("drought_days"), "일"),
        ("화염장", O.get("flame_length"), "m")]:
        s = _num(val)
        if s is not None: parts.append(f"{label} {s}{unit}")
    return ", ".join(parts)

def parse_case(obj):
    info = obj.get("labelling_data_info", obj)
    q = info.get("query", {}) if isinstance(info, dict) else {}
    qtext = (q.get("query_text") or "").strip()
    nl = []
    tot = info.get("tree_of_thought") if isinstance(info, dict) else None
    if tot is not None:
        collect_nl(tot, nl)
    # 중복 제거(순서 보존)
    seen = set(); uniq = []
    for s in ([qtext] if qtext else []) + nl:
        if s and s not in seen:
            seen.add(s); uniq.append(s)
    text = "\n".join(uniq)
    # 메타 추출
    fuel_type = ""
    def find_fuel(n):
        nonlocal fuel_type
        if fuel_type or not isinstance(n, (dict, list)): return
        if isinstance(n, dict):
            if "fuel_type" in n and isinstance(n["fuel_type"], str): fuel_type = n["fuel_type"]
            for v in n.values(): find_fuel(v)
        else:
            for v in n: find_fuel(v)
    find_fuel(info)
    SUBJ_FIX = {"피혜예상": "피해예상", "제확산": "재확산", "진화벙법": "진화방법"}  # 오타 통일(3순위)
    subj = q.get("query_subject", "")
    meta = {"query_purpose": q.get("query_purpose", ""), "query_subject": SUBJ_FIX.get(subj, subj),
            "query_type": q.get("query_type", ""), "fuel_type": fuel_type,
            "conditions": extract_conditions(info)}      # 수치 조건(헤더용)
    return text, meta

def size_do_from_name(name):
    m = re.search(r"_(대형|중형|소형)_([가-힣]+도)", name)
    return (m.group(1), m.group(2)) if m else ("", "")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir"); ap.add_argument("--out", default="rag_units.jsonl")
    ap.add_argument("--chunk-size", type=int, default=512); ap.add_argument("--overlap", type=int, default=64)
    ap.add_argument("--sample", type=int, default=3)
    a = ap.parse_args()
    tok, method = make_tok()
    cases = toks = 0; samples = []
    fout = open(a.out, "w", encoding="utf-8")

    def handle(name, raw):
        nonlocal cases, toks
        try: obj = json.loads(raw.decode("utf-8", "ignore"))
        except Exception: return
        text, meta = parse_case(obj)
        if not text: return
        size, do = size_do_from_name(name)
        rec = {"id": os.path.basename(name), "size": size, "do": do, **meta, "text": text}
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        cases += 1; toks += tok(text)
        if len(samples) < a.sample: samples.append(text[:400])
        if cases % 5000 == 0:
            sys.stderr.write(f"[progress] case {cases:,}, 임베딩 토큰 {toks:,}\n"); sys.stderr.flush()

    for root, _, files in os.walk(a.corpus_dir):
        for f in files:
            p = os.path.join(root, f)
            if f.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(p) as z:
                        for n in z.namelist():
                            if n.lower().endswith(".json"): handle(os.path.join(f, n), z.read(n))
                except Exception as e: sys.stderr.write(f"[zip skip] {p}: {e}\n")
            elif f.lower().endswith(".json"):
                handle(f, open(p, "rb").read())
    fout.close()

    step = max(1, a.chunk_size - a.overlap); chunks = math.ceil(toks / step) if toks else 0
    print(f"\n토큰화: {method} | chunk_size={a.chunk_size} overlap={a.overlap}")
    print(f"임베딩 단위(case): {cases:,}")
    print(f"임베딩 토큰: {toks:,}")
    print(f"예상 청크: {chunks:,}")
    print(f"출력: {a.out}")
    print(f"\n[참고] 전체 문자열-leaf 과대치(이전) 대비 — 수치 context·메타 제외 후 값")
    for i, s in enumerate(samples, 1):
        print(f"\n--- 샘플 임베딩 text {i} ---\n{s}")

if __name__ == "__main__":
    main()

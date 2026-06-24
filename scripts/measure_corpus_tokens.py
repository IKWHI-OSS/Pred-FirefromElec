#!/usr/bin/env python3
"""
RAG 코퍼스 토큰/청크 실측 (Pred-FirefromElec)

목적: 오픈 임베딩 + 로컬 FAISS 색인 전, 코퍼스 규모를 추정으로가 아니라 실측한다.
대상: rag-corpus/(규정·논문·정책 PDF/HTML) + aihub-71921/(산불 Q&A JSON zip).

출력: 파일유형별 문서 수, 문자 수, 토큰 수, chunk_size 기준 예상 청크 수.
- 토큰: tiktoken(cl100k_base) 있으면 사용, 없으면 문자기반 근사(method 열에 표기).
  ※ 오픈 임베딩(BGE-m3 등) 실제 토큰 수와는 다소 차이날 수 있음 — 여기선 '규모 사이징'이 목적.
  ※ 비용은 오픈+로컬이라 $0. 토큰 수는 색인 시간·인덱스 크기·청크 수 산정용.

사용:
  python3 measure_corpus_tokens.py <코퍼스경로> [--chunk-size 512] [--overlap 64]
  # 버킷에서 먼저 받기:  gsutil -m cp -r gs://<BK>/rag-corpus gs://<BK>/aihub-71921 ./corpus_dl
  # 그 후:               python3 measure_corpus_tokens.py ./corpus_dl
"""
import sys, os, io, json, zipfile, argparse, math, re
from collections import defaultdict

# ---- 토큰화기 (tiktoken 우선, 없으면 문자기반 근사) ----
def make_tokenizer():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s, disallowed_special=()))), "tiktoken/cl100k_base"
    except Exception:
        # 근사: 한국어 혼합 텍스트는 cl100k에서 대략 char*0.55 토큰 (대략치)
        return (lambda s: int(len(s) * 0.55)), "approx(char*0.55)"

# ---- 텍스트 추출기 ----
def text_from_json_bytes(b):
    """JSON에서 문자열 leaf를 전부 모은다(임베딩 텍스트 상한 — 메타 포함, 추후 실제 Q/A 필드로 정밀화)."""
    try:
        obj = json.loads(b.decode("utf-8", "ignore"))
    except Exception:
        return ""
    out = []
    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(obj)
    return "\n".join(out)

def text_from_pdf(path):
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        sys.stderr.write(f"[pdf skip] {path}: {e}\n"); return ""

def text_from_html(b):
    s = b.decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s)

_PROG = {"n": 0}
def add(stats, kind, chars, toks):
    d = stats[kind]; d["docs"] += 1; d["chars"] += chars; d["toks"] += toks
    _PROG["n"] += 1
    if _PROG["n"] % 2000 == 0:
        tot = sum(s["toks"] for s in stats.values())
        sys.stderr.write(f"[progress] 문서(zip 내부 포함) {_PROG['n']:,}개, 누적 토큰 {tot:,}\n"); sys.stderr.flush()

def process_file(path, stats, tok):
    low = path.lower()
    if low.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.endswith("/"): continue
                    b = z.read(n)
                    if n.lower().endswith(".json"):
                        t = text_from_json_bytes(b); add(stats, "json(zip)", len(t), tok(t))
                    elif n.lower().endswith((".txt", ".md")):
                        t = b.decode("utf-8", "ignore"); add(stats, "txt(zip)", len(t), tok(t))
        except Exception as e:
            sys.stderr.write(f"[zip skip] {path}: {e}\n")
    elif low.endswith(".json"):
        b = open(path, "rb").read(); t = text_from_json_bytes(b); add(stats, "json", len(t), tok(t))
    elif low.endswith(".pdf"):
        t = text_from_pdf(path); add(stats, "pdf", len(t), tok(t))
    elif low.endswith((".html", ".htm")):
        b = open(path, "rb").read(); t = text_from_html(b); add(stats, "html", len(t), tok(t))
    elif low.endswith((".txt", ".md")):
        t = open(path, encoding="utf-8", errors="ignore").read(); add(stats, "txt", len(t), tok(t))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_dir")
    ap.add_argument("--chunk-size", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=64)
    a = ap.parse_args()
    tok, method = make_tokenizer()
    stats = defaultdict(lambda: {"docs": 0, "chars": 0, "toks": 0})
    seen = 0
    for root, _, files in os.walk(a.corpus_dir):
        for f in files:
            process_file(os.path.join(root, f), stats, tok)
            seen += 1
            if seen % 100 == 0:
                tot = sum(d["toks"] for d in stats.values())
                sys.stderr.write(f"[progress] 파일 {seen}개 처리, 누적 토큰 {tot:,}\n"); sys.stderr.flush()

    step = max(1, a.chunk_size - a.overlap)
    print(f"\n토큰화 방식: {method} | chunk_size={a.chunk_size} overlap={a.overlap}\n")
    print(f"{'유형':<12}{'문서':>8}{'문자':>15}{'토큰':>15}{'예상청크':>12}")
    print("-" * 62)
    T = {"docs": 0, "chars": 0, "toks": 0, "chunks": 0}
    for kind in sorted(stats):
        d = stats[kind]; ch = math.ceil(d["toks"] / step) if d["toks"] else 0
        print(f"{kind:<12}{d['docs']:>8,}{d['chars']:>15,}{d['toks']:>15,}{ch:>12,}")
        for k in ("docs", "chars", "toks"): T[k] += d[k]
        T["chunks"] += ch
    print("-" * 62)
    print(f"{'합계':<12}{T['docs']:>8,}{T['chars']:>15,}{T['toks']:>15,}{T['chunks']:>12,}")
    # 참고용 유료 색인비(만약 유료 전환 시) — 결정은 오픈이므로 $0, 비교 기록용
    m = T["toks"] / 1_000_000
    print(f"\n[참고] 유료 색인비 환산(전환 시): 3-small 배치 ${m*0.01:,.2f} / 표준 ${m*0.02:,.2f} / 3-large 배치 ${m*0.065:,.2f}")
    print("[결정] 오픈 임베딩 + 로컬 FAISS = 색인비 $0. 위 토큰 수는 청크 수·색인 시간 산정용.")

if __name__ == "__main__":
    main()

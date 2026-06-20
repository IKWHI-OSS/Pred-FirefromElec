"""build_index.py — 마운트된 GCS 버킷의 20개 클래스 zip을 전역 인덱싱.

각 클래스의 원천 zip(이미지)과 라벨 zip(JSON)을 파일명 stem 으로 페어링하여
하나의 index.jsonl 로 만든다. 학습/평가 시 이 인덱스만 읽으면
매번 20개 zip 의 central directory 를 재스캔하지 않아도 됨.

스키마 v1(knowledge/aihub-71388-label-schema.md §0):
  - JSON 1개 = 이미지 1개, 파일명 stem 동일(확장자만 .json↔.jpg).
  - zip 엔트리에 선행 슬래시 포함될 수 있음 → stem 기준 매칭이라 무관.

출력 index.jsonl 한 줄 = 한 샘플:
  {"cls": "brick", "img_zip": "<path>", "img": "<entry>",
   "lbl_zip": "<path>", "lbl": "<entry>"}

사용:
  python build_index.py --mount ~/gcs --split train --out train_index.jsonl
  python build_index.py --mount ~/gcs --split val   --out val_index.jsonl
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

from classes import CLASS_NAMES

# 스플릿별 zip 파일명 패턴 (AI Hub 71388 건설자재).
#   Training:   TS_건설자재_<cls>.zip (원천) / TL_건설자재_<cls>.zip (라벨)
#   Validation: VS_건설자재_<cls>.zip (원천) / VL_건설자재_<cls>.zip (라벨)
SPLIT_PREFIX = {
    "train": ("TS", "TL"),
    "val": ("VS", "VL"),
}


def find_zip(mount: Path, prefix: str, cls: str):
    """마운트 트리에서 <prefix>_..._<cls>.zip 한 개를 찾는다(경로 깊이 무관)."""
    hits = [p for p in mount.rglob(f"{prefix}_*{cls}.zip")]
    if not hits:
        return None
    # 가장 짧은 경로(정확 매칭) 우선
    hits.sort(key=lambda p: len(str(p)))
    return hits[0]


def index_class(img_zip: Path, lbl_zip: Path, cls: str):
    """한 클래스의 (이미지 엔트리 ↔ 라벨 엔트리) 페어 리스트."""
    with zipfile.ZipFile(img_zip) as iz:
        img_by_stem = {
            Path(n).stem: n
            for n in iz.namelist()
            if n.lower().endswith((".jpg", ".jpeg", ".png"))
        }
    with zipfile.ZipFile(lbl_zip) as lz:
        json_entries = [n for n in lz.namelist() if n.lower().endswith(".json")]

    rows, missing = [], 0
    for j in json_entries:
        stem = Path(j).stem
        img = img_by_stem.get(stem)
        if img is None:
            missing += 1
            continue
        rows.append({
            "cls": cls,
            "img_zip": str(img_zip), "img": img,
            "lbl_zip": str(lbl_zip), "lbl": j,
        })
    return rows, missing, len(img_by_stem), len(json_entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mount", required=True, help="gcsfuse 마운트 경로 (예: ~/gcs)")
    ap.add_argument("--split", choices=SPLIT_PREFIX, default="train")
    ap.add_argument("--out", default=None, help="출력 jsonl (기본: <split>_index.jsonl)")
    ap.add_argument("--classes", nargs="*", default=CLASS_NAMES,
                    help="인덱싱할 클래스(기본 20종 전체)")
    args = ap.parse_args()

    mount = Path(args.mount).expanduser()
    out = Path(args.out or f"{args.split}_index.jsonl")
    img_pre, lbl_pre = SPLIT_PREFIX[args.split]

    total, total_missing = 0, 0
    n_found_classes = 0
    with out.open("w") as f:
        for cls in args.classes:
            izp = find_zip(mount, img_pre, cls)
            lzp = find_zip(mount, lbl_pre, cls)
            if izp is None or lzp is None:
                print(f"  [skip] {cls}: zip 없음 (img={izp}, lbl={lzp})", file=sys.stderr)
                continue
            rows, missing, n_img, n_json = index_class(izp, lzp, cls)
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(rows)
            total_missing += missing
            n_found_classes += 1
            print(f"  {cls:16s} paired={len(rows):6d}  imgs={n_img:6d} jsons={n_json:6d} missing={missing}",
                  flush=True)

    print(f"\n[done] split={args.split}  classes={n_found_classes}/{len(args.classes)}  "
          f"samples={total}  missing_img={total_missing}  -> {out}")
    if total == 0:
        sys.exit("인덱스가 비었음 — --mount 경로/마운트 상태 확인")


if __name__ == "__main__":
    main()

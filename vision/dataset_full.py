"""dataset_full.py — 건설자재 20종 객체탐지 Dataset (본학습용).

리허설 dataset.AIHubBrailleDataset 를 확장:
  - 단일 클래스 → 20 클래스 (classes.CLASS_MAP).
  - 단일 zip 쌍 → build_index.py 가 만든 index.jsonl(다중 zip) 기반.
  - zip 핸들은 (경로별) lazy + fork-safe → num_workers>0 안전.

검증 확정 스키마(knowledge/aihub-71388-label-schema.md §0)를 그대로 유지:
  - geometry = polygon(flat) → min/max 로 xyxy 유도.
  - 좌표 = 절대픽셀, EXIF 미적용(stored) 공간 → exif_transpose 호출 금지.
  - 엣지: annotation 0개(빈 타겟), 경계 밖 polygon(클리핑), degenerate 박스(제외).
"""
import io
import json
import zipfile
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset

from classes import CLASS_MAP


def polygon_to_xyxy(poly):
    xs = poly[0::2]
    ys = poly[1::2]
    return min(xs), min(ys), max(xs), max(ys)


class AIHubConstructionDataset(Dataset):
    """index.jsonl 한 줄 = 한 샘플. zip 에서 스트리밍으로 읽음(로컬 추출 불필요)."""

    def __init__(self, index_path, transforms=None):
        self.transforms = transforms
        self.samples = []
        with open(index_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    self.samples.append(json.loads(line))
        if not self.samples:
            raise ValueError(f"빈 인덱스: {index_path}")
        # 경로별 ZipFile 핸들 캐시 (lazy, 프로세스별 — fork 후 자식에서 재오픈)
        self._zips = {}

    def _zip(self, path):
        z = self._zips.get(path)
        if z is None:
            z = zipfile.ZipFile(path)
            self._zips[path] = z
        return z

    def __len__(self):
        return len(self.samples)

    def _load_target(self, s, idx):
        d = json.loads(self._zip(s["lbl_zip"]).read(s["lbl"]))
        meta = d["images"][0]
        W, H = meta["width"], meta["height"]
        boxes, labels = [], []
        for a in d.get("annotations", []):
            cls = a.get("class")
            # 라벨값이 매핑에 없으면 zip 의 클래스로 폴백(각 zip 은 단일 자재)
            label_id = CLASS_MAP.get(cls) or CLASS_MAP.get(s["cls"])
            if label_id is None:
                continue
            poly = a.get("polygon")
            if not poly:
                continue
            x1, y1, x2, y2 = polygon_to_xyxy(poly)
            x1 = max(0, min(x1, W)); x2 = max(0, min(x2, W))
            y1 = max(0, min(y1, H)); y2 = max(0, min(y2, H))
            if x2 <= x1 or y2 <= y1:           # degenerate 가드
                continue
            boxes.append([x1, y1, x2, y2])
            labels.append(label_id)

        if boxes:
            boxes = torch.as_tensor(boxes, dtype=torch.float32)
            labels = torch.as_tensor(labels, dtype=torch.int64)
        else:
            boxes = torch.zeros((0, 4), dtype=torch.float32)
            labels = torch.zeros((0,), dtype=torch.int64)
        return {
            "boxes": boxes,
            "labels": labels,
            "image_id": torch.tensor([idx]),
            "orig_size": torch.tensor([H, W]),
        }

    def __getitem__(self, idx):
        s = self.samples[idx]
        raw = self._zip(s["img_zip"]).read(s["img"])
        # exif_transpose 호출 금지 (라벨이 stored 좌표) — Image.open 기본
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        target = self._load_target(s, idx)
        if self.transforms is not None:
            img = self.transforms(img)
        return img, target


def collate_fn(batch):
    return tuple(zip(*batch))

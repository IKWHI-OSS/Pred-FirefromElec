"""
AI Hub 71388 (건설자재 brailleBlock) — torchvision detection Dataset.

스키마 v1 (knowledge/aihub-71388-label-schema.md §0, 실측 확정):
- JSON 1개 = 이미지 1개. zip 엔트리에 선행 슬래시 포함.
- annotation 지오메트리는 'polygon'(flat [x1,y1,x2,y2,...]). bbox 없음 → min/max로 xyxy 유도.
- class = "brailleBlock" 단일 → {brailleBlock:1}, background=0.
- 좌표 = 절대픽셀, EXIF 미적용(stored) 공간 → exif_transpose 호출 금지.
- 엣지: annotation 0개/2개 존재, polygon이 경계 밖(클리핑) + degenerate 박스 가드.

zip 스트리밍으로 읽어 디스크 사용 0 (리허설용). num_workers=0 권장
(ZipFile 핸들은 프로세스별 lazy open — fork 후 자식에서 재오픈).
"""
import io
import json
import zipfile
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import Dataset

CLASS_MAP = {"brailleBlock": 1}  # 0 = background (torchvision 관례)


def polygon_to_xyxy(poly):
    """flat [x1,y1,x2,y2,...] -> (xmin, ymin, xmax, ymax)."""
    xs = poly[0::2]
    ys = poly[1::2]
    return min(xs), min(ys), max(xs), max(ys)


class AIHubBrailleDataset(Dataset):
    def __init__(self, img_zip, lbl_zip, transforms=None, skip_empty=True):
        self.img_zip_path = str(img_zip)
        self.lbl_zip_path = str(lbl_zip)
        self.transforms = transforms
        self._iz = None  # lazy per-process ZipFile handles
        self._lz = None

        # 인덱스 구축: JSON stem <-> 이미지 엔트리 페어링 (핸들은 즉시 닫음)
        with zipfile.ZipFile(self.img_zip_path) as iz:
            img_by_stem = {}
            for n in iz.namelist():
                low = n.lower()
                if low.endswith((".jpg", ".jpeg", ".png")):
                    img_by_stem[Path(n).stem] = n
        with zipfile.ZipFile(self.lbl_zip_path) as lz:
            json_entries = [n for n in lz.namelist() if n.lower().endswith(".json")]

        self.samples = []  # (json_entry, img_entry)
        self.n_missing_img = 0
        self.n_empty = 0
        for j in json_entries:
            stem = Path(j).stem
            img = img_by_stem.get(stem)
            if img is None:
                self.n_missing_img += 1
                continue
            self.samples.append((j, img))
        self.skip_empty = skip_empty

    # ---- lazy handles (fork-safe) ----
    def _img(self):
        if self._iz is None:
            self._iz = zipfile.ZipFile(self.img_zip_path)
        return self._iz

    def _lbl(self):
        if self._lz is None:
            self._lz = zipfile.ZipFile(self.lbl_zip_path)
        return self._lz

    def __len__(self):
        return len(self.samples)

    def _load_target(self, json_entry, idx):
        d = json.loads(self._lbl().read(json_entry))
        meta = d["images"][0]
        W, H = meta["width"], meta["height"]
        boxes, labels = [], []
        for a in d.get("annotations", []):
            cls = a.get("class")
            if cls not in CLASS_MAP:
                continue
            x1, y1, x2, y2 = polygon_to_xyxy(a["polygon"])
            # 경계 클리핑 (polygon 22/300이 OOB)
            x1 = max(0, min(x1, W)); x2 = max(0, min(x2, W))
            y1 = max(0, min(y1, H)); y2 = max(0, min(y2, H))
            # degenerate 가드 (FasterRCNN는 zero-area 박스 거부)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([x1, y1, x2, y2])
            labels.append(CLASS_MAP[cls])

        if boxes:
            boxes = torch.as_tensor(boxes, dtype=torch.float32)
            labels = torch.as_tensor(labels, dtype=torch.int64)
        else:
            boxes = torch.zeros((0, 4), dtype=torch.float32)
            labels = torch.zeros((0,), dtype=torch.int64)
        target = {
            "boxes": boxes,
            "labels": labels,
            "image_id": torch.tensor([idx]),
            "orig_size": torch.tensor([H, W]),
        }
        return target

    def __getitem__(self, idx):
        json_entry, img_entry = self.samples[idx]
        # EXIF 미적용으로 로드 (라벨이 stored 공간 기준) → exif_transpose 호출 안 함
        raw = self._img().read(img_entry)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        target = self._load_target(json_entry, idx)
        if self.transforms is not None:
            img = self.transforms(img)
        return img, target


def collate_fn(batch):
    """객체 수 가변 → 기본 collate 불가. torchvision detection 표준."""
    return tuple(zip(*batch))

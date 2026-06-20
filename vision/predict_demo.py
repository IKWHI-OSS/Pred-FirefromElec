"""predict_demo.py — 학습된 체크포인트로 예측 → bbox 시각화 PNG 저장.

사용(VM 안에서):
  python predict_demo.py --val-index val_index.jsonl --ckpt runs/constgx/last.pth \
      --n 8 --score-thresh 0.5 --out demo_out
출력: demo_out/pred_000.png ... (박스 + 클래스명 + 점수)
"""
import argparse
import random
from pathlib import Path

import torch
from torchvision.transforms import functional as F
from torchvision.utils import draw_bounding_boxes, save_image

from classes import NUM_CLASSES, ID_TO_NAME
from dataset_full import AIHubConstructionDataset
from train import build_model


def to_tensor(img):
    return F.to_tensor(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-index", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--score-thresh", type=float, default=0.5)
    ap.add_argument("--out", default="demo_out")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    ds = AIHubConstructionDataset(args.val_index, transforms=to_tensor)
    model = build_model(NUM_CLASSES, pretrained=False).to(device)
    ckpt = torch.load(args.ckpt, map_location=device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    random.seed(args.seed)
    idxs = random.sample(range(len(ds)), min(args.n, len(ds)))

    with torch.no_grad():
        for k, i in enumerate(idxs):
            img, _ = ds[i]
            pred = model([img.to(device)])[0]
            keep = pred["scores"] >= args.score_thresh
            boxes = pred["boxes"][keep].cpu()
            labels = pred["labels"][keep].cpu().tolist()
            scores = pred["scores"][keep].cpu().tolist()
            names = [f"{ID_TO_NAME.get(int(l), l)} {s:.2f}" for l, s in zip(labels, scores)]
            img_u8 = (img * 255).to(torch.uint8)
            if boxes.shape[0] > 0:
                img_u8 = draw_bounding_boxes(img_u8, boxes, labels=names,
                                             colors="red", width=4)
            save_image(img_u8.float() / 255, out / f"pred_{k:03d}.png")
            print(f"  pred_{k:03d}.png  idx={i} dets={boxes.shape[0]}")

    print(f"[done] {len(idxs)}개 예측 시각화 -> {out}")


if __name__ == "__main__":
    main()

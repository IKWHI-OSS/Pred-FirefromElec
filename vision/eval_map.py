"""eval_map.py — 검증셋(VS/VL)에서 mAP 평가.

torchmetrics.detection.MeanAveragePrecision (COCO 방식: mAP@[.5:.95], mAP@.5, 클래스별 AP).

사용(VM 안에서):
  python eval_map.py --val-index val_index.jsonl --ckpt runs/constgx/last.pth \
      --batch-size 4 --workers 8 [--limit 0]
"""
import argparse

import torch
from torch.utils.data import DataLoader, Subset
from torchvision.transforms import functional as F
from torchmetrics.detection.mean_ap import MeanAveragePrecision

from classes import NUM_CLASSES, ID_TO_NAME
from dataset_full import AIHubConstructionDataset, collate_fn
from train import build_model


def to_tensor(img):
    return F.to_tensor(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-index", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help=">0 이면 빠른 점검용 부분평가")
    ap.add_argument("--score-thresh", type=float, default=0.0,
                    help="평가는 보통 0(모든 예측 포함). 데모 시각화만 높임.")
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    ds = AIHubConstructionDataset(args.val_index, transforms=to_tensor)
    if args.limit and args.limit < len(ds):
        ds = Subset(ds, list(range(args.limit)))
    print(f"[data] val samples = {len(ds)}")
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.workers, collate_fn=collate_fn,
                        pin_memory=(device.type == "cuda"))

    model = build_model(NUM_CLASSES, pretrained=False).to(device)
    ckpt = torch.load(args.ckpt, map_location=device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    print(f"[model] loaded {args.ckpt} (trained epoch {ckpt.get('epoch')})")

    metric = MeanAveragePrecision(box_format="xyxy", class_metrics=True)

    with torch.no_grad():
        for imgs, targets in loader:
            imgs = [im.to(device) for im in imgs]
            preds = model(imgs)
            preds = [{k: v.detach().cpu() for k, v in p.items()} for p in preds]
            gts = [{"boxes": t["boxes"], "labels": t["labels"]} for t in targets]
            metric.update(preds, gts)

    res = metric.compute()
    print("\n==== mAP 결과 ====")
    print(f"  mAP@[.5:.95] = {res['map'].item():.4f}")
    print(f"  mAP@.5       = {res['map_50'].item():.4f}")
    print(f"  mAP@.75      = {res['map_75'].item():.4f}")

    # 클래스별 AP (class_metrics=True 일 때 제공)
    if "map_per_class" in res and res["map_per_class"].numel() > 1:
        classes = res.get("classes")
        per = res["map_per_class"]
        print("\n  클래스별 AP@[.5:.95]:")
        for c, ap_c in zip(classes.tolist(), per.tolist()):
            print(f"    {ID_TO_NAME.get(int(c), c):18s} {ap_c:.4f}")


if __name__ == "__main__":
    main()

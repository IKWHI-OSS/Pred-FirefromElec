"""train.py — 건설자재 20종 FasterRCNN 본학습 (GPU VM, CUDA + AMP).

리허설(rehearse.py)과의 차이 = 본학습 설정:
  - weights="DEFAULT"  (리허설은 weights=None 랜덤초기화였음 — 샌드박스 프록시 차단 때문).
  - num_classes = 21   (background + 20).
  - 기본 해상도(min 800 / max 1333), CUDA, AMP(혼합정밀), num_workers>0 스트리밍.
  - 에폭마다 체크포인트 저장 + resume 지원(스팟 VM 중단 대비).

사용(VM 안에서):
  python train.py --train-index train_index.jsonl \
      --epochs 12 --batch-size 4 --workers 8 --out runs/constgx \
      [--resume runs/constgx/last.pth] [--gcs-out gs://constgx-aihub-237/runs]
"""
import argparse
import os
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from torchvision.transforms import functional as F
from torchvision.models.detection import fasterrcnn_resnet50_fpn
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

from classes import NUM_CLASSES
from dataset_full import AIHubConstructionDataset, collate_fn


def to_tensor(img):
    return F.to_tensor(img)


def build_model(num_classes, pretrained=True):
    weights = "DEFAULT" if pretrained else None
    model = fasterrcnn_resnet50_fpn(weights=weights)
    in_feat = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_feat, num_classes)
    return model


def save_ckpt(path, model, opt, sched, scaler, epoch, args):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model": model.state_dict(),
        "optimizer": opt.state_dict(),
        "scheduler": sched.state_dict() if sched else None,
        "scaler": scaler.state_dict(),
        "epoch": epoch,
        "num_classes": NUM_CLASSES,
        "args": vars(args),
    }, path)


def maybe_gcs_upload(local_path, gcs_out):
    if gcs_out:
        os.system(f'gsutil -q cp "{local_path}" "{gcs_out.rstrip("/")}/" || true')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-index", required=True)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.005)
    ap.add_argument("--momentum", type=float, default=0.9)
    ap.add_argument("--weight-decay", type=float, default=5e-4)
    ap.add_argument("--out", default="runs/constgx")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--gcs-out", default=None, help="체크포인트 업로드할 gs:// 경로(선택)")
    ap.add_argument("--no-pretrained", action="store_true", help="weights=None (디버그용)")
    ap.add_argument("--log-every", type=int, default=50)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        print("[warn] CUDA 미감지 — CPU로 진행하면 매우 느림. GPU VM 인지 확인.")

    ds = AIHubConstructionDataset(args.train_index, transforms=to_tensor)
    print(f"[data] train samples = {len(ds)}")
    loader = DataLoader(
        ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, collate_fn=collate_fn,
        pin_memory=(device.type == "cuda"), persistent_workers=(args.workers > 0),
    )

    model = build_model(NUM_CLASSES, pretrained=not args.no_pretrained).to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=args.lr, momentum=args.momentum,
                          weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.StepLR(opt, step_size=max(1, args.epochs // 3), gamma=0.1)
    scaler = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda"))

    start_epoch = 0
    if args.resume and Path(args.resume).exists():
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model"])
        opt.load_state_dict(ckpt["optimizer"])
        if ckpt.get("scheduler"):
            sched.load_state_dict(ckpt["scheduler"])
        scaler.load_state_dict(ckpt["scaler"])
        start_epoch = ckpt["epoch"] + 1
        print(f"[resume] {args.resume} 에서 epoch {start_epoch} 부터 재개")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for epoch in range(start_epoch, args.epochs):
        model.train()
        t0 = time.time()
        running = 0.0
        for step, (imgs, targets) in enumerate(loader):
            imgs = [im.to(device) for im in imgs]
            targets = [{"boxes": t["boxes"].to(device),
                        "labels": t["labels"].to(device)} for t in targets]
            opt.zero_grad()
            with torch.cuda.amp.autocast(enabled=(device.type == "cuda")):
                loss_dict = model(imgs, targets)
                loss = sum(loss_dict.values())
            if not torch.isfinite(loss):
                print(f"[warn] non-finite loss at e{epoch} s{step} — 스킵")
                continue
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            running += loss.item()
            if step % args.log_every == 0:
                comp = {k: round(v.item(), 3) for k, v in loss_dict.items()}
                print(f"e{epoch} s{step}/{len(loader)} loss={loss.item():.4f} {comp}", flush=True)
        sched.step()
        dt = time.time() - t0
        print(f"[epoch {epoch}] mean_loss={running / max(1, len(loader)):.4f} "
              f"lr={sched.get_last_lr()[0]:.5f} time={dt/60:.1f}min", flush=True)

        last = out / "last.pth"
        save_ckpt(last, model, opt, sched, scaler, epoch, args)
        save_ckpt(out / f"epoch_{epoch:03d}.pth", model, opt, sched, scaler, epoch, args)
        maybe_gcs_upload(last, args.gcs_out)
        maybe_gcs_upload(out / f"epoch_{epoch:03d}.pth", args.gcs_out)

    print(f"[done] 학습 완료 — 체크포인트: {out}/last.pth")


if __name__ == "__main__":
    main()

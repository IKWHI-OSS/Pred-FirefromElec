"""
리허설 객체탐지 파이프라인 디버그 러너.
3단계 검증 게이트 (전량 본학습 전 파이프라인 무결성 확인):
  A. DataLoader 배치 1개 정상 형태
  B. bbox 시각화 1장 (좌표변환·라벨매핑 시각 검증)
  C. FasterRCNN 1 epoch (소수 샘플, CPU): loss dict 유한·역전파 동작

사용: python rehearse.py [IMG_ZIP] [LBL_ZIP]
"""
import sys
from pathlib import Path

import torch
from torchvision.transforms import functional as F
from torchvision.utils import draw_bounding_boxes, save_image
from torch.utils.data import DataLoader, Subset

from dataset import AIHubBrailleDataset, collate_fn

DEFAULT_BASE = "/sessions/ecstatic-fervent-babbage/mnt/aihub_dl/237.건설_현장_장비_모니터링_및_생산성_측정_데이터/01-1.정식개방데이터/Training"
IMG_ZIP = sys.argv[1] if len(sys.argv) > 1 else f"{DEFAULT_BASE}/01.원천데이터/TS_건설자재_brailleBlock.zip"
LBL_ZIP = sys.argv[2] if len(sys.argv) > 2 else f"{DEFAULT_BASE}/02.라벨링데이터/TL_건설자재_brailleBlock.zip"

OUT = Path(__file__).parent / "_out"
OUT.mkdir(exist_ok=True)
torch.manual_seed(0)


def to_tensor(img):
    return F.to_tensor(img)


def banner(s):
    print("\n" + "=" * 8 + f" {s} " + "=" * 8)


def build(ds=None):
    banner("BUILD DATASET")
    ds = AIHubBrailleDataset(IMG_ZIP, LBL_ZIP, transforms=to_tensor)
    print(f"samples paired: {len(ds)}  | missing-image json: {ds.n_missing_img}", flush=True)
    assert len(ds) > 0, "데이터셋이 비었음"
    return ds


def stage_a(ds):
    # ---------- Stage A: DataLoader 배치 1개 ----------
    banner("STAGE A: DataLoader batch")
    loader = DataLoader(ds, batch_size=2, shuffle=True, num_workers=0, collate_fn=collate_fn)
    imgs, targets = next(iter(loader))
    assert isinstance(imgs, tuple) and len(imgs) == 2, "배치 이미지 형태 이상"
    assert isinstance(targets, tuple) and isinstance(targets[0], dict), "타겟 형태 이상"
    for i, (im, t) in enumerate(zip(imgs, targets)):
        assert im.ndim == 3 and im.shape[0] == 3, f"이미지 텐서 CHW 아님: {im.shape}"
        assert t["boxes"].shape[1] == 4, "boxes [N,4] 아님"
        assert t["boxes"].shape[0] == t["labels"].shape[0], "boxes/labels 수 불일치"
        print(f"  img{i}: {tuple(im.shape)} dtype={im.dtype} max={im.max():.3f} | "
              f"boxes={tuple(t['boxes'].shape)} labels={t['labels'].tolist()}")
    print("STAGE A PASS ✅  (배치가 이미지 튜플 + 타겟 dict 튜플로 정상 반환)", flush=True)


def stage_b(ds):
    # ---------- Stage B: bbox 시각화 ----------
    banner("STAGE B: bbox visualization")
    # 박스가 있는 첫 샘플을 찾아 시각화 (라벨매핑·좌표변환 시각 검증)
    # 라벨만 읽어 탐색(이미지 로드 회피) → 찾은 인덱스만 풀 로드
    viz_idx = next(i for i in range(len(ds))
                   if ds._load_target(ds.samples[i][0], i)["boxes"].shape[0] > 0)
    img, tgt = ds[viz_idx]
    img_u8 = (img * 255).to(torch.uint8)
    drawn = draw_bounding_boxes(img_u8, tgt["boxes"], colors="red", width=8,
                                labels=["brailleBlock"] * tgt["boxes"].shape[0])
    out_png = OUT / "bbox_check.png"
    save_image(drawn.float() / 255, out_png)
    b = tgt["boxes"][0].tolist()
    print(f"  idx={viz_idx} boxes={tgt['boxes'].shape[0]} first_xyxy=[{b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}]")
    print(f"  saved -> {out_png}")
    print("STAGE B PASS ✅  (박스가 이미지 좌표계로 그려짐 — 육안 확인용 PNG 생성)", flush=True)


def stage_c(ds):
    # ---------- Stage C: FasterRCNN 1 epoch ----------
    banner("STAGE C: FasterRCNN 1-epoch debug (CPU, few samples)")
    from torchvision.models.detection import fasterrcnn_resnet50_fpn
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

    num_classes = 2  # background + brailleBlock
    # weights=None: 사전학습 가중치는 download.pytorch.org(프록시 차단)에서 받아야 함.
    # 리허설 목표(loss 유한·역전파 동작)엔 랜덤 초기화로 충분. 본학습 땐 한국 IP에서 DEFAULT 사용.
    # min_size/max_size 축소: CPU 디버그 속도 위해 내부 입력 해상도를 낮춤
    # (본학습 땐 기본 800/1333). 파이프라인 무결성 확인엔 무관.
    model = fasterrcnn_resnet50_fpn(weights=None, weights_backbone=None,
                                    min_size=256, max_size=400)
    in_feat = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_feat, num_classes)
    model.train()

    # 박스 있는 소수 샘플만 (빈 타겟은 리허설에서 제외)
    nonempty = []
    for i in range(len(ds)):
        if ds._load_target(ds.samples[i][0], i)["boxes"].shape[0] > 0:
            nonempty.append(i)
        if len(nonempty) == 2:
            break
    sub = Subset(ds, nonempty)
    dl = DataLoader(sub, batch_size=1, shuffle=True, num_workers=0, collate_fn=collate_fn)
    opt = torch.optim.SGD([p for p in model.parameters() if p.requires_grad],
                          lr=0.005, momentum=0.9, weight_decay=0.0005)

    print(f"  training on {len(sub)} samples, 1 epoch, CPU", flush=True)
    losses = []
    for step, (imgs, targets) in enumerate(dl):
        imgs = list(imgs)
        targets = [{k: v for k, v in t.items() if k in ("boxes", "labels")} for t in targets]
        loss_dict = model(imgs, targets)
        loss = sum(loss_dict.values())
        assert torch.isfinite(loss), f"loss가 유한하지 않음: {loss}"
        opt.zero_grad()
        loss.backward()
        # 역전파로 grad가 실제로 흘렀는지 확인
        gradnorm = sum(p.grad.abs().sum() for p in model.parameters() if p.grad is not None)
        assert gradnorm > 0, "grad가 0 — 역전파 미동작"
        opt.step()
        losses.append(loss.item())
        comp = {k: round(v.item(), 4) for k, v in loss_dict.items()}
        print(f"  step{step}: loss={loss.item():.4f} {comp}", flush=True)
    assert all(torch.isfinite(torch.tensor(l)) for l in losses), "NaN/Inf loss 발생"
    print(f"STAGE C PASS ✅  (loss 유한, 역전파 grad>0, optimizer step 동작) losses={['%.3f'%l for l in losses]}", flush=True)


if __name__ == "__main__":
    import os
    sel = os.environ.get("REH_STAGE", "ALL")
    ds = build()
    if sel in ("A", "AB", "ALL"):
        stage_a(ds)
    if sel in ("B", "AB", "ALL"):
        stage_b(ds)
    if sel in ("C", "ALL"):
        stage_c(ds)
    if sel == "ALL":
        banner("REHEARSAL RESULT")
        print("ALL STAGES PASS ✅ — 파이프라인 무결성 확인 완료 (Dataset→DataLoader→FasterRCNN 학습 루프)", flush=True)

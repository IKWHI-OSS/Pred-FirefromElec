#!/usr/bin/env bash
# setup_vm.sh — GPU VM 안에서 실행. CUDA torch + gcsfuse + 의존성 설치 후 GCS 버킷 마운트.
# Deep Learning VM(common-cu123) 기준: NVIDIA 드라이버는 이미 설치되어 있음.
#
# 사용(VM 안에서):  bash ~/vision/setup_vm.sh
set -euo pipefail

BUCKET="${BUCKET:-constgx-aihub-237}"
MNT="${MNT:-$HOME/gcs}"

echo "== 0) GPU/드라이버 확인 =="
nvidia-smi || { echo "드라이버 미설치 — 1~2분 더 기다린 뒤 재시도 (Deep Learning VM 자동설치)"; exit 1; }

echo "== 1) CUDA PyTorch 설치 =="
# Deep Learning VM(cu123)에 맞춰 CUDA 12.1 휠 설치. (샌드박스의 CPU 핀 torch==2.2.2 와 무관 — 여기선 정상 CUDA torch)
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install torchmetrics pycocotools pillow tqdm
python -c "import torch; print('torch', torch.__version__, 'cuda?', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

echo "== 2) 사전학습 weights 접근 확인 (weights=DEFAULT 용) =="
# 한국 IP(GCP 서울)에서는 download.pytorch.org 접근 정상이어야 함. 받아서 캐시.
python - <<'PY'
from torchvision.models.detection import fasterrcnn_resnet50_fpn
m = fasterrcnn_resnet50_fpn(weights="DEFAULT")
print("pretrained weights OK — params:", sum(p.numel() for p in m.parameters()))
PY

echo "== 3) gcsfuse 설치 =="
if ! command -v gcsfuse >/dev/null 2>&1; then
  export GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)"
  echo "deb https://packages.cloud.google.com/apt $GCSFUSE_REPO main" | sudo tee /etc/apt/sources.list.d/gcsfuse.list
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
  sudo apt-get update -q && sudo apt-get install -y gcsfuse
fi
gcsfuse --version

echo "== 4) 버킷 마운트 (읽기 전용, 랜덤리드 캐시 켜기) =="
mkdir -p "$MNT"
if mountpoint -q "$MNT"; then
  echo "이미 마운트됨: $MNT"
else
  # --implicit-dirs: gsutil cp -r 로 만든 경로 트리 인식.  -o ro: 읽기전용.
  # stat/type 캐시로 zip central-directory 반복 읽기 비용 절감.
  gcsfuse --implicit-dirs -o ro \
    --stat-cache-ttl 1h --type-cache-ttl 1h --max-conns-per-host 32 \
    "$BUCKET" "$MNT"
  echo "마운트 완료: $BUCKET -> $MNT"
fi

echo
echo "== 마운트 내용 확인 =="
find "$MNT" -name 'TS_*.zip' | head -3
echo "..."
echo "[done] 셋업 완료. 다음: python ~/vision/build_index.py --mount $MNT"

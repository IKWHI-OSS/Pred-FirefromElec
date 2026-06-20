#!/usr/bin/env bash
# provision_vm.sh — GCP GPU VM 생성 (asia-northeast3 / 서울, 데이터와 동일 리전 → egress 0)
# 본학습용 1회성 VM. 학습이 끝나면 반드시 delete_vm 으로 삭제(비용통제).
#
# 사전조건(로컬 또는 Cloud Shell):
#   - gcloud CLI 설치 + 로그인:  gcloud auth login
#   - 프로젝트 설정:             gcloud config set project <PROJECT_ID>
#   - Compute Engine API 활성화:  gcloud services enable compute.googleapis.com
#   - GPU 할당량 확인(중요):      아래 'quota' 명령. 무료체험 계정은 GPU 할당량이 0일 수 있음.
#
# 사용:
#   bash provision_vm.sh quota     # 서울 리전 GPU 할당량 조회 (먼저 실행 권장)
#   bash provision_vm.sh create    # VM 생성
#   bash provision_vm.sh ssh       # VM 접속
#   bash provision_vm.sh delete    # VM 삭제 (학습 종료 후 필수)
set -euo pipefail

# ---- 설정 (필요시 환경변수로 덮어쓰기) ----
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-asia-northeast3-b}"          # 서울. b존에 GPU 재고 많은 편(없으면 -a/-c 시도)
VM="${VM:-constgx-train}"
MACHINE="${MACHINE:-n1-standard-8}"        # 8 vCPU / 30GB — 스트리밍 dataloader CPU 여유
GPU_TYPE="${GPU_TYPE:-nvidia-tesla-t4}"    # T4 16GB(저렴, 재고 많음). 대안: nvidia-l4(24GB), nvidia-tesla-v100
GPU_COUNT="${GPU_COUNT:-1}"
DISK_GB="${DISK_GB:-100}"                  # 데이터는 GCS 스트리밍 → 큰 디스크 불필요(OS+체크포인트+코드만)
# Deep Learning VM 이미지: CUDA 드라이버·conda 사전탑재 (드라이버 수동설치 불필요)
IMAGE_FAMILY="${IMAGE_FAMILY:-common-cu123-debian-11}"
IMAGE_PROJECT="${IMAGE_PROJECT:-deeplearning-platform-release}"
# 비용절감: SPOT=1 이면 스팟(선점형) VM — 최대 60~91% 저렴하나 중단 가능(train.py가 resume 지원).
SPOT="${SPOT:-0}"

case "${1:-}" in
  quota)
    echo "== 서울(asia-northeast3) 리전 GPU/CPU 할당량 =="
    gcloud compute regions describe asia-northeast3 \
      --project "$PROJECT" \
      --format="table(quotas.metric,quotas.limit,quotas.usage)" \
      | grep -iE 'GPU|NVIDIA|PREEMPTIBLE|CPU' || true
    echo
    echo "limit=0 이면 GPU 사용 불가 → IAM & Admin > Quotas 에서 'GPUs (all regions)' 또는"
    echo "'NVIDIA T4 GPUs' 상향 요청 필요. 무료체험 계정은 보통 0 → 결제계정 업그레이드 후 요청."
    ;;

  create)
    SPOT_FLAGS=()
    if [ "$SPOT" = "1" ]; then
      SPOT_FLAGS=(--provisioning-model=SPOT --instance-termination-action=STOP)
      echo "[info] SPOT(선점형) VM 으로 생성 — 저렴하나 중단 가능. train.py resume 로 복구."
    fi
    echo "[info] 생성: $VM ($MACHINE + ${GPU_COUNT}x${GPU_TYPE}) @ $ZONE"
    gcloud compute instances create "$VM" \
      --project="$PROJECT" \
      --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --accelerator="type=${GPU_TYPE},count=${GPU_COUNT}" \
      --image-family="$IMAGE_FAMILY" \
      --image-project="$IMAGE_PROJECT" \
      --boot-disk-size="${DISK_GB}GB" \
      --boot-disk-type=pd-ssd \
      --maintenance-policy=TERMINATE \
      --metadata="install-nvidia-driver=True" \
      --scopes=https://www.googleapis.com/auth/cloud-platform \
      "${SPOT_FLAGS[@]}"
    echo
    echo "[done] 생성 완료. 1~2분 후 드라이버 설치 완료됨."
    echo "  접속:   bash provision_vm.sh ssh"
    echo "  ⚠ 학습 끝나면 반드시:  bash provision_vm.sh delete"
    ;;

  ssh)
    gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE"
    ;;

  push)
    # 로컬 vision/ 코드를 VM 으로 복사
    gcloud compute scp --recurse --project="$PROJECT" --zone="$ZONE" \
      "$(dirname "$0")" "$VM:~/vision"
    echo "[done] vision/ → $VM:~/vision 복사 완료"
    ;;

  delete)
    echo "[warn] VM '$VM' 를 삭제합니다 (부팅디스크 포함). 체크포인트를 GCS에 올렸는지 확인하세요."
    read -r -p "정말 삭제? (yes/no) " ans
    [ "$ans" = "yes" ] || { echo "취소됨"; exit 0; }
    gcloud compute instances delete "$VM" --project="$PROJECT" --zone="$ZONE" --quiet
    echo "[done] 삭제 완료 — 과금 중지."
    ;;

  *)
    echo "사용: bash provision_vm.sh {quota|create|ssh|push|delete}"
    echo "  먼저 'quota' 로 GPU 할당량(>0) 확인 → 'create' → 'push' → 'ssh' → 학습 → 'delete'"
    exit 1
    ;;
esac

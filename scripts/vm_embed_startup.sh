#!/bin/bash
# 자가종료 GPU 배치 VM startup (범용) — 메타데이터로 받은 작업을 GPU에서 돌리고 인스턴스를 스스로 삭제.
# 프로젝트 무관: 입력/출력/실행명령을 VM 생성 시 --metadata로 주입한다. 본문에 프로젝트 값 없음(지식 오염 방지).
#   metadata attrs (생성 시 --metadata=KEY=VALUE 로 전달):
#     gcs-in   : 입력(데이터+러너)이 있는 gs:// 디렉토리. 통째로 /root 로 받음.
#     gcs-out  : 산출/로그를 올릴 gs:// 디렉토리(러너가 직접 올리면 여기엔 실행로그만 올라감).
#     run-cmd  : /root 에서 실행할 명령 한 줄. 예) /opt/conda/bin/python build_rag_index.py ... --device cuda --gcs-out gs://.../
#     pip-pkgs : (선택) 추가 설치 패키지. 기본 "sentence-transformers faiss-cpu".
# 가정: Deep Learning VM(pytorch-latest-gpu) — torch+CUDA 사전설치, conda python = /opt/conda/bin.
set -x
LOG=/var/log/gpujob.log
exec > "$LOG" 2>&1

META="http://metadata/computeMetadata/v1/instance"
# -f: 없는 메타데이터 키는 404 HTML 대신 빈 출력으로(그래야 선택 키 기본값 처리가 동작).
attr() { curl -sf -H "Metadata-Flavor: Google" "$META/attributes/$1"; }
GCS_IN=$(attr gcs-in)
GCS_OUT=$(attr gcs-out)
RUN_CMD=$(attr run-cmd)
PIP_PKGS=$(attr pip-pkgs); [ -z "$PIP_PKGS" ] && PIP_PKGS="sentence-transformers faiss-cpu"
ZONE=$(curl -s -H "Metadata-Flavor: Google" "$META/zone" | awk -F/ '{print $NF}')
NAME=$(curl -s -H "Metadata-Flavor: Google" "$META/name")

# torch가 import되는 python을 탐색(이미지마다 경로 상이) → `python`으로 심볼릭링크해 통일.
PY=""
for c in python3 /opt/conda/bin/python /usr/bin/python3 $(ls /opt/conda/envs/*/bin/python /opt/*/bin/python 2>/dev/null); do
  if "$c" -c "import torch" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && PY=python3
ln -sf "$(command -v "$PY" 2>/dev/null || echo "$PY")" /usr/local/bin/python
echo "[startup] PY=$PY torch=$(python -c 'import torch;print(torch.__version__, torch.cuda.is_available())' 2>&1)"

# GPU 드라이버 준비 대기(이미지가 첫 부팅에 설치)
for i in $(seq 1 30); do nvidia-smi && break || sleep 10; done

python -m pip install -q --no-cache-dir $PIP_PKGS
# 텍스트 임베딩엔 torchaudio/torchvision 불요. 이미지 사전설치본이 torch와 ABI 불일치라
# transformers가 로드하다 죽음 → 제거해 깨진 import를 차단(텍스트 경로엔 영향 없음).
python -m pip uninstall -y torchaudio torchvision >/dev/null 2>&1 || true
echo "[startup] post-pip torch=$(python -c 'import torch;print(torch.__version__, torch.cuda.is_available())' 2>&1)"

# 입력 통째로 받기(데이터+러너). 와일드카드 실패 시 디렉토리째 재시도.
cd /root
gcloud storage cp -r "$GCS_IN/*" /root/ || gcloud storage cp -r "$GCS_IN" /root/

# 작업 실행(프로젝트별 명령은 run-cmd 메타데이터에서 옴)
eval "$RUN_CMD"
RC=$?
echo "JOB_EXIT=$RC"

# 실행로그 업로드(성패 무관 — 실패 시 디버깅용)
[ -n "$GCS_OUT" ] && gcloud storage cp "$LOG" "$GCS_OUT/run.log" || true

# 성공 시에만 자가삭제(과금 정지). 실패면 VM 보존 → SSH 디버그. 7h max-run-duration이 백스톱.
if [ "${RC:-1}" -eq 0 ]; then
  gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet
else
  echo "[startup] FAILED RC=$RC — VM 보존(SSH 디버그용)."
fi

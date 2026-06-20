#!/usr/bin/env bash
# 전량 적재 루프 — filekey 1개씩: 다운로드 → 병합 → 무결성 → GCS 업로드 → 크기검증 → 로컬삭제.
# 공간 안전(414GB를 4.4GB/디스크에 다 안 받음): 파일키 단위로 받고 검증 후 즉시 삭제하며 전진.
# ⚠ 반드시 한국 IP(집)인 Mac에서 실행. 클라우드/해외 IP는 AI Hub가 502로 차단.
#
# 사용:
#   export AIHUB_KEY='발급키'
#   export GCS_BUCKET='gs://constgx-aihub-237'
#   bash dl_to_gcs_loop.sh 504524 504566 504608 504650   # filekey 나열
#   (filekey 목록은 먼저:  aihubshell -mode l -datasetkey 71388  로 확보)
#
# 안전 원칙(파괴적 삭제는 검증 게이트 통과 후에만):
#   - unzip -t 통과 + GCS 업로드 후 원격 크기 == 로컬 크기 일치해야 로컬 rm.
#   - 한 단계라도 실패하면 그 filekey는 로컬 보존하고 로그에 FAIL 남기고 다음으로.
set -uo pipefail

DATASETKEY=71388
DLDIR="${DLDIR:-$HOME/aihub_dl}"          # 홈 보호폴더 회피 위해 별도 폴더
KEY="${AIHUB_KEY:?AIHUB_KEY 환경변수 필요}"
BUCKET="${GCS_BUCKET:?GCS_BUCKET 환경변수 필요 (예: gs://constgx-aihub-237)}"
LOG="${DLDIR}/dl_loop_$(date +%Y%m%d_%H%M%S).log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$DLDIR"; cd "$DLDIR"
log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

for FK in "$@"; do
  log "=== filekey $FK 시작 ==="
  before=$(mktemp); find "$DLDIR" -name '*.zip' -newermt '1970-01-01' 2>/dev/null | sort > "$before"

  # 1) 다운로드 (패치된 aihubshell가 자동 병합. 끊기면 -C - 로 resume)
  if ! aihubshell -mode d -datasetkey "$DATASETKEY" -aihubapikey "$KEY" -filekey "$FK" 2>&1 | tee -a "$LOG"; then
    log "FAIL[$FK] 다운로드 단계 비정상 종료 — 보존하고 다음"; rm -f "$before"; continue
  fi

  # 2) 병합 누락분 폴백 (.part 남아있으면)
  if find "$DLDIR" -name '*.part*' | grep -q .; then
    log "[$FK] .part 잔존 → merge_parts.sh 폴백"
    bash "$SCRIPT_DIR/merge_parts.sh" "$DLDIR" 2>&1 | tee -a "$LOG"
  fi

  # 3) 이번에 새로 생긴 zip 식별
  after=$(mktemp); find "$DLDIR" -name '*.zip' 2>/dev/null | sort > "$after"
  mapfile -t NEW < <(comm -13 "$before" "$after")
  rm -f "$before" "$after"
  if [ "${#NEW[@]}" -eq 0 ]; then log "FAIL[$FK] 새 zip 없음 — 0바이트 병합 의심, 보존하고 다음"; continue; fi

  for Z in "${NEW[@]}"; do
    [ -s "$Z" ] || { log "FAIL[$FK] 0바이트: $Z (조각 보존)"; continue; }
    # 4) 무결성
    if ! unzip -t "$Z" >/dev/null 2>&1; then log "FAIL[$FK] unzip -t 실패: $Z (보존)"; continue; fi
    # 5) 업로드 (버킷 내 원본 상대경로 보존)
    REL="${Z#$DLDIR/}"
    if ! gsutil -q cp "$Z" "$BUCKET/$REL" 2>&1 | tee -a "$LOG"; then log "FAIL[$FK] 업로드 실패: $Z (보존)"; continue; fi
    # 6) 크기검증 (로컬 == 원격)
    L=$(stat -f%z "$Z" 2>/dev/null || stat -c%s "$Z")
    R=$(gsutil stat "$BUCKET/$REL" 2>/dev/null | awk -F': *' '/Content-Length/{print $2}')
    if [ "$L" != "$R" ]; then log "FAIL[$FK] 크기 불일치 L=$L R=$R: $Z (로컬 보존)"; continue; fi
    # 7) 검증 통과 → 로컬 삭제 + 조각 정리
    rm -f "$Z"; rm -f "${Z%.zip}".part* 2>/dev/null
    log "OK[$FK] $REL  ($L bytes) 업로드·검증·삭제 완료"
  done
  log "=== filekey $FK 종료 ==="
done
log "전체 루프 종료. 로그: $LOG"

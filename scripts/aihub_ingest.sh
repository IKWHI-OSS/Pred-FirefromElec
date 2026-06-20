#!/usr/bin/env bash
# AI Hub 71388 단일 에이전트 적재 러너.
# 다운로드→무결성→업로드→크기검증→삭제 를 filekey 단위로 무한루프 없이 반복.
# ⚠ 한국 IP Mac에서 실행. 삭제는 두 게이트(무결성+크기) 통과 후에만.
#
# 연관 문서 (사람/에이전트가 읽음 — 이 스크립트가 파싱하지는 않음. 전부 같은 scripts/ 폴더):
#   INGEST-AGENT.md            정책: 재시도 한도·DIAGNOSIS 표·무한루프 방지·HITL
#   aihub-71388-filekey-map.md filekey 목록/진행상태/사이클 (크기는 아래 fk_gb()에 내장)
#   aihub-71388-label-schema.md 라벨 스키마(학습 단계 참고)
#   .env (.env.example)        KEY·BK 비밀값 — 시작 시 자동 로드
#
# 사용:
#   export KEY='aihub키'; export BK='gs://constgx-aihub-237'
#   bash aihub_ingest.sh 504525 504526 504527 ...
#   (재실행하면 상태파일의 DONE은 자동 스킵 → 멱등/재개)
set -uo pipefail

DATASETKEY=71388
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# .env 자동 로드 (scripts/.env). 여기서 KEY, BK 정의 → 매번 export 불필요. (.gitignore에 .env 등록됨)
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
DLDIR="${DLDIR:-$HOME/aihub_dl}"
KEY="${KEY:-}"; BK="${BK:-}"   # 검증은 preflight에서(미설정 시 JSONL에 로깅 후 종료)
AIHUBSHELL="${AIHUBSHELL:-/usr/local/bin/aihubshell}"
STATE="$DLDIR/ingest_state.tsv"
LOG="$DLDIR/ingest_$(date +%Y%m%d).jsonl"

# 한도 (무한루프 방지)
DL_MAX=3; INTEG_MAX=2; UP_MAX=3; SIZE_MAX=3   # 단계별 재시도
FK_ATTEMPT=2                                   # filekey 전체 재시도
HALT_CONSEC=2                                  # 연속 FAILED 차단기

mkdir -p "$DLDIR"; cd "$DLDIR"; touch "$STATE"
ts(){ date +%Y-%m-%dT%H:%M:%S; }
logj(){ # logj fk step result "msg"
  printf '{"ts":"%s","fk":"%s","step":"%s","result":"%s","msg":"%s"}\n' \
    "$(ts)" "$1" "$2" "$3" "${4:-}" | tee -a "$LOG" ; }
state_get(){ awk -F'\t' -v k="$1" '$1==k{print $2}' "$STATE" | tail -1; }
state_set(){ printf '%s\t%s\t%s\n' "$1" "$2" "$(ts)" >> "$STATE"; }

# filekey 크기(GB) — filekey-map.md 기준. 모르면 1(라벨/GPS 소형).
RATE_MBs="${RATE_MBs:-30}"   # 다운로드 속도(MB/s) 추정용. 504527 실측 ~36 → 30으로 보정(.env로 조정 가능)
fk_gb(){ case "$1" in
  504524)echo 15;; 504525)echo 14;; 504526)echo 22;; 504527)echo 10;; 504528)echo 17;;
  504529)echo 16;; 504530)echo 12;; 504531)echo 13;; 504532)echo 15;; 504533)echo 13;;
  504534)echo 13;; 504535)echo 22;; 504536)echo 15;; 504537)echo 14;; 504538)echo 9;;
  504539)echo 6;; 504540)echo 19;; 504541)echo 22;; 504542)echo 20;; 504543)echo 13;;
  504544)echo 40;; 504565)echo 5;; 504628)echo 6;; 504649)echo 1;;
  504608)echo 4;; 504609)echo 3;; 504610)echo 4;; 504611)echo 2;; 504612)echo 3;;
  504613)echo 3;; 504614)echo 2;; 504615)echo 3;; 504616)echo 3;; 504617)echo 3;;
  504618)echo 3;; 504619)echo 3;; 504620)echo 3;; 504621)echo 4;; 504622)echo 1;;
  504623)echo 5;; 504624)echo 4;; 504625)echo 4;; 504626)echo 2;; 504627)echo 2;;
  *)echo 1;; esac; }
est_min(){ local gb; gb=$(fk_gb "$1"); echo $(( gb*1024/RATE_MBs/60 )); }   # 다운로드 예상(분)
hms(){ local s=$1; printf '%dm%02ds' $((s/60)) $((s%60)); }

# filekey → 기대 zip 이름패턴 (건설자재 TS/TL/VS/VL). 기존 유효 zip 재사용 가드용.
MATS="brailleBlock brick castIronCover circleManhole collectorWell curbStone deckPlate doubleWallPipe floorPost flumeTube forms pvcPipe rubberCone scaffold squareManhole steelBar steelGrating trenchCover waterBarrier wideflangeShapes"
fk_expect(){ # echo "<TIER>_건설자재_<mat>" 또는 "" (비건설자재)
  local fk=$1 tier base;
  if   [ "$fk" -ge 504524 ] && [ "$fk" -le 504543 ]; then tier=TS; base=504524
  elif [ "$fk" -ge 504566 ] && [ "$fk" -le 504585 ]; then tier=TL; base=504566
  elif [ "$fk" -ge 504608 ] && [ "$fk" -le 504627 ]; then tier=VS; base=504608
  elif [ "$fk" -ge 504650 ] && [ "$fk" -le 504669 ]; then tier=VL; base=504650
  else echo ""; return; fi
  local i=$((fk-base)); set -- $MATS; eval "echo \"${tier}_건설자재_\${$((i+1))}\""
}

# ---- preflight (통과 못하면 시작 안 함) ----
preflight(){
  [ -n "$KEY" ] || { logj - preflight ABORT "KEY 미설정 — scripts/.env 에 KEY=... (.env.example 참고)"; return 1; }
  case "$BK" in gs://*) ;; *) logj - preflight ABORT "BK 형식오류(gs://… 이어야): '$BK'"; return 1;; esac
  command -v "$AIHUBSHELL" >/dev/null 2>&1 || command -v aihubshell >/dev/null 2>&1 \
    || { logj - preflight ABORT "aihubshell 없음"; return 1; }
  # 패치(한글 글롭 병합) 확인 — 미적용이면 0바이트 위험
  if ! grep -q 'ls .*part' "$AIHUBSHELL" 2>/dev/null; then
    logj - preflight ABORT "aihubshell 병합패치 미적용 → 재패치 필요(MEMORY 2026-06-15)"; return 1
  fi
  command -v gsutil >/dev/null 2>&1 || { logj - preflight ABORT "gsutil 없음"; return 1; }
  gsutil ls -b "$BK" >/dev/null 2>&1 || gsutil mb -l asia-northeast3 -b on "$BK" \
    || { logj - preflight ABORT "버킷 접근/생성 실패(인증 의심)"; return 1; }
  logj - preflight OK "preflight 통과"; return 0
}

# ---- 단계 함수 (성공 0 / 실패 비0) ----
new_zip_after_download(){ find "$DLDIR" -name '*.zip' -newer "$1" 2>/dev/null; }

download_one(){ # $1=fk  → 새 zip이 생기면 0
  local fk="$1" mark; mark=$(mktemp); local n=1
  while [ $n -le $DL_MAX ]; do
    "$AIHUBSHELL" -mode d -datasetkey "$DATASETKEY" -aihubapikey "$KEY" -filekey "$fk" \
      > "$DLDIR/aihub_${fk}e.log" 2>&1
    # 성공 판정 우선: mark 이후 새로 생긴 0바이트 아닌 zip이 있으면 성공.
    #   (로그 스크래핑보다 산출물 존재가 진실. curl 진행률의 '502M' 같은 숫자 오매칭 원천 차단.)
    if [ -n "$(find "$DLDIR" -name '*.zip' -newer "$mark" -size +0c 2>/dev/null)" ]; then
      logj "$fk" download OK "attempt $n"; rm -f "$mark"; return 0
    fi
    # zip 없음 → 이때만 실패 원인 진단. DIAGNOSIS #4: 진짜 해외차단/HTTP 502만 (바이트 숫자 아님)
    if grep -qiE '해외 다운로드 제한|국외 접속|HTTP/[0-9.]+ 502|HTTP status[: ]*502' "$DLDIR/aihub_${fk}e.log"; then
      logj "$fk" download ABORT "해외차단/HTTP502 — 한국 IP 필요"; rm -f "$mark"; return 2
    fi
    # DIAGNOSIS #2: 0바이트/새 zip 없음(병합 미완 등) → 병합 폴백 후 재시도
    logj "$fk" download RETRY "0바이트/새 zip 없음 → merge_parts 폴백 (attempt $n)"
    [ -x "$SCRIPT_DIR/merge_parts.sh" ] && bash "$SCRIPT_DIR/merge_parts.sh" "$DLDIR" >>"$LOG" 2>&1
    n=$((n+1)); sleep $((n*20))
  done
  logj "$fk" download FAIL "$DL_MAX회 초과"; rm -f "$mark"; return 1
}

verify_integrity(){ # 새로 받은 zip 전수 unzip -t
  local fk="$1" z n=1
  while [ $n -le $INTEG_MAX ]; do
    local bad=0
    for z in $(find "$DLDIR" -name '*.zip'); do
      unzip -tqq "$z" >/dev/null 2>&1 || { logj "$fk" integrity RETRY "손상 $z (attempt $n)"; bad=1; break; }
    done
    [ $bad -eq 0 ] && { logj "$fk" integrity OK ""; return 0; }
    n=$((n+1))   # 손상 = 재다운로드가 corrective (호출측에서 처리)
    return 3     # 3 = 재다운로드 필요 신호
  done
  return 1
}

upload_one(){ # $1=fk
  local fk="$1" n=1
  while [ $n -le $UP_MAX ]; do
    if gsutil -m cp -r 237* "$BK/" >>"$LOG" 2>&1; then logj "$fk" upload OK "attempt $n"; return 0; fi
    # 인증류면 ABORT
    if gsutil ls "$BK" 2>&1 | grep -qiE 'Anonymous|401|403|credential'; then
      logj "$fk" upload ABORT "인증 실패 → gcloud auth login 필요"; return 2
    fi
    logj "$fk" upload RETRY "일시장애 (attempt $n)"; n=$((n+1)); sleep $((n*15))
  done
  logj "$fk" upload FAIL "$UP_MAX회 초과"; return 1
}

verify_size(){ # 로컬==GCS, 통과해야 삭제
  local fk="$1" f L R n=1
  while [ $n -le $SIZE_MAX ]; do
    local bad=0
    for f in $(find 237* -name '*.zip'); do
      L=$(stat -f%z "$f"); R=$(gsutil stat "$BK/$f" 2>/dev/null | awk -F': *' '/Content-Length/{print $2}')
      [ "$L" = "$R" ] || { logj "$fk" size RETRY "MISMATCH $f L=$L R=$R (attempt $n)"; bad=1; break; }
    done
    [ $bad -eq 0 ] && { logj "$fk" size OK ""; return 0; }
    gsutil -m cp -r 237* "$BK/" >>"$LOG" 2>&1   # 재업로드 후 재검증
    n=$((n+1))
  done
  logj "$fk" size FAIL "크기 불일치 지속 — 로컬 보존"; return 1
}

# ---- filekey 트랜잭션 ----
process_fk(){ # $1=fk → 0 DONE / 1 FAILED / 2 ABORT(systemic)
  local fk="$1" a=1 rc exp reuse
  while [ $a -le $FK_ATTEMPT ]; do
    cd "$DLDIR"
    # 재사용 가드(첫 시도만): 이 filekey의 기대 zip이 이미 0바이트 아닌 채로 있으면 다운로드 스킵.
    #   이름패턴으로 매칭 → 다른 filekey 잔존본 오재사용 방지. 재시도(a>1)엔 항상 새로 받음.
    exp=$(fk_expect "$fk"); reuse=""
    [ "$a" -eq 1 ] && [ -n "$exp" ] && reuse=$(find 237* -name "*${exp}*.zip" -size +0c 2>/dev/null | head -1)
    if [ -n "$reuse" ]; then
      logj "$fk" reuse OK "기존 유효 zip 재사용(다운로드 스킵): $reuse"
    else
      rm -rf 237* 2>/dev/null
      download_one "$fk"; rc=$?
      [ $rc -eq 2 ] && return 2
      if [ $rc -ne 0 ]; then a=$((a+1)); continue; fi
    fi
    verify_integrity "$fk"; rc=$?
    if [ $rc -eq 3 ]; then logj "$fk" integrity REDOWNLOAD ""; a=$((a+1)); continue; fi
    [ $rc -ne 0 ] && { a=$((a+1)); continue; }
    upload_one "$fk"; rc=$?
    [ $rc -eq 2 ] && return 2
    [ $rc -ne 0 ] && { a=$((a+1)); continue; }
    verify_size "$fk"; rc=$?
    [ $rc -ne 0 ] && { a=$((a+1)); continue; }
    # 두 게이트 통과 → 삭제(파괴적, 여기서만)
    cd "$DLDIR"; rm -rf 237*
    logj "$fk" done OK "업로드·검증·삭제 완료"; return 0
  done
  return 1
}

# ================= main =================
preflight || { echo "preflight 실패 — 로그 확인: $LOG"; exit 1; }

# 큐 전체 예상시간(다운로드 기준) 사전 출력
tot=0; for FK in "$@"; do [ "$(state_get "$FK")" = "DONE" ] || tot=$((tot+$(est_min "$FK"))); done
echo "큐 ${#}개 | 예상 다운로드 합계 ~${tot}min (@${RATE_MBs}MB/s, 업로드 별도)"

consec=0
for FK in "$@"; do
  if [ "$(state_get "$FK")" = "DONE" ]; then logj "$FK" skip DONE "이미 완료"; continue; fi
  em=$(est_min "$FK"); gb=$(fk_gb "$FK")
  echo "[$(ts)] FK $FK (${gb}GB) 시작 — 예상 다운로드 ~${em}min"
  logj "$FK" start "" "est_dl_min=${em} gb=${gb}"
  t0=$(date +%s)
  process_fk "$FK"; rc=$?
  el=$(( $(date +%s)-t0 ))
  echo "[$(ts)] FK $FK 종료(rc=$rc) — 실제 $(hms $el) (예상 ~${em}min)"
  logj "$FK" elapsed "$rc" "actual_sec=${el} est_dl_min=${em}"
  if [ $rc -eq 0 ]; then state_set "$FK" DONE; consec=0
  elif [ $rc -eq 2 ]; then state_set "$FK" ABORT; echo "ABORT(systemic) at $FK — 로그: $LOG"; exit 2
  else
    state_set "$FK" FAILED; consec=$((consec+1))
    if [ $consec -ge $HALT_CONSEC ]; then
      logj - halt STOP "연속 실패 $consec회 — systemic 의심, 중단"
      echo "HALT: 연속 $consec 실패 — $LOG 확인 후 원인 조치"; exit 3
    fi
  fi
done
echo "완료. 상태: $STATE  로그: $LOG"

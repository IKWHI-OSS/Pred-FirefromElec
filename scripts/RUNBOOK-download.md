# 전량 다운로드 → GCS 적재 런북 (Mac, 한국 IP에서 실행)

> 실행 환경: **집 Mac 터미널** (한국 IP 필수). 코워크 샌드박스/클라우드 VM은 AI Hub가 502로 차단.
> 원칙: filekey 1개씩 받고 → 무결성·크기 검증 통과 후에만 로컬 삭제(파괴적 작업 게이트).

## 0. 사전 점검
```bash
which aihubshell gsutil unzip            # 셋 다 있어야 함
gcloud auth list                          # GCP 인증 상태
grep -n "ls .*part" /usr/local/bin/aihubshell  # 패치 적용 여부(한글 글롭/ sort -n) 확인
```
- ⚠ aihubshell 재설치했다면 patch 소실 → MEMORY 2026-06-15 절차로 재적용.

## 1. 버킷 준비 (비워뒀으면 재생성)
```bash
gsutil ls -b gs://constgx-aihub-237 || \
  gsutil mb -l asia-northeast3 -b on gs://constgx-aihub-237
```

## 2. 파일 트리 → filekey 목록 확보
```bash
aihubshell -mode l -datasetkey 71388 | tee ~/aihub_dl/tree_71388.txt
```
- 여기서 받을 filekey들을 골라낸다(datasetkey 자신/헤더 줄은 filekey 아님, 제외).
- 검증된 짝 예: TS_brailleBlock=504524, TL=504566, VS=504608, VL=504650.

## 3. 적재 루프 실행 (tmux 무인)
```bash
tmux new -s aihub
export AIHUB_KEY='발급키'
export GCS_BUCKET='gs://constgx-aihub-237'
bash ~/Documents/constgx/scripts/dl_to_gcs_loop.sh 504524 504566 504608 504650
# (Ctrl-b d 로 detach → 노트북 켜둔 채 자리 비워도 진행. tmux attach -t aihub 로 복귀)
```
- 속도 ~12MB/s throttle → 414GB 전량은 다운로드만 ~10h. 배치로 나눠 며칠 분산 가능.
- 각 filekey: 다운로드→병합→`unzip -t`→GCS 업로드→크기검증→로컬삭제. 실패는 보존+로그.

## 4. 진행/검증 확인
```bash
tail -f ~/aihub_dl/dl_loop_*.log            # 실시간
grep -c '^.*OK\[' ~/aihub_dl/dl_loop_*.log  # 성공 건수
grep 'FAIL' ~/aihub_dl/dl_loop_*.log        # 실패만
gsutil du -s gs://constgx-aihub-237         # 버킷 누적 용량
```

## 5. 마무리
- 자리 비울 땐 비용 0 유지가 목표지만, 적재본은 GCS에 있어야 학습 가능 → 버킷은 유지(저장비만, 저렴).
- 진짜 $0가 필요하면 학습 끝난 뒤 버킷 비우고, 재학습 시 재적재.
- API 키 노출 우려 있으면 적재 완료 후 재발급.

## 한계 / 다음 자동화
- 이 스크립트는 **수동 트리거 루프**다. 자기검증·재시도·진단은 최소(FAIL 보존+로그)만 들어감.
- 다음 단계 = `agents/` 오케스트레이터로 승격: 이 루프를 Tool로 감싸고 Verifier(존재/크기/무결성)+진단테이블+bounded 재시도+JSONL 로그를 붙인다. (구조: MEMORY 2026-06-14 자기검증 루프 골격)

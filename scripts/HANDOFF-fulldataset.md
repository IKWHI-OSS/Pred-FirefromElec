# 인계 프롬프트 — 전량 적재 (건설자재 전체, tmux 무인)

> Cursor의 Claude에 붙여넣어 실행. 504527 평가 통과로 러너 검증 완료 → 이제 남은 건설자재 전량을
> `aihub_ingest.sh`로 무인 적재. macOS(한국 IP) 터미널 필요. 정책: `scripts/INGEST-AGENT.md`.

---

[작업] 너는 macOS(한국 IP) 터미널 접근이 있는 실행 에이전트다. AI Hub 71388 건설자재 데이터를
아래 큐 전량을 **tmux 무인 세션**으로 적재하라. 러너는 검증 완료(504527 DONE)됐으니 그대로 신뢰하되,
안전 제약과 보고를 지켜라. 전부 `constgx/scripts/`에 있다(러너·정책·맵·.env). 별도 첨부 불필요.

## 0. 사전 (1회)
- `scripts/aihub_ingest.sh`(러너)·`scripts/INGEST-AGENT.md`(정책)를 1문단 요약.
- `.env`에 `KEY`/`BK` 있는지만 확인(값 노출 금지). preflight가 패치·버킷·디스크·KEY/BK를 자동 검증함.
- 디스크 여유 확인: 건설자재 최대 filekey 22GB → peak ~44GB 필요. (보조의 굴착기 40GB는 별도, §보조 참고)

## 1. 실행 (tmux 무인) — 남은 건설자재 전량
상태파일(`ingest_state.tsv`)이 DONE을 기억하므로 끊겨도 재실행하면 이어짐(멱등). 한 번에 큐 전체 전달:
```bash
tmux new -s aihub
bash ~/Documents/constgx/scripts/aihub_ingest.sh \
  504528 504529 504530 504531 504532 504533 504534 504535 504536 504537 504538 504539 504540 504541 504542 504543 \
  504567 504568 504569 504570 504571 504572 504573 504574 504575 504576 504577 504578 504579 504580 504581 504582 504583 504584 504585 \
  504608 504609 504610 504611 504612 504613 504614 504615 504616 504617 504618 504619 504620 504621 504622 504623 504624 504625 504626 504627 \
  504650 504651 504652 504653 504654 504655 504656 504657 504658 504659 504660 504661 504662 504663 504664 504665 504666 504667 504668 504669
# Ctrl-b d 로 detach. 복귀: tmux attach -t aihub
```
- 순서 = TS 잔여(16개) → TL 라벨(19개) → VS 검증이미지(20개) → VL 라벨(20개). TS/VS ~300GB, 라벨 ~120MB.
- 러너가 filekey마다 예상/실제 시간을 출력·로깅한다.

## 2. 모니터링 (detach 중 다른 탭에서)
```bash
tail -f ~/aihub_dl/ingest_$(date +%Y%m%d).jsonl       # 실시간 로그
grep -c '"step":"done","result":"OK"' ~/aihub_dl/ingest_*.jsonl   # 완료 건수
grep '"result":"FAIL\|ABORT"' ~/aihub_dl/ingest_*.jsonl          # 실패만
column -t ~/aihub_dl/ingest_state.tsv                  # filekey별 상태
gsutil du -s gs://constgx-aihub-237                    # 버킷 누적 용량
```

## 2b. 생존/사망 판별 (멈춘 것 같을 때 — "죽었나?" 확인)
> ⚠ 셸 작업엔 "커널" 개념이 없다(커널=주피터 노트북 전용). 적재에서 죽을 수 있는 건
> ①러너/자식 프로세스(aihub_ingest/aihubshell/gsutil) ②그걸 띄운 셸/세션(터미널 창 또는 tmux).
> **tmux로 감싸 실행했는지에 따라 체크가 갈린다:**

**공통 (tmux 사용 여부 무관) — 이것부터:**
```bash
# 1) 러너·자식 프로세스 떠 있나 (작업 생존의 진짜 신호)
pgrep -af 'aihub_ingest|aihubshell|gsutil' || echo "프로세스 없음(죽음/완료)"
# 2) 진행 중인가: 폴더 전체 크기가 커지는지 30초 간격 2회
#    (⚠ 237* 만 보면 안 됨! 다운로드 구간엔 데이터가 download.tar/.part 로 먼저 쌓이고
#     추출 후에야 237* 가 생긴다. 그래서 ~/aihub_dl 전체로 봐야 다운로드 단계도 잡힘.)
du -sh ~/aihub_dl 2>/dev/null; sleep 30; du -sh ~/aihub_dl 2>/dev/null
ls -lh ~/aihub_dl   # download.tar / *.part / 237* 중 무엇이 있는지로 현재 단계 파악
# 3) 네트워크 활동
nettop -P -l 1 2>/dev/null | grep -iE 'python|gsutil|curl' | head
# 4) 어디까지 DONE 했나
tail -3 ~/aihub_dl/ingest_state.tsv
```
**tmux로 실행한 경우에만 추가:**
```bash
tmux has-session -t aihub 2>/dev/null && echo "tmux ALIVE" || echo "tmux DEAD/미사용"
# (tmux를 안 썼으면 위 한 줄은 'DEAD/미사용'이 정상 — 무시. 프로세스(1번)로 판단.)
```
> tmux/nohup 없이 그냥 터미널에서 돌렸다면 **터미널/세션이 닫히면 작업도 죽는다**. 장시간 무인이면 tmux 권장.
**판정 규칙:**
- `tmux DEAD` 또는 프로세스 없음 → **죽음**. `ingest_state.tsv` 마지막 줄 확인 후 **같은 명령 재실행**(상태파일이 DONE 스킵 → 끊긴 지점부터 재개).
- 프로세스 ALIVE + (파일 크기 증가 OR 네트워크 활동) → **정상**(느린 것뿐, 기다림).
- 프로세스 ALIVE + 장시간 무진행(파일 정지 + 네트워크 0) → **행(hang) 의심** → 해당 filekey 로그 `~/aihub_dl/aihub_<fk>e.log` 확인 후 보고. (필요시 `tmux send-keys -t aihub C-c`로 중단 → 재실행)
- ⚠ **주의**: 큰 파일 다운로드 중에는 JSONL이 안 늘어난다(러너는 단계 완료 시에만 로깅). 그러니 다운로드 구간 생존 신호는 **로그 mtime이 아니라 파일 크기 증가·네트워크 활동**으로 본다.
> 알려진 한계: 러너에 단계별 타임아웃은 없음 → aihubshell/gsutil이 무한정 멈추면 외부에서 위 절차로 감지·중단해야 함.

## 3. 안전 제약 / HITL (반드시 준수)
- 삭제는 러너가 **무결성+크기 두 게이트 통과 후에만** 수행. 수동 삭제 금지.
- 러너가 **ABORT(rc=2)** 또는 **HALT(연속 실패 차단기)** 로 멈추면: 재시작하지 말고 로그와 함께 보고(HITL).
  (ABORT=해외IP/인증/디스크 같은 systemic 신호 → 환경 조치 필요.)
- **DIAGNOSIS 표에 없는 에러**: 추측 패치·임의 재시도 금지. 원문·발생 filekey·단계를 캡처해 보고(사용자가 진단표 보강).

## 4. 보조 데이터 (선택 — 메인 완료 후 별도 실행, 디스크 확인 후)
- 굴착기(40GB라 peak~80GB 필요): `aihub_ingest.sh 504544 504586 504628 504670`
- 입출입: `aihub_ingest.sh 504565 504607 504649 504691`
- 위치궤적(GPS, 전부 KB~MB): TS 504545-504564 / TL 504587-504606 / VS 504629-504648 / VL 504671-504690.

## 5. 완료 보고 형식 (채워서 사용자에게 전달)
```
[전량 적재 결과]
- 완료/전체: NN/79 DONE (FAILED: 목록 또는 없음)
- 총 소요: Xh Ym / 버킷 누적: gsutil du -s 출력
- 상태표: ingest_state.tsv 의 DONE/FAILED 요약
- 실패 filekey(있으면): filekey + 단계 + JSONL 원문 + DIAGNOSIS 해당여부
- ABORT/HALT 발생 여부 및 원인
- 이상/개선점: (없으면 "없음")
```
끝나면 [전량 적재 결과] 블록만 전달. 키·비밀값 마스킹.

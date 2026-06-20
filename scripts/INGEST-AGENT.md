# 단일 에이전트 — AI Hub 71388 적재 러너 (정책/설계)

> 역할: 결정적 다운로드→검증→업로드→검증→삭제 루프를 **무한루프 없이** 회복탄력적으로 반복.
> 멀티에이전트 아님. happy path는 LLM 개입 0. 에이전트는 *미진단 에러*에서만 판단/에스컬레이션.
> 실행 환경: **한국 IP Mac**. 러너: `scripts/aihub_ingest.sh`.

## 입출력 (산출물 분리)
- 입력(읽기전용): `knowledge/aihub-71388-filekey-map.md`(목록), `aihub-71388-label-schema.md`(스키마).
- 상태: `~/aihub_dl/ingest_state.tsv` (`filekey<TAB>STATUS`). 재실행 시 DONE은 스킵(멱등).
- 로그: `~/aihub_dl/ingest_YYYYmmdd.jsonl` (시도·단계·결과·에러 1줄/이벤트, 감사용).

## 제어 루프 (filekey 1개 = 1 트랜잭션)
```
preflight (1회) → for FK in 큐:
   DONE이면 skip
   attempt 1..MAX_ATTEMPT:
     download → integrity(unzip -t) → upload(gsutil) → size-match → rm 로컬
     각 단계 실패 = DIAGNOSIS 표로 (retriable?, corrective) 판정
   결과를 DONE/FAILED로 상태기록
   FAILED 연속 K회 → 전체 halt (systemic 의심, 사람 호출)
```

## 성공/실패 판정 원칙 (504527 eval 교훈 2026-06-15)
- **성공은 산출물(0바이트 아닌 zip)의 존재로 판정**한다. 로그 텍스트 스크래핑으로 성공/실패를 정하지 않음.
  (curl 진행률의 바이트수치 `502M` 가 `502` 정규식에 오매칭 → 멀쩡한 다운로드를 ABORT한 거짓양성 발생했음.)
- 에러 패턴(해외차단/HTTP502) 스캔은 **zip이 안 생겼을 때만** 수행. HTTP 상태 문맥에 고정(맨 숫자 금지).
- **기존 유효 zip 재사용 가드**: 재실행 시 그 filekey의 기대 zip이 이미 있으면(이름패턴 매칭) 다운로드 스킵→integrity부터. 오탐/중단 후 재다운로드 비용 0.

## 무한루프 방지 3원칙 (MEMORY 2026-06-15 멈춤신호 반영)
1. **모든 filekey는 종료한다**: 반드시 DONE/FAILED/SKIP 중 하나로 끝남.
2. **재시도는 유계(bounded) + 새 증거가 있을 때만**: 단계별 최대 N회. "근거 없는 동일 시도" 금지 —
   재시도 전에 corrective(재개/재패치/병합폴백)를 적용해 *상태를 바꾼* 뒤에만 다시 시도.
3. **연속 실패 차단기**: FAILED가 연속 K회면 즉시 halt. 1건 아닌 연속 실패는 systemic(인증·IP·디스크·패치) 신호.

## DIAGNOSIS 표 (에러신호 → 재시도? → 보정) — 과거 시행착오 시드
| # | 에러 신호 | 원인 | 재시도 | 보정(corrective) | 한도 |
|---|---|---|---|---|---|
| 1 | aihubshell 종료≠0 / 전송 끊김 | 네트워크·throttle | O | `aihubshell` 재호출(=`curl -C -` 이어받기) | 3 |
| 2 | 다운로드 후 **0바이트 zip / 새 zip 없음** | merge `printf %q` 한글버그 (패치 소실?) | O | 패치 확인→없으면 재적용; 그래도면 `merge_parts.sh` 폴백 후 재시도 | 2 |
| 3 | `unzip -t` 실패(손상/절단) | 다운로드 미완 | O | 재다운로드(resume) | 2 |
| 4 | "해외 다운로드 제한"/HTTP 502 (zip 미생성 시에만 검사) | IP가 한국 아님 | **X** | **ABORT** + 사람 호출(환경 문제) | 0 |
| 5 | `cp`/추출 중 디스크 full | peak≈2×배치 초과 | **X** | ABORT(공간 확보 필요). filekey 단위라 거의 없음 | 0 |
| 6 | gsutil 401/403/Anonymous | 인증 만료 | **X** | `gcloud auth login` 필요(HITL) | 0 |
| 7 | gsutil 5xx/broken pipe | 일시 장애 | O | 외부 재시도(gsutil 자체 -m 재시도 위에 한 겹) | 3 |
| 8 | 업로드 후 **크기 불일치** | 업로드 절단 | O | 재업로드 | 3 |

- 표에 없는 에러 = **미진단** → 재시도 말고 FAILED 기록 + halt(사람이 진단표에 추가). 이게 자기학습 루프.

## preflight (루프 전 1회, 통과 못하면 시작 안 함)
- `aihubshell` 존재 + **패치 적용 확인**(`grep 'ls .*part' /usr/local/bin/aihubshell` 에 한글글롭/`sort -n`). 미적용이면 0바이트 위험 → 재패치 후 진행.
- `gsutil` 인증 OK(`gcloud auth list` / `gsutil ls "$BK"`), 버킷 존재(없으면 생성).
- 디스크 여유 ≥ 최대 filekey×2 (peak 모델).
- `KEY`/`BK` 환경변수 세팅.

## HITL(사람 개입) 트리거
- DIAGNOSIS #4/#5/#6 (IP·디스크·인증) → 즉시 중단, 사용자 조치 필요.
- 연속 FAILED K회 차단기 작동 시.
- 미진단 에러 발생 시.

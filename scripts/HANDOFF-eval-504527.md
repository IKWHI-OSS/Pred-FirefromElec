# 인계 프롬프트 — 적재 워크플로 평가 실행 (filekey 504527, 1건)

> 이 파일을 Cursor의 Claude에 그대로 붙여넣어 실행시킨다. 목적: 단일 에이전트 적재 러너를
> filekey 1건(504527 circleManhole, ~10GB)으로 돌려 **워크플로 정합성·시간·에러대응을 평가**.

---

[작업] 너는 macOS(한국 IP) 터미널 접근이 있는 실행 에이전트다. AI Hub 71388 건설 데이터 적재
파이프라인을 **filekey 504527 1건만** 평가 실행하고, 아래 형식으로 보고하라. 전량 실행 금지.

## 0. 먼저 읽기 (실행 전 필수)
- `scripts/INGEST-AGENT.md` — 정책(재시도 한도, DIAGNOSIS 표, 무한루프 방지 3원칙, HITL 트리거).
- `scripts/aihub_ingest.sh` — 러너 본체.
- `scripts/aihub-71388-filekey-map.md` — 목록/사이클 / `scripts/aihub-71388-label-schema.md` — 스키마(참고).
  (러너·정책·맵·스키마·.env 전부 `constgx/scripts/` 한 폴더에 있음 — 별도 첨부 불필요.
   단 schema/filekey-map은 cowork 정본의 스냅샷이라 수정은 하지 말 것.)
읽고 "이 러너가 무엇을 어떤 게이트로 하는지" 1문단으로 먼저 요약하라.

## 1. 사전 확인 (preflight 신뢰)
- `grep 'ls .*part' /usr/local/bin/aihubshell` 로 병합 패치 적용 확인(없으면 0바이트 위험 → 보고하고 중단).
- `gsutil ls -b gs://constgx-aihub-237` 로 버킷/인증 확인.
- 디스크 여유 ≥ 24GB(10GB×2 peak) 확인.

## 2. 실행 (504527 1건)
- 키·버킷은 **`scripts/.env`에 정의됨**(`KEY`, `BK`). 러너가 시작 시 자동 로드 → export 불필요.
  (.env 없으면 `scripts/.env.example` 복사해 채울 것. .env는 .gitignore로 보호됨. 키 값은 보고에 노출 금지.)
```bash
bash ~/Documents/constgx/scripts/aihub_ingest.sh 504527
```
- 러너가 출력하는 예상시간(`~Nmin`)과 실제소요(`Xm Ys`)를 모두 캡처.

## 3. 안전 제약 (반드시 준수)
- 로컬 삭제(`rm -rf 237*`)는 러너가 **무결성+크기 두 게이트 통과 후에만** 수행한다. 수동으로 임의 삭제 금지.
- "해외 다운로드 제한"/502, gsutil 인증오류, 디스크 부족 → **재시도 말고 중단·보고**(HITL).
- **DIAGNOSIS 표에 없는 에러**가 나오면: 재시도하지 말고 그 에러 원문·발생단계를 그대로 캡처해 보고하라
  (사용자가 진단표를 키운다). 임의 추측 패치 금지.

## 4. 보고 형식 (이 블록을 채워서 출력 → 사용자가 복사해 평가에 사용)
```
[504527 평가 결과]
- preflight: (패치/버킷/디스크 각각 OK/실패)
- 예상 다운로드: ~Nmin / 실제 총소요: Xm Ys
- 단계별 결과: download / integrity(unzip -t) / upload / size-match / delete = 각 OK/실패
- GCS 확인: gsutil ls -l gs://constgx-aihub-237/.../circleManhole.zip 출력(바이트)
- 상태파일: ingest_state.tsv 에 504527 = DONE 인지
- JSONL 로그: ingest_YYYYMMDD.jsonl 의 504527 관련 줄 전체(원문)
- 에러/이상: (없으면 "없음". 있으면 원문 + 어느 단계 + DIAGNOSIS 표에 있었는지)
- 워크플로 평가 의견: (게이트·시간추정·로그 가독성에서 개선점 1~3개)
```

---
끝나면 위 [504527 평가 결과] 블록만 사용자에게 전달. 키·경로 비밀값은 마스킹.

# AI Hub 적재 현황 — 화재위험도 예측 프로젝트 (Pred-FirefromElec)

> 프로젝트 운영상태 문서. 정본 레포 = `Pred-FirefromElec`. (에이전트 메모리 아님 — cowork MEMORY에 두지 말 것)
> 갱신 2026-06-20.

## 적재 완료 (2026-06-20)
| dataSetSn | 이름 | filekey 범위 | 건수 | BK prefix | 결과 |
|---|---|---|---|---|---|
| 71918 | 배터리 열폭주 제어 멀티모달 | 565888–566470 | 583 | `${BK}/aihub-71918/` | 전량 적재, 0 실패 |
| 71921 | 산불 확산 위험 대응 추론 | 567303–567358 | 56 | `${BK}/aihub-71921/` | 전량 적재, 0 실패 |
| 외부 RAG 7종 | 물성·발화 + 가연환경·확산 | (직접 URL) | 7 | `${BK}/rag-corpus/` | 같은 드라이버로 적재 |

- 합계 639 filekey 무인 auto-run, 두 게이트(무결성 `unzip -t` → 로컬==GCS 크기) 통과 후 로컬 자동삭제.
- 적재 엔진 = orc `INGEST_AIHUB` 인스턴스(`agents/orc/ingest_driver.py`). 멱등 = `ingest_state.tsv` DONE skip.

## 재조회 금지 (비용)
- `aihubshell -mode l` 재조회 금지. filekey 맵은 `aihub-71918-filekey-map.md`·`aihub-71921-filekey-map.md`에 박제.
- 적재현황 재확인은 `gsutil ls`/상태표로(로그 스크래핑 금지).

## 후속 (보강 예정)
- 스키마 v1.1: 71918 이미지 원천 내부(해상도·채널), 71921 원천(TS/VS) 필드 — 적재 후 1 zip 열어 보강.
- git: orc/ 변경이 인프라 세션 미커밋 변경과 같은 워킹트리 → 커밋/머지 조율은 인프라 세션과 직접(`git push`는 게이트).

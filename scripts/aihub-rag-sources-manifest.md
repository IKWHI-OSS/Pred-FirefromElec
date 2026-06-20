# 외부 RAG 출처 매니페스트 — 물성·발화 + 가연환경·확산 (2026-06-20 검증)

> AI Hub에 없는 두 RAG 축의 외부 출처. **AI Hub filekey 아님 → 직접 URL 다운로드.**
> 7종 전부 실재·접근가능 웹검증 완료(2026-06-20). 적재 루프(무결성→업로드→크기검증)는 71918/71921과 동일 재사용.
> BK prefix: `${BK}/rag-corpus/properties/` (물성·발화), `${BK}/rag-corpus/environment/` (가연환경·확산).

## 표기
- 등급: 1순위 = 무료·공식배포·재배포부담 낮음(바로 적재). 2순위 = 유료/라이선스/저작권 확인 후.
- 다운로드 = 사용자 맥 또는 샌드박스(아래 §3 도메인 접근성 확인 필요).

## 1. 물성·발화 근거 → `rag-corpus/properties/`
| 출처 | 유형 | 직접 URL | 라이선스 | 등급 |
|---|---|---|---|---|
| KC 62619 (ESS 리튬이차전지 안전성·오용) | KS/KC 규격 PDF | https://www.kats.go.kr/cwsboard/board.do?mode=download&bid=155&cid=21073&filename=21073_201910251526580981.pdf | KATS 무료 공식배포 | 1순위 |
| ESS 셀 열폭주 유도 시험방법 | KS 규격 PDF | https://www.standard.go.kr/KSCI/ct/ptl/download.do?fileSn=141674 | standard.go.kr 무료 | 1순위 |
| KS C IEC 62619 상세(메타) | 규격 메타 | https://www.kssn.net/search/stddetail.do?itemNo=K001010135657 | kssn 유료 구매 | 2순위(라이선스 확인) |
| KS C IEC 62660-2 / KS R ISO 12405-3 | EV 셀 신뢰성·오용 규격 | https://www.kssn.net/search/stddetail.do?itemNo=K001010127832 (12405-3) | kssn 유료 구매 | 2순위(라이선스 확인) |
| LIB 벤트가스 가연한계 논문 | 학술 PDF | https://pubs.acs.org/doi/10.1021/acsomega.0c03713 | ACS Omega 골드 오픈액세스 | 1순위(OA) |

## 2. 가연환경·확산 근거 → `rag-corpus/environment/`
| 출처 | 유형 | 직접 URL | 라이선스 | 등급 |
|---|---|---|---|---|
| 소방청 리튬이온 화재예방대책 | 정책 PDF | https://www.isafe.go.kr/DATA/bbs/86/20250825032929346.pdf | 공공 무료 | 1순위 |
| KFPA 리튬이온 화재 위험성·안전대책 | 해설 HTML | https://www.kfpa.or.kr/webzine/202408/disaster1.html | 무료 웹진 | 1순위 |
| KFPA 전기차 충전시설 안전기준 | 해설 HTML | https://www.kfpa.or.kr/webzine/202304/disaster1.html | 무료 웹진 | 1순위 |
| LiFePO4 열폭주 가스 분산·폭발 시뮬 | 학술 | https://pubs.acs.org/doi/10.1021/acsomega.3c08709 | ACS Omega 오픈액세스 | 1순위(OA) |

## 3. 적재 전 확인사항
- **도메인 접근성:** 샌드박스 프록시가 kats/standard/isafe/kfpa/pubs.acs를 허용하는지 미확인 → 차단 시 사용자 맥에서 다운로드(AI Hub와 동일 패턴). 다운로드 후 업로드만 샌드박스/맥 어디서든.
- **kssn 2건:** 본문 PDF는 유료 구매·라이선스 → 무단 RAG 색인 금지. KC 62619·열폭주 시험방법(무료)으로 물성 축 1차 충당 가능하므로 kssn은 보류 가능.
- **논문:** 골드 OA(ACS Omega)만 본문 적재. ScienceDirect/Nature 계열은 인용·요약만(저작권).
- HTML(KFPA)은 PDF 변환 또는 본문 텍스트 추출 후 색인.

## 4. 적재 루프 (71918/71921과 공유)
```
preflight(BK·gsutil 인증) 1회 →
for SRC in 1순위 큐:
  download(직접 URL) → 무결성(PDF/HTML 0바이트 아님·열림) → gsutil 업로드(prefix별) → 크기검증 → DONE 기록
```
- 성공 판정 = 0바이트 아닌 파일 존재(로그 아님).
- orc/ 인스턴스로 장착 시: `handlers_ingest.py`의 다운로드 액션을 URL 직접다운로드로 분기(aihubshell 대신 curl).

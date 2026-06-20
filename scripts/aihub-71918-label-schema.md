# AI Hub 71918 라벨/구조 스키마 — 배터리 열폭주 멀티모달 (v1, 실측 확정)

> 작성 2026-06-20. **v1 실측**: TL 라벨(566083)·TS 센서(565889) zip 실제 inspect.
> 형식 본보기: `aihub-71388-label-schema.md`. 맵: `aihub-71918-filekey-map.md`.

## 0. 데이터셋 골격 (실측)
- dataSetSn **71918**, ~13.12GB. 폴더 루트 `20.배터리_열폭주_제어_멀티모달_데이터`.
- 4계층: Training(**TS** 원천 / **TL** 라벨) + Validation(**VS** 원천 / **VL** 라벨) + Other(메타).
- **실험 단위 = 1 run** (예 `각형_280_100_가열_20250818_20250818001`). run 1개당 3모달:
  - **센서 원천** `TS_센서_*.zip` → 안에 `sensor_data_<runid>_<dataid>.json` 다수(시계열, 1 timestep=1 json).
  - **이미지 원천** `TS_이미지_*.zip` → 열화상 PNG(`<날짜>_<시각>_<n>.png`). 라벨의 `imgdata_id`로 1:1.
  - **라벨** `TL_센서_*.zip` → `labeling_data_<runid>_<dataid>.json` 다수(센서값+단계라벨+이상이벤트).
- run명: `<TS|TL|VS|VL>_<센서|이미지>_<셀형태(각형/원통형)>_<용량>_<셀수>_<시험(가열/과충전)>_<날짜>_<runid>.zip`.

## 1. 센서 원천 JSON (TS/VS_센서) — 실측
`sensor_data_<runid>_<dataid>.json`, 1 파일 = 1 timestep. 필드:
```
data_id, test_day(YYMMDD), test_time(HHMMSSmmm),
meas_v(전압 V), meas_a(전류 A), meas_t1, meas_t2(온도 ℃), meas_p(압력),
meas_ch4, meas_co, meas_co2, meas_hcn, meas_hcl, meas_hf, meas_n2o, meas_no, meas_no2, meas_so2 (가스 10종),
indu_t, indu_t.1(유도온도), atmp_t(대기온도), thermal_t(열화상 대표온도)
```
- 한 run zip 안에 수천 timestep(예 565889 = 6880건). 라벨과 `data_id`로 1:1 매칭.

## 2. 라벨 JSON (TL/VL_센서) — 실측 ★학습 핵심
`labeling_data_<runid>_<dataid>.json`, 1 파일 = 1 timestep. **§1 센서필드 전부 포함 + 아래 추가**:
```
imgdata_id      : "20250818_105003_1.png"   ← 열화상 이미지 파일명(이미지 원천과 매칭 키)
tr_stage        : 1~6                        ← ★열폭주 단계 라벨(메인 타깃)
abn_temprise, abn_presrise, abn_vdrop, abn_v0, abn_vdddrop, abn_temprise2, abn_maxtemp : "Y"/"N"  ← 이상이벤트 플래그
bat_class       : 정수(셀형태 코드)
bat_cc          : 정격용량(예 280.0)
soc_status      : SOC 상태 코드
tr_method       : 열폭주 유도법 코드(1=가열 등)
meas_t1_plus_t2 : 파생(t1+t2)
```
- **매칭 규칙**: `data_id`(센서↔라벨), `imgdata_id`(라벨↔열화상 이미지). 셋이 한 timestep으로 묶임.
- **타깃**: `tr_stage`(다단계 분류 1~6) + 이상이벤트(`abn_*` 멀티라벨). 입력 = 센서 시계열 + 열화상.

## 3. 적재 무결성 관점 (이 세션)
- 적재는 zip 단위 1:1(다운로드→`unzip -t`→업로드→크기검증→삭제). 내부 JSON 파싱은 학습 단계 몫.
- 소형 다수(583 zip, 평균 ~23MB). 라벨/센서 zip은 수십~수백 KB, 이미지 zip이 용량 대부분.

## 4. 후속 학습 매핑(설계 메모, 적재 후)
- Dataset `__getitem__` → (열화상 텐서 + 센서 시계열 윈도, target={tr_stage, abn_*}).
- 센서↔라벨↔이미지 조인키 = (runid, data_id, imgdata_id). EXIF 이슈는 PNG라 71388 대비 없음(확인 권장).
- tr_stage 클래스 불균형(초기단계 다수) 예상 → 가중/리샘플 고려.

---
_상태: v1 실측 확정(라벨·센서). 이미지 원천 내부(해상도·채널)는 적재 후 1zip 열어 보강 예정._

# AI Hub 71921 라벨/구조 스키마 — 산불 확산 위험 대응방안 추론 (v1, 실측 확정)

> 작성 2026-06-20. **v1 실측**: VL 라벨(567350) zip 실제 inspect.
> 역할: RAG(산불 확산 근거). 형식 본보기: `aihub-71388-label-schema.md`. 맵: `aihub-71921-filekey-map.md`.

## 0. 데이터셋 골격 (실측)
- dataSetSn **71921**, ~1.86GB. 폴더 루트 `38.산불_확산_위험_대응방안_추론_데이터`.
- 4계층: Training(**TS** 원천 / **TL** 라벨) + Validation(**VS** 원천 / **VL** 라벨).
- 분할: **산불 규모(대형/중형/소형) × 도(강원/경기/경상/전라/충청)**, 계층당 14조합.
- 파일 단위: `<코드>_T_P####_T###.json` (예 `AS20240324_T_P0001_T001.json`). 1 파일 = 1 질의-추론 케이스.
- **라벨(TL/VL)이 자연어 Q&A + 추론트리 본체**(용량 큼). 원천(TS/VS)은 케이스 입력/시나리오.

## 1. 라벨 JSON 구조 (TL/VL) — 실측 ★RAG 본체
최상위 `labelling_data_info`:
```
labelling_data_info:
  query:
    query_text     : 자연어 질문(예 "지형·기상·주민 분포를 종합한 전체 구조 작업 완료 시간은?")
    query_purpose  : 질의 목적(예 "현황파악")
    query_subject  : 질의 주제(예 "대피전략")
    query_type     : "composite" | (단일/복합 유형)
  tree_of_thought:                      ← 다단계 추론 트리(ToT)
    level_0_input:
      L0_node_id   : "ROOT"
      L0_thought   : 추론 주제 요약
      L0_context:                        ← 케이스 정량 컨텍스트(확산 근거 핵심)
        weather_conditions   : {wind_speed, wind_direction, humidity_percent, temperature,
                                surface_temperature, drought_days, visibility}
        terrain_conditions   : {elevation, slope, slope_aspect, curvature,
                                topographic_position_index, terrain_complexity, hydrological_features}
        fuel_conditions      : {fuel_type(예 활엽수림), fuel_moisture, fuel_density,
                                fuel_average_age, surface_fuel_depth, canopy_height, canopy_coverage}
        Infra_Social         : {population, vulnerable, fire_station_distance,
                                road_accessibility, Important_Infra_distance, shelter}
        occurrence_status    : {fire_duration, drought_duration_days, wildfire_duration_time,
                                flame_length, fire_intensity, fire_length, ...}
    level_1.. (하위 추론 노드/근거/결론 — 레벨별 thought·context 전개)
```
- 1 case JSON ~40KB. zip(예 VL_소형_경기도)당 200여 case.
- **RAG 색인 대상**: `query_text`(질문) + `tree_of_thought`(추론·근거) + `L0_context`(정량 조건).
  → 확산 위험/대응 질의에 대한 근거·추론 체인 검색에 사용.

## 2. 원천 JSON (TS/VS) — 케이스 입력
- 라벨과 동일 case 키(`<코드>_T_P####_T###`)로 짝. 시나리오/컨텍스트 입력(라벨의 context 원본).
- (정밀 필드는 적재 후 1 zip 열어 보강. RAG 본체는 라벨이므로 우선순위 낮음.)

## 3. 적재 무결성 관점 (이 세션)
- zip 단위 1:1 적재(다운로드→`unzip -t`→업로드→크기검증→삭제). 텍스트 전용이라 소형(최대 469MB).
- BK prefix `${BK}/aihub-71921/`.

## 4. RAG 매핑(설계 메모, 적재 후)
- 청크 단위 = 1 case의 (query + ToT 추론 + 정량 context). 메타 = {규모, 도, query_subject, fuel_type}.
- 71918(물성·발화 신호)과 상보: 71921은 **확산·대응 근거** 축. 외부출처(매니페스트)와 합쳐 RAG 코퍼스 구성.

---
_상태: v1 실측 확정(라벨 ToT Q&A). 원천(TS/VS) 내부 필드는 적재 후 보강 예정._

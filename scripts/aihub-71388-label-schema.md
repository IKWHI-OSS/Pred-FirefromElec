# AI Hub 71388 라벨 어노테이션 스키마 — 학습 노트 (v1, 실측 확정)

> 작성 2026-06-15. **v1 승격(2026-06-15): brailleBlock TL/TS zip 실제 inspect로 확정.**
> 300개 JSON 샘플 통계 + 이미지 대조 완료. 아래 §0이 확정 사실, §2~§4는 v0 prior(이력 보존).

## 0. 실측 확정 스키마 (v1 — brailleBlock 기준, 300 샘플)

- **JSON 단위**: 이미지 1장당 JSON 1개 (TL 3654 = TS 3654, 1:1). zip 엔트리는 **선행 슬래시** 포함(`/brailleBlock_1809b.json`).
- **파일명 대응**: `brailleBlock_<번호><a|b|c>.json` ↔ 동일 stem `.jpg`. 확장자만 교체하면 매칭.
- **최상위**: `{"images":[{filename,width,height}], "annotations":[...]}` (300/300 동일).
- **지오메트리**: ❗**bbox 아님 — 항상 `polygon`** (flat `[x1,y1,x2,y2,...]`, 짝수 길이). bbox/box/points/segmentation 필드 전무.
  → torchvision detection용 **xyxy 박스는 polygon에서 유도**: `x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys)` (xs=poly[0::2], ys=poly[1::2]).
- **클래스**: 필드명 `class`, 값 문자열 `"brailleBlock"` 단일 (300/300). class_id 없음 → 매핑 `{brailleBlock:1}`, bg=0.
- **좌표계**: 절대픽셀. **EXIF 미적용(stored) 공간** — 일부 이미지 EXIF orientation=6이나 JSON `width/height`가 stored JPEG 크기와 일치(3건 검증). → ⚠ **이미지 로딩 시 `ImageOps.exif_transpose()` 호출 금지**(부르면 dims 회전돼 polygon 좌표 어긋남). `Image.open` 기본(EXIF 무시)이 라벨과 일치.
- **엣지케이스(반드시 처리)**: ①annotation 0개 파일 존재(예 `brailleBlock_3973b.json`, 샘플 1/300) → 빈 target 또는 스킵. ②파일당 annotation 2개 케이스 존재(3/300). ③polygon 좌표가 W/H 경계 밖(22/300) → bbox 유도 후 `[0,W]/[0,H]` 클리핑 + degenerate(zero w/h) 박스 가드(FasterRCNN가 거부).

---

## (이하 v0 prior — 이력 보존)

> 아래는 검증 전 강한 prior. §0이 실측으로 일부를 정정함(특히 bbox→polygon).

## 1. 데이터셋 골격 (확인된 사실)

- datasetkey **71388**, 약 414GB, 대부분 원천(이미지).
- 4계층 구조: Training(**TS** 원천 / **TL** 라벨) + Validation(**VS** 원천 / **VL** 라벨).
- 자재 클래스별로 zip이 쪼개짐(brailleBlock=점자블록, brick, scaffold, pvcPipe … 약 20종).
- 리허설 짝(로컬 확보): `TS_건설자재_brailleBlock.zip`(15GB 이미지, filekey 504524),
  `TL_건설자재_brailleBlock.zip`(4MB 라벨, filekey 504566).
  cf. 검증셋 VS=504608(4GB), VL=504650(1MB).

## 2. 예상 어노테이션 스키마 (AI Hub OD 공통 패턴 — **검증 필요**)

AI Hub 객체탐지 라벨은 대개 **이미지 1장당 JSON 1개**, 또는 자재별 통합 JSON이다. 전형적 필드:

```jsonc
{
  "image": {                     // 또는 "images", 최상위 메타
    "filename": "brailleBlock_0001.jpg",
    "width": 1920, "height": 1080,
    "date": "...", "location": "..."   // 부가 메타(현장·촬영정보)
  },
  "annotations": [               // 또는 "objects" / "shapes" / "label"
    {
      "class": "brailleBlock",   // 또는 "category"/"label"/"object_class" + class_id
      "box": [x, y, w, h]        // ★ 포맷 미확정: [x,y,w,h](COCO) vs [x1,y1,x2,y2](VOC)
      // 혹은 "points":[[x1,y1],[x2,y2]] / "bbox":{...}
    }
  ]
}
```

**가장 흔한 두 변형:**
- (A) COCO 유사: `bbox: [x, y, width, height]` (좌상단 기준).
- (B) VOC 유사: `[xmin, ymin, xmax, ymax]` (또는 폴리곤 points).

→ torchvision detection은 **[x1,y1,x2,y2] (xyxy, 절대픽셀)** 를 요구하므로, 어느 포맷이든 **xyxy로 변환**하는 한 줄이 Dataset 핵심.

## 3. 다음 세션 검증 명령 (이걸로 §2를 사실로 확정)

```
LBL=$(find ~/aihub_dl/237* -name 'TL_건설자재_brailleBlock.zip' | head -1)
IMG=$(find ~/aihub_dl/237* -name 'TS_건설자재_brailleBlock.zip' | head -1)
unzip -l "$LBL" | head -20
unzip -Z1 "$LBL" | grep -ci '\.json$'
unzip -Z1 "$IMG" | grep -ciE '\.(jpg|jpeg|png)$'
J=$(unzip -Z1 "$LBL" | grep -i '\.json$' | head -1)
unzip -p "$LBL" "$J" | python3 -m json.tool | head -90
unzip -Z1 "$IMG" | head -8
```

**확정해야 할 5가지:**
1. JSON 단위 = 이미지당 1개인가, 자재당 통합인가?
2. bbox 포맷 = xywh(COCO) vs xyxy(VOC) vs polygon points?
3. 좌표 = 절대픽셀 vs 정규화(0~1)?
4. 클래스 필드명·표기(문자열 vs id), 한 이미지에 다중 클래스 여부.
5. **이미지↔라벨 파일명 대응 규칙**(예 `brailleBlock_0001.jpg` ↔ `brailleBlock_0001.json`).

## 4. torch Dataset 매핑 설계 (스키마 확정 후 구현)

- `__getitem__` → `(image_tensor, target)` 반환.
  `target = {"boxes": FloatTensor[N,4] (xyxy 절대픽셀), "labels": Int64Tensor[N], "image_id": ...}`.
- **클래스 매핑**: 문자열 class → 정수 index. brailleBlock 단일이면 `{brailleBlock:1}`, background=0 (torchvision 관례).
  리허설은 단일 자재라 클래스 1개 + 배경이면 충분. 전량 학습 시 20종 매핑표로 확장.
- **이미지 로딩**: 15GB zip을 ① 통째 압축해제(디스크 +15GB) vs ② `zipfile`로 스트리밍 읽기.
  리허설은 소수 샘플만 쓰므로 **zip 스트리밍**이 디스크 절약(권장).
- **collate_fn**: 객체 수가 가변이라 기본 collate 불가 → `lambda b: tuple(zip(*b))` (torchvision detection 표준).
- **모델**: `torchvision.models.detection.fasterrcnn_resnet50_fpn(weights=...)` 헤드만 클래스수 교체.
  리허설 목표 = 배치 1개 forward/backward에서 loss dict 정상(NaN 없음)·역전파 동작 확인(1 epoch, CPU 소수 샘플).

## 5. 리허설 성공 기준 (재확인)

subset은 *대체*가 아니라 *전량 본학습 전 리허설*. 다음을 통과하면 파이프라인 검증 완료:
- DataLoader가 배치 1개를 정상 형태로 반환(이미지 리스트 + 타겟 dict 리스트).
- bbox 시각화 1장에서 박스가 객체에 맞게 그려짐(라벨매핑·좌표변환 검증).
- FasterRCNN 1 epoch(소수 샘플) loss 유한·감소 추세, 역전파 에러 없음.

---
_상태: v0 prior. 다음 세션에서 §3 실행 → §2·§4를 실제값으로 갱신하고 v1로 승격._
_출처: 데이터셋 개요 aihub.or.kr dataSetSn=71388. 스키마 세부는 실제 JSON 대조 필요(아직 미확정)._

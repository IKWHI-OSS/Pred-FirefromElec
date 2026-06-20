# AI Hub 71388 — 전체 filekey 맵 (박제, 재조회 금지)

> 확정 2026-06-15. `aihubshell -mode l -datasetkey 71388` 1회 실측 결과. **다시 트리 조회하지 말 것.**
> 원본 트리 덤프: `~/aihub_dl/tree_71388.txt`. aihubshell version 25.09.19 v0.6.
> 구조: Training(TS 원천/TL 라벨) + Validation(VS 원천/VL 라벨). 총 ~414GB.

## 표기
- ✅ = 로컬 다운로드+`unzip -t` 검증 완료. ☁️ = GCS 적재 완료. (현재 GCS는 비어있음 $0)
- 메인 작업 = **건설자재 객체탐지**(TS+TL 학습, VS+VL 검증). 굴착기/입출입/위치궤적은 보조.

## 1. 건설자재 — Training 원천 TS (메인, 이미지 ~300GB)
| filekey | 자재 | 크기 | 상태 |
|---|---|---|---|
| 504524 | brailleBlock | 15GB | ✅☁️ 로컬검증+GCS적재(2026-06-15, 16243498628 bytes 일치) |
| 504525 | brick | 14GB | ✅☁️ GCS적재(2026-06-15) |
| 504526 | castIronCover | 22GB | ✅☁️ GCS적재(2026-06-15) |
| 504527 | circleManhole | 10GB | ✅☁️ GCS적재(2026-06-16, 11263931648 bytes) |
| 504528 | collectorWell | 17GB | ← 다음 |
| 504529 | curbStone | 16GB | |
| 504530 | deckPlate | 12GB | |
| 504531 | doubleWallPipe | 13GB | |
| 504532 | floorPost | 15GB | |
| 504533 | flumeTube | 13GB | |
| 504534 | forms | 13GB | |
| 504535 | pvcPipe | 22GB | |
| 504536 | rubberCone | 15GB | |
| 504537 | scaffold | 14GB | |
| 504538 | squareManhole | 9GB | |
| 504539 | steelBar | 6GB | |
| 504540 | steelGrating | 19GB | |
| 504541 | trenchCover | 22GB | |
| 504542 | waterBarrier | 20GB | |
| 504543 | wideflangeShapes | 13GB | |

## 2. 건설자재 — Training 라벨 TL (~100MB 합계, filekey 504566~504585)
brailleBlock=504566 ✅☁️(4277559), brick=504567, castIronCover=504568, circleManhole=504569, collectorWell=504570,
curbStone=504571, deckPlate=504572, doubleWallPipe=504573, floorPost=504574, flumeTube=504575,
forms=504576, pvcPipe=504577, rubberCone=504578, scaffold=504579, squareManhole=504580,
steelBar=504581, steelGrating=504582, trenchCover=504583, waterBarrier=504584, wideflangeShapes=504585

## 3. 건설자재 — Validation 원천 VS (~61GB, filekey 504608~504627)
brailleBlock=504608(4GB), brick=504609(3GB), castIronCover=504610(4GB), circleManhole=504611(2GB),
collectorWell=504612(3GB), curbStone=504613(3GB), deckPlate=504614(2GB), doubleWallPipe=504615(3GB),
floorPost=504616(3GB), flumeTube=504617(3GB), forms=504618(3GB), pvcPipe=504619(3GB),
rubberCone=504620(3GB), scaffold=504621(4GB), squareManhole=504622(1GB), steelBar=504623(5GB),
steelGrating=504624(4GB), trenchCover=504625(4GB), waterBarrier=504626(2GB), wideflangeShapes=504627(2GB)

## 4. 건설자재 — Validation 라벨 VL (~20MB, filekey 504650~504669)
brailleBlock=504650, brick=504651, castIronCover=504652, circleManhole=504653, collectorWell=504654,
curbStone=504655, deckPlate=504656, doubleWallPipe=504657, floorPost=504658, flumeTube=504659,
forms=504660, pvcPipe=504661, rubberCone=504662, scaffold=504663, squareManhole=504664,
steelBar=504665, steelGrating=504666, trenchCover=504667, waterBarrier=504668, wideflangeShapes=504669

## 5. 보조 데이터
- **굴착기**: TS=504544(40GB), TL=504586(26MB), VS=504628(6GB), VL=504670(3MB)
- **입출입 이미지**: TS=504565(5GB), TL=504607(2MB), VS=504649(1GB), VL=504691(326KB)
- **위치궤적(GPS)**: 전부 KB~MB. TS=504545~504564, TL=504587~504606, VS=504629~504648, VL=504671~504690.

## 6. 다운로드 운영 (박제된 수동 프롬프트)
사용자 표준 수동 다운로드 호출 (filekey만 교체):
```bash
cd ~/aihub_dl && rm -rf 237*
aihubshell -mode d -datasetkey 71388 -aihubapikey "$KEY" -filekey <FK> 2>&1 | tee ~/aihub_<FK>e.log
```
⚠ **`rm -rf 237*`는 직전 다운로드본을 삭제**한다 → 다음 filekey 받기 전 반드시 GCS 업로드 완료할 것.
브라유블록(504524)은 현재 로컬 유일본(GCS 미적재) → 덮어쓰기 전 업로드 필수.
- 자동화 대안(업로드·검증·삭제 게이트 포함): `constgx/scripts/dl_to_gcs_loop.sh` (rm -rf 불필요).

### 박제된 1사이클 (무결성→업로드→크기검증→삭제→다음 다운로드) — rm -rf 워크플로용
```bash
BK=gs://constgx-aihub-237
NEXT=<다음FK>          # 이번 사이클 끝나고 받을 filekey
cd ~/aihub_dl
# ① 업로드 전 로컬 무결성 (깨졌으면 업로드/삭제 금지)
for z in $(find 237* -name '*.zip'); do
  unzip -t "$z" >/dev/null 2>&1 && echo "INTEGRITY OK  $z" || echo "CORRUPT  $z ← 중단"
done
# ② 버킷 보장 + 237* 통째 업로드(구조 보존)
gsutil ls -b "$BK" >/dev/null 2>&1 || gsutil mb -l asia-northeast3 -b on "$BK"
gsutil -m cp -r 237* "$BK/"
# ③ 삭제 전 크기 일치 (로컬 == GCS)
for f in $(find 237* -name '*.zip'); do
  L=$(stat -f%z "$f"); R=$(gsutil stat "$BK/$f" 2>/dev/null | awk -F': *' '/Content-Length/{print $2}')
  [ "$L" = "$R" ] && echo "SIZE OK  $f ($L)" || echo "MISMATCH  $f  L=$L R=$R"
done
# ④ ①③ 전부 OK일 때만: 직전본 삭제 + 다음 filekey 다운로드 (이미 GCS에 있으니 rm 안전)
cd ~/aihub_dl && rm -rf 237*
aihubshell -mode d -datasetkey 71388 -aihubapikey "$KEY" -filekey "$NEXT" 2>&1 | tee ~/aihub_${NEXT}e.log
```

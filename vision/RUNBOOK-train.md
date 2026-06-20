# RUNBOOK — 건설자재 20종 본학습 (GCP GPU VM, 서울)

> 데이터 적재 완료(`gs://constgx-aihub-237`, 362GiB) + 리허설 통과 상태에서 시작.
> 실행 방식 = **클라우드 GPU(서울) + GCS 스트리밍**. 데이터를 VM에 통째로 내려받지 않고
> 학습 루프가 마운트된 버킷의 zip 에서 배치 단위로 직접 읽음(egress 0, 경량 VM).

## 0. 사전조건 (로컬 / Cloud Shell)
- `gcloud auth login` + `gcloud config set project <PROJECT_ID>`
- `gcloud services enable compute.googleapis.com`
- 결제계정 연결(무료체험은 GPU 할당량 0일 수 있음).

## 1. GPU 할당량 확인 → VM 생성
```bash
cd vision
bash provision_vm.sh quota      # 서울 GPU limit > 0 확인. 0이면 Quotas 에서 상향 요청.
bash provision_vm.sh create     # n1-standard-8 + T4 1장 @ asia-northeast3-b
# (저렴하게: SPOT=1 bash provision_vm.sh create  — 중단 가능하나 train.py resume 로 복구)
bash provision_vm.sh push       # 이 vision/ 폴더를 VM 으로 복사
bash provision_vm.sh ssh        # VM 접속
```
> GPU 옵션은 환경변수로 조정: `GPU_TYPE=nvidia-l4 ZONE=asia-northeast3-a bash provision_vm.sh create`

## 2. VM 셋업 (VM 안에서)
```bash
bash ~/vision/setup_vm.sh       # CUDA torch + torchmetrics + gcsfuse 설치, 버킷을 ~/gcs 에 마운트
```
- `nvidia-smi`, `torch.cuda.is_available()=True`, 사전학습 weights(`weights=DEFAULT`) 다운로드 OK 를 자동 확인.
- 버킷이 읽기전용으로 `~/gcs` 에 마운트됨.

## 3. 데이터 인덱스 빌드 (VM 안에서)
```bash
cd ~/vision
python build_index.py --mount ~/gcs --split train --out train_index.jsonl
python build_index.py --mount ~/gcs --split val   --out val_index.jsonl
```
- 20개 클래스의 (이미지 zip ↔ 라벨 zip) 페어를 stem 으로 매칭해 jsonl 생성.
- 학습/평가는 이 인덱스만 읽으므로 매번 zip 재스캔 안 함.

## 4. 학습 (weights=DEFAULT, CUDA + AMP)
```bash
python train.py --train-index train_index.jsonl \
    --epochs 12 --batch-size 4 --workers 8 \
    --out runs/constgx \
    --gcs-out gs://constgx-aihub-237/runs        # 체크포인트를 GCS 에도 백업(VM 삭제 대비)
# 스팟 VM 중단 후 재개:  --resume runs/constgx/last.pth 추가
```
- 리허설과 다른 점: 사전학습 가중치 사용, 21클래스 헤드, 기본 해상도(800/1333), GPU/AMP, num_workers 스트리밍.
- 에폭마다 `last.pth` + `epoch_NNN.pth` 저장(+ GCS 백업).
- dataloader 가 병목이면(스트리밍 랜덤리드) `--workers` 상향 또는 §부록 WebDataset 재패키징 검토.

## 5. mAP 평가
```bash
python eval_map.py --val-index val_index.jsonl --ckpt runs/constgx/last.pth \
    --batch-size 4 --workers 8
# 빠른 점검:  --limit 500
```
- COCO 방식 mAP@[.5:.95], mAP@.5/.75, 클래스별 AP 출력.

## 6. 예측 데모
```bash
python predict_demo.py --val-index val_index.jsonl --ckpt runs/constgx/last.pth \
    --n 8 --score-thresh 0.5 --out demo_out
# 결과 PNG 를 로컬로 회수:
#   (로컬) gcloud compute scp --recurse constgx-train:~/vision/demo_out ./ --zone asia-northeast3-b
```

## 7. 학습 후 정리 (비용통제 — 필수)
1. 체크포인트/결과가 GCS(`gs://.../runs`) 또는 로컬에 안전히 백업됐는지 확인.
2. **VM 삭제**(과금 중지):
   ```bash
   bash provision_vm.sh delete
   ```
3. 원본 대용량(362GiB)은 당장 안 쓰면 비용절감:
   - Archive 스토리지로 강등:  `gsutil rewrite -s archive gs://constgx-aihub-237/**`  (또는 버킷 라이프사이클 규칙)
   - 또는 학습 끝나고 재현 불필요하면 삭제. weights·결과만 보존.
4. 예산 알림: GCP 콘솔 Billing > Budgets & alerts 에서 월 예산/알림 설정 권장.

## 주의 — 샌드박스 ≠ GPU VM
- 리허설의 `torch==2.2.2` CPU 핀 / `numpy<2` / `weights=None` / `min_size` 축소는 **코워크 샌드박스 제약**(디스크 4.4GB·CPU·프록시 차단) 때문이었음.
- GPU VM 에선 **CUDA torch + weights=DEFAULT + 기본 해상도**. 샌드박스 제약을 VM 으로 가져오지 말 것.

## 파일 구성
| 파일 | 역할 |
|---|---|
| `provision_vm.sh` | VM 생성/접속/코드복사/삭제 (gcloud) |
| `setup_vm.sh` | VM 내부: CUDA torch + gcsfuse + 버킷 마운트 |
| `classes.py` | 20종 클래스 매핑(1..20, bg=0, num_classes=21) |
| `build_index.py` | 마운트된 20개 zip → train/val index.jsonl |
| `dataset_full.py` | 20클래스 Dataset(스키마 v1 유지, fork-safe zip 스트리밍) |
| `train.py` | 본학습(weights=DEFAULT, AMP, 체크포인트/resume) |
| `eval_map.py` | 검증셋 mAP(torchmetrics) |
| `predict_demo.py` | 예측 bbox 시각화 |
| `dataset.py`, `rehearse.py` | (리허설 원본 — 검증된 단일클래스 파이프라인, 보존) |

## 부록 — dataloader 병목 시: WebDataset 재패키징
gcsfuse + zipfile 랜덤리드가 GPU 를 못 먹이면, 1회 전처리로 `.tar` 샤드(WebDataset)로 재패키징해
순차 스트리밍하면 처리량이 크게 오름. 같은 버킷·리전에 쓰면 egress 0 유지. (다음 개선 후보)

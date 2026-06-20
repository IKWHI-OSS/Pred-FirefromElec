"""건설자재 20종 클래스 매핑 (AI Hub 71388).

filekey 맵(knowledge/aihub-71388-filekey-map.md) TS 504524~504543 순서 그대로.
torchvision detection 관례: 0 = background, 실제 클래스는 1..20.
라벨 JSON의 'class' 값(영문 자재명)이 키. zip 파일명의 자재명과 동일.
"""

CLASS_NAMES = [
    "brailleBlock", "brick", "castIronCover", "circleManhole", "collectorWell",
    "curbStone", "deckPlate", "doubleWallPipe", "floorPost", "flumeTube",
    "forms", "pvcPipe", "rubberCone", "scaffold", "squareManhole",
    "steelBar", "steelGrating", "trenchCover", "waterBarrier", "wideflangeShapes",
]
assert len(CLASS_NAMES) == 20

# name -> label_id (1..20)
CLASS_MAP = {name: i + 1 for i, name in enumerate(CLASS_NAMES)}
# label_id -> name (0 = __background__)
ID_TO_NAME = {0: "__background__", **{i + 1: n for i, n in enumerate(CLASS_NAMES)}}

NUM_CLASSES = len(CLASS_NAMES) + 1  # +1 background = 21

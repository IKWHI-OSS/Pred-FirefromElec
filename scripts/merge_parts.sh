#!/usr/bin/env bash
# aihubshell이 큰 파일을 1GB .partN(오프셋명) 조각으로 받고 병합하지 않은 경우,
# 조각을 오프셋 순서로 이어붙여 원본 .zip 으로 복원한다.
# 사용:  bash merge_parts.sh [데이터폴더]   (기본 = 현재 폴더)
# 안전:  병합은 .tmp 에 한 뒤 원자적 mv. .part 원본은 지우지 않음(검증 후 수동 삭제).
set -eu

DIR="${1:-.}"

if [ -z "$(find "$DIR" -type f -name '*.part*' 2>/dev/null | head -1)" ]; then
  echo "병합할 .part 조각이 없음 ($DIR)"
  exit 0
fi

# 하위폴더까지 재귀로 .partN 조각을 찾아 베이스 전체경로(예: .../NAME.zip) 목록 생성
find "$DIR" -type f -name '*.part*' | sed -E 's/\.part[0-9]+$//' | sort -u | while IFS= read -r base; do
  [ -z "$base" ] && continue
  echo "병합: $base"
  # 오프셋 숫자 기준 오름차순 정렬
  ordered=$(for p in "$base".part*; do printf '%s\t%s\n' "${p##*.part}" "$p"; done | sort -n | cut -f2-)
  : > "$base.tmp"
  printf '%s\n' "$ordered" | while IFS= read -r p; do
    [ -n "$p" ] && cat "$p" >> "$base.tmp"
  done
  mv "$base.tmp" "$base"
  echo "  → $(du -h "$base" | cut -f1)"
done

echo
echo "완료. 무결성 확인:  unzip -t <파일>.zip"
echo "검증 끝나면 조각 삭제로 공간 회수:  rm *.part*"

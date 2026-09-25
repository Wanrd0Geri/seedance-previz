#!/usr/bin/env bash
# encode.sh <png目录> <输出.mp4> [fps，默认 24]
# png 序列 → h264 mp4（yuv420p，crf 18）→ ffprobe 核对并按 Seedance 上传限制打分
# → 同名 _逐秒.png（每秒一格拼图）和 _首中末.png（从 mp4 解出的首帧、中帧、末帧）。
# 只收文件名以数字结尾的 png（frame_0001.png），按数字排序；帧号有缺口会提示。
set -euo pipefail

usage() { echo "用法：encode.sh <png目录> <输出.mp4> [fps，默认 24]" >&2; exit 2; }
[ $# -ge 2 ] || usage
IN_DIR=$1
OUT=$2
FPS=${3:-24}
command -v ffmpeg >/dev/null || { echo "找不到 ffmpeg" >&2; exit 3; }
command -v ffprobe >/dev/null || { echo "找不到 ffprobe" >&2; exit 3; }
[ -d "$IN_DIR" ] || { echo "不是目录：$IN_DIR" >&2; exit 2; }
case "$OUT" in *.mp4|*.MP4) ;; *) echo "输出要是 .mp4：$OUT" >&2; exit 2 ;; esac
case "$FPS" in ''|*[!0-9]*) echo "fps 要是整数：$FPS" >&2; exit 2 ;; esac

OUT_DIR=$(cd "$(dirname "$OUT")" 2>/dev/null && pwd || true)
if [ -z "$OUT_DIR" ]; then mkdir -p "$(dirname "$OUT")"; OUT_DIR=$(cd "$(dirname "$OUT")" && pwd); fi
OUT="$OUT_DIR/$(basename "$OUT")"
STEM="${OUT%.*}"
TMP=$(mktemp -d "$OUT_DIR/.encode_tmp.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

# 按文件名末尾的数字排序，软链成连续编号
LIST=$(cd "$IN_DIR" && ls -1 | grep -E '[0-9]+\.png$' \
  | awk '{ s=$0; sub(/\.png$/, "", s); match(s, /[0-9]+$/); print substr(s, RSTART) + 0 "\t" $0 }' \
  | sort -n -k1,1 || true)
[ -n "$LIST" ] || { echo "目录里没有以数字结尾的 png：$IN_DIR" >&2; exit 2; }
ABS_IN=$(cd "$IN_DIR" && pwd)
N=0; FIRST=""; LAST=""
while IFS="$(printf '\t')" read -r num name; do
  N=$((N + 1))
  [ -z "$FIRST" ] && FIRST=$num
  LAST=$num
  ln -s "$ABS_IN/$name" "$TMP/$(printf '%06d' "$N").png"
done <<EOF
$LIST
EOF
SPAN=$((LAST - FIRST + 1))
echo "输入：$N 张 png，帧号 $FIRST–$LAST"
[ "$SPAN" -eq "$N" ] || echo "注意：帧号不连续，缺 $((SPAN - N)) 张（按现有 $N 张连续编码）"

ffmpeg -v error -y -framerate "$FPS" -i "$TMP/%06d.png" \
  -vf "crop=trunc(iw/2)*2:trunc(ih/2)*2" \
  -c:v libx264 -pix_fmt yuv420p -crf 18 -preset medium -r "$FPS" -movflags +faststart "$OUT"

W=""; H=""; RATE=""; NB=""; DUR=""; SIZE=""; CODEC=""
while IFS='=' read -r k v; do
  case "$k" in
    width) W=$v ;; height) H=$v ;; r_frame_rate) RATE=$v ;; nb_read_frames) NB=$v ;;
    duration) DUR=$v ;; size) SIZE=$v ;; codec_name) CODEC=$v ;;
  esac
done <<EOF
$(ffprobe -v error -select_streams v:0 -count_frames \
  -show_entries stream=codec_name,width,height,r_frame_rate,nb_read_frames:format=duration,size \
  -of default=nw=1 "$OUT")
EOF
FPS_OUT=$(awk -v r="$RATE" 'BEGIN{ split(r, a, "/"); if (a[2] == 0) a[2] = 1; printf "%.3f", a[1] / a[2] }')
echo "ffprobe：width=$W height=$H fps=$FPS_OUT nb_frames=$NB duration=$DUR size=$SIZE codec=$CODEC"

check() { if [ "$1" = 1 ]; then echo "  通过    $2"; else echo "  不通过  $2"; FAILS=$((FAILS + 1)); fi; }
FAILS=0
echo "Seedance 上传限制："
check "$(awk -v d="$DUR" 'BEGIN{ print ((d >= 2 && d <= 30) ? 1 : 0) }')" "时长 ${DUR}s（每段 2–30 s）"
check "$(awk -v f="$FPS_OUT" 'BEGIN{ print ((f >= 24 && f <= 60) ? 1 : 0) }')" "帧率 ${FPS_OUT}（24–60）"
check "$(awk -v w="$W" -v h="$H" 'BEGIN{ s = (w < h) ? w : h; l = (w < h) ? h : w; print ((s >= 480 && l <= 4096) ? 1 : 0) }')" "分辨率 ${W}×${H}（短边 ≥480，长边 ≤4096）"
check "$(awk -v w="$W" -v h="$H" 'BEGIN{ r = w / h; print ((r >= 0.4 && r <= 2.5) ? 1 : 0) }')" "宽高比 $(awk -v w="$W" -v h="$H" 'BEGIN{ printf "%.3f", w / h }')（0.4–2.5）"
check "$(awk -v s="$SIZE" 'BEGIN{ print ((s <= 200000000) ? 1 : 0) }')" "大小 $(awk -v s="$SIZE" 'BEGIN{ printf "%.1f", s / 1000000 }') MB（≤200 MB）"
check "$([ "$CODEC" = h264 ] && echo 1 || echo 0)" "编码 ${CODEC}，mp4"
[ "$NB" = "$N" ] || echo "  注意    解出 $NB 帧，输入 $N 张"

# 逐秒拼图：取第 0、1、2… 秒的第一帧（帧号 0、fps、2×fps…），5 列
SEC=$(( (NB + FPS - 1) / FPS ))
COLS=$(( SEC < 5 ? SEC : 5 )); ROWS=$(( (SEC + COLS - 1) / COLS ))
ffmpeg -v error -y -i "$OUT" \
  -vf "select=not(mod(n\,$FPS)),scale=400:-1,tile=${COLS}x${ROWS}:padding=4:color=black" \
  -fps_mode vfr -frames:v 1 -update 1 "${STEM}_逐秒.png"
# 首帧、中帧、末帧：从编码后的 mp4 解出来，不拿渲染序列顶替
MID=$(( (NB - 1) / 2 )); END=$(( NB - 1 ))
ffmpeg -v error -y -i "$OUT" \
  -vf "select=eq(n\,0)+eq(n\,$MID)+eq(n\,$END),scale=640:-1,tile=3x1:padding=4:color=black" \
  -fps_mode vfr -frames:v 1 -update 1 "${STEM}_首中末.png"

echo "输出：$OUT"
[ -s "${STEM}_逐秒.png" ] || { echo "逐秒拼图没生成" >&2; exit 4; }
[ -s "${STEM}_首中末.png" ] || { echo "首中末帧没生成" >&2; exit 4; }
echo "      ${STEM}_逐秒.png（${SEC} 格）"
echo "      ${STEM}_首中末.png（第 1、$((MID + 1))、$((END + 1)) 帧）"
if [ "$FAILS" -gt 0 ]; then echo "结论：$FAILS 项不合上传限制，改好再传"; else echo "结论：合上传限制"; fi
echo "下一步：用 Read 看两张图"

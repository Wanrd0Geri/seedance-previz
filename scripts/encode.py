# -*- coding: utf-8 -*-
"""png 序列 → h264 mp4，跨平台（macOS / Windows / Linux），只用标准库 + ffmpeg。

用法：python3 -X utf8 encode.py <png目录> <输出.mp4> [fps，默认 24] [首帧 末帧]

png 序列 → h264 mp4（yuv420p，crf 18）→ ffprobe 核对并按 Seedance 上传限制打分
→ 同名 _逐秒.png（每秒一格拼图）和 _首中末.png（从 mp4 解出的首帧、中帧、末帧）。
只收文件名以数字结尾的 png（frame_0001.png），按数字排序；帧号有缺口会提示。
分段：末尾再给首帧、末帧（全片帧号，两个都给才生效），只收这段帧；输出的 mp4 从第 1 帧起。
后期（可选，写在哪个位置都行）：
  --flash 25,49,54        这些帧（png 帧号 = Blender 帧号）整屏提亮一帧，当闪白
  --flash-gain 0.28       提亮量，默认 0.28（蛟龙案例的值；1.0 = 全白）
  --fade-white 6.625 0.25 从输出第 6.625 秒起用 0.25 秒淡到全白（结尾白场）
  两样都在编码时加进 mp4，png 序列不动；逐秒图、首中末图从加过效果的 mp4 解出，末帧应是白的。
（与旧 encode.sh 语义一致；encode.sh 现在只是调用本脚本的薄封装。）
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

USAGE = "用法：encode.py <png目录> <输出.mp4> [fps，默认 24] [首帧 末帧] [--flash 帧,帧,…] [--flash-gain 0.28] [--fade-white 起始秒 时长秒]"


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def find_tool(name):
    """PATH → 环境变量 FFMPEG_DIR → 常见安装位置。"""
    exe = name + (".exe" if os.name == "nt" else "")
    p = shutil.which(name)
    if p:
        return p
    dirs = []
    if os.environ.get("FFMPEG_DIR"):
        dirs.append(os.environ["FFMPEG_DIR"])
    if os.name == "nt":
        dirs += [r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"]
        dirs += [str(d / "bin") for d in Path("C:/").glob("ffmpeg*")]
    else:
        dirs += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    for d in dirs:
        c = os.path.join(d, exe)
        if os.path.isfile(c):
            return c
    die(f"找不到 {name}（装 ffmpeg，或设环境变量 FFMPEG_DIR 指向它的 bin 目录）", 3)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"命令失败：{' '.join(map(str, cmd))}\n{r.stderr.strip()}", 4)
    return r.stdout


def link_or_copy(src, dst):
    """先试硬链接（不占空间），不行再复制。Windows 上软链要权限，所以不用。"""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def parse_flags(argv):
    """把 --flash / --flash-gain / --fade-white 从参数里挑出来，剩下的按原来的位置参数解释。"""
    rest, flash, gain, fade = [], [], 0.28, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--flash":
            i += 1
            if i >= len(argv):
                die("--flash 后面要跟帧号列表，如 --flash 25,49,54")
            for s in argv[i].split(","):
                s = s.strip()
                if not s.isdigit():
                    die(f"--flash 的帧号要是整数：{s}")
                flash.append(int(s))
        elif a == "--flash-gain":
            i += 1
            try:
                gain = float(argv[i])
            except (IndexError, ValueError):
                die("--flash-gain 后面要跟 0–1 的数，如 --flash-gain 0.28")
            if not 0.0 < gain <= 1.0:
                die(f"--flash-gain 要在 0–1 之间：{gain}")
        elif a == "--fade-white":
            try:
                st, d = float(argv[i + 1]), float(argv[i + 2])
            except (IndexError, ValueError):
                die("--fade-white 后面要跟起始秒和时长秒，如 --fade-white 6.625 0.25")
            if st < 0 or d <= 0:
                die(f"--fade-white 起始秒要 ≥0、时长要 >0：{st} {d}")
            fade = (st, d)
            i += 2
        elif a.startswith("--"):
            die(f"不认识的选项：{a}；{USAGE}")
        else:
            rest.append(a)
        i += 1
    return rest, flash, gain, fade


def main(argv):
    argv, flash, gain, fade = parse_flags(argv)
    if not (2 <= len(argv) <= 5) or len(argv) == 4:
        die(USAGE)
    in_dir, out = Path(argv[0]), Path(argv[1])
    fps_s = argv[2] if len(argv) > 2 else "24"
    seg_a = argv[3] if len(argv) > 3 else None
    seg_b = argv[4] if len(argv) > 4 else None
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not in_dir.is_dir():
        die(f"不是目录：{in_dir}")
    if out.suffix.lower() != ".mp4":
        die(f"输出要是 .mp4：{out}")
    if not fps_s.isdigit():
        die(f"fps 要是整数：{fps_s}")
    fps = int(fps_s)
    a = b = None
    if seg_a is not None:
        if not seg_a.isdigit():
            die(f"首帧要是整数：{seg_a}")
        if not seg_b.isdigit():
            die(f"末帧要是整数：{seg_b}")
        a, b = int(seg_a), int(seg_b)
        if a > b:
            die(f"首帧 {a} 大于末帧 {b}")

    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")

    items = []
    for f in in_dir.iterdir():
        m = re.search(r"(\d+)\.png$", f.name)
        if f.is_file() and m:
            items.append((int(m.group(1)), f))
    items.sort(key=lambda x: x[0])
    if not items:
        die(f"目录里没有以数字结尾的 png：{in_dir}")
    if a is not None:
        items = [x for x in items if a <= x[0] <= b]
        if not items:
            die(f"第 {a}–{b} 帧没有 png：{in_dir}")
    n = len(items)
    first, last = items[0][0], items[-1][0]
    span = last - first + 1
    if a is not None:
        print(f"分段：第 {a}–{b} 帧，{n} 张")
    print(f"输入：{n} 张 png，帧号 {first}–{last}")
    if span != n:
        print(f"注意：帧号不连续，缺 {span - n} 张（按现有 {n} 张连续编码）")

    # 后期：闪白按 png 帧号找到它在输出里的序号（0 起，分段和缺帧都照顾到）；白场按输出秒数
    vf = ["crop=trunc(iw/2)*2:trunc(ih/2)*2"]
    if flash:
        idx = {fr: i for i, (fr, _) in enumerate(items)}
        missing = sorted(set(f for f in flash if f not in idx))
        if missing:
            die(f"--flash 的帧号不在这段序列里：{missing}（序列是第 {first}–{last} 帧）")
        flash = sorted(set(flash))
        expr = "+".join(f"eq(n\\,{idx[f]})" for f in flash)
        vf.append(f"eq=brightness={gain}:enable='{expr}'")
        print(f"闪白：第 {','.join(map(str, flash))} 帧提亮 {gain}")
    if fade:
        st, d = fade
        if st >= n / fps:
            die(f"--fade-white 起始 {st} s 超过片长 {n / fps:.3f} s")
        vf.append(f"fade=t=out:st={st}:d={d}:color=white")
        print(f"白场：第 {st} s 起 {d} s 淡到全白")

    # 临时目录放在输出旁边（同盘才能硬链接），按连续编号链进去
    tmp = Path(tempfile.mkdtemp(prefix=".encode_tmp_", dir=out.parent))
    try:
        for i, (_, f) in enumerate(items, 1):
            link_or_copy(str(f.resolve()), str(tmp / f"{i:06d}.png"))
        run([ffmpeg, "-v", "error", "-y", "-framerate", str(fps), "-i", str(tmp / "%06d.png"),
             "-vf", ",".join(vf),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
             "-r", str(fps), "-movflags", "+faststart", str(out)])
    finally:
        for f in tmp.glob("*.png"):
            f.unlink()
        try:
            tmp.rmdir()
        except OSError:
            pass

    info = {}
    for line in run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
                     "-show_entries",
                     "stream=codec_name,width,height,r_frame_rate,nb_read_frames:format=duration,size",
                     "-of", "default=nw=1", str(out)]).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    w, h = int(info["width"]), int(info["height"])
    num, _, den = info["r_frame_rate"].partition("/")
    fps_out = float(num) / (float(den) if den and float(den) else 1)
    nb = int(info["nb_read_frames"])
    dur, size, codec = float(info["duration"]), int(info["size"]), info["codec_name"]
    print(f"ffprobe：width={w} height={h} fps={fps_out:.3f} nb_frames={nb} duration={info['duration']} "
          f"size={size} codec={codec}")

    fails = 0

    def check(ok, msg):
        nonlocal fails
        if ok:
            print(f"  通过    {msg}")
        else:
            print(f"  不通过  {msg}")
            fails += 1

    print("Seedance 上传限制：")
    check(2 <= dur <= 30, f"时长 {info['duration']}s（每段 2–30 s）")
    check(24 <= fps_out <= 60, f"帧率 {fps_out:.3f}（24–60）")
    check(min(w, h) >= 480 and max(w, h) <= 4096, f"分辨率 {w}×{h}（短边 ≥480，长边 ≤4096）")
    check(0.4 <= w / h <= 2.5, f"宽高比 {w / h:.3f}（0.4–2.5）")
    check(size <= 200000000, f"大小 {size / 1e6:.1f} MB（≤200 MB）")
    check(codec == "h264", f"编码 {codec}，mp4")
    if nb != n:
        print(f"  注意    解出 {nb} 帧，输入 {n} 张")
    # 整秒：播放器把 6.83 秒显示成 6 秒，用户按它选生成时长会截掉尾镜（屋脊打戏 v22，规则页 5.2 节）
    whole = nb // fps
    integer_len = nb % fps == 0
    if not integer_len:
        print(f"  注意    总长 {nb / fps:.3f} s 不是整秒：播放器会显示成 {whole} 秒，按它选生成时长会截掉尾镜；"
              f"把总帧数补到 {fps} 的倍数（{(whole + 1) * fps} 帧），多出的帧加在最后一镜尾巴上，不改切点")

    # 逐秒拼图：取第 0、1、2… 秒的第一帧，5 列
    sec = (nb + fps - 1) // fps
    cols = min(sec, 5)
    rows = (sec + cols - 1) // cols
    sec_png = Path(f"{stem}_逐秒.png")
    run([ffmpeg, "-v", "error", "-y", "-i", str(out),
         "-vf", f"select=not(mod(n\\,{fps})),scale=400:-1,tile={cols}x{rows}:padding=4:color=black",
         "-fps_mode", "vfr", "-frames:v", "1", "-update", "1", str(sec_png)])
    # 首帧、中帧、末帧：从编码后的 mp4 解出来，不拿渲染序列顶替
    mid, end = (nb - 1) // 2, nb - 1
    fml_png = Path(f"{stem}_首中末.png")
    run([ffmpeg, "-v", "error", "-y", "-i", str(out),
         "-vf", f"select=eq(n\\,0)+eq(n\\,{mid})+eq(n\\,{end}),scale=640:-1,tile=3x1:padding=4:color=black",
         "-fps_mode", "vfr", "-frames:v", "1", "-update", "1", str(fml_png)])

    print(f"输出：{out}")
    for p in (sec_png, fml_png):
        if not p.is_file() or p.stat().st_size == 0:
            die(f"没生成：{p}", 4)
    print(f"      {sec_png}（{sec} 格）")
    print(f"      {fml_png}（第 1、{mid + 1}、{end + 1} 帧）")
    print(f"结论：{fails} 项不合上传限制，改好再传" if fails else "结论：合上传限制")
    if integer_len:
        print(f"生成时长：选 {whole} 秒（白模正好 {whole} 秒；汇报第一行照抄这句）")
    else:
        print(f"生成时长：白模 {nb / fps:.3f} s 不是整秒，先补到 {whole + 1} 秒再交付")
    print("下一步：打开看两张图")


if __name__ == "__main__":
    main(sys.argv[1:])

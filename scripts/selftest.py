# -*- coding: utf-8 -*-
"""跨平台自测入口：找到 Blender，后台跑 previz_lib.py 自测。

用法：python3 -X utf8 selftest.py        （通过时输出含 SELFTEST OK，退出码 0）
Blender 查找顺序：环境变量 BLENDER_EXECUTABLE / BLENDER → PATH → 各平台常见安装位置（取最新版本）。
"""
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def find_blender():
    for var in ("BLENDER_EXECUTABLE", "BLENDER"):
        v = os.environ.get(var)
        if v and os.path.isfile(v):
            return v
    p = shutil.which("blender")
    if p:
        return p
    cands = []
    if sys.platform == "darwin":
        cands += glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
    elif os.name == "nt":
        for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                                  r"C:\Program Files")):
            cands += glob.glob(os.path.join(base, "Blender Foundation", "Blender *", "blender.exe"))
    else:
        cands += ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"]

    def ver(path):
        m = re.search(r"Blender (\d+(?:\.\d+)*)", path)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

    cands = [c for c in dict.fromkeys(cands) if os.path.isfile(c)]
    return max(cands, key=ver) if cands else None


def main():
    exe = find_blender()
    if not exe:
        print("找不到 Blender：设环境变量 BLENDER_EXECUTABLE 指向 blender 可执行文件", file=sys.stderr)
        return 3
    lib = Path(__file__).resolve().parent / "previz_lib.py"
    print("Blender:", exe)
    r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(lib)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       encoding="utf-8", errors="replace")
    keep = [l for l in r.stdout.splitlines() if "SELFTEST" in l or "Error" in l or "Traceback" in l]
    print("\n".join(keep))
    ok = "SELFTEST OK" in r.stdout and r.returncode == 0
    if not ok:
        print(r.stdout[-3000:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

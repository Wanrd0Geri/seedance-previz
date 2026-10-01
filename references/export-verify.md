# 渲染、导出与核对

## 1 渲染设置

`pv.setup_workbench(res, fps, sun_dir, frame_range)` 一次设好：

- Workbench 渲染器；物体色（OBJECT）；投影开；cavity 开；高光关。景深按镜头开（camera-moves.md 第 7 节），setup_workbench 不碰它。
- 视图变换 Standard：颜色按写进去的出，不被 AgX 压暗偏色。
- 摄影棚光改世界坐标，转到太阳方位：切镜后亮面不换边。要纯平光传 `light="FLAT"`。
- 逆光看不清：传 `shadow_intensity=0.4`；再不行传 `follow_camera=True`（摄影棚光跟相机走，投影方向仍按 sun_dir 固定；check_export 只记备注）。仰拍底面全黑传 `studio_light="studio.sl"`。旧场景是材质色：默认 `adopt_material_colors=True` 会把材质色抄进物体色，不会渲成全白。
- 背景用世界色，默认中性灰。png、RGB、8 位；stamp 关。
- 建 `LGT_sun` 记录光向。

Workbench 不认灯物体，投影方向由 `scene.display.light_direction` 决定。Blender 5.2.2 实测：光的行进方向 = (−lx, lz, −ly)，所以"光从 s 方向来"要写 `light_direction = (s.x, s.z, −s.y)`。摄影棚光 Default 在世界坐标下，`studiolight_rotate_z = 0` 时主光方位约 −108°，rotate_z 加大光顺时针转。setup_workbench 按这两条换算；换 Blender 版本要重测（自测会查第一条）。

分辨率按画幅，短边 ≥480，宽高取偶数：

| 画幅 | 分辨率 |
|---|---|
| 16:9 | 1280×720 |
| 2.35:1 | 1280×544 |
| 9:16 | 720×1280 |
| 1:1 | 720×720 |
| 4:3 | 960×720 |

fps 24。单段 ≤30 s，即 ≤720 帧。

## 2 overlay 与辅助线

- F12 渲染（`render.render`）本来就不画 overlay、相机框、空物体。
- 会渲出来的要防：做成实体的辅助线（加了倒角的曲线、代表轨迹的细圆柱）、蜡笔、stamp 烧字。check_export 按名字和类型查。
- 要交给桌面 Blender 用插件，或做视口渲染，先跑 `pv.hide_overlays()`。

## 3 导出

帧目录规矩（E02S08 堆到 32 GB 的教训）：
- 全程一个 `frames/`，每版覆盖同名文件，不建 frames_v2、frames_v3。
- 只改了一镜，就把 A、B 设成那一镜的帧段重渲，覆盖进同一目录再合成（一镜约 1 分钟）。
- 分段上传的 mp4 不复制帧：encode.py 传首帧、末帧就行。
- 审看版不渲帧：见第 7 节。
- mp4 合成并看过逐秒图、首中末图后，`frames/` 挪进废纸篓：macOS `mv "<白模目录>/frames" ~/.Trash/<片名>_frames_<YYMMDD>`；Windows 送回收站（不永久删除）。

在 `execute_blender_code` 里分批渲 png，一次一批，别让单次调用太长（Workbench 1280×544、千来个物体时 48 帧约 5 秒）。调用超时先用 `get_scene_info` 看 Blender 还连着没有，别盲目重跑：

```python
import bpy
sc = bpy.context.scene
A, B = 1, 120                    # 这一批的帧；下一批改成 121, 240
fs, fe = sc.frame_start, sc.frame_end
sc.render.filepath = "/绝对路径/白模_<片名>/frames/frame_"
try:
    sc.frame_start, sc.frame_end = A, B
    bpy.ops.render.render(animation=True)
finally:
    sc.frame_start, sc.frame_end = fs, fe
result = {"rendered": [A, B]}
```

渲完在主机上（Bash）编码：

```bash
python3 -X utf8 $HOME/Documents/Codex/seedance-previz/scripts/encode.py "<白模目录>/frames" "<白模目录>/<片名>_白模运镜_<YYMMDD>-<n>.mp4" 24
```

Windows 上 `python3` 不可用时换成 `py -3`。旧的 `encode.sh` 保留为转调 encode.py 的薄封装（macOS / Git Bash）。

分段：末尾加首帧、末帧，如 `… 24 546 876` 只收这段帧号（用全片帧号，输出的 mp4 从第 1 帧起）。

encode.py 做的事：

- 只收文件名以数字结尾的 png，按数字排序；帧号有缺口会提示。
- h264、yuv420p、crf 18；奇数宽高裁掉 1 像素。
- ffprobe 打印 width / height / fps / nb_frames / duration / size / codec，逐条对上传限制打"通过 / 不通过"。
- 出同名 `_逐秒.png`（每秒第一帧，5 列）和 `_首中末.png`（从 mp4 解出的首帧、中帧、末帧）。

## 4 核对

1. 打开看 `_逐秒.png`：切点在不在对的秒上，主体在不在，有没有辅助线，投影朝哪边。
2. 打开看 `_首中末.png`：首帧是镜头1 的起幅，末帧是最后一镜的落幅。
3. 跑 check_export。渲之前跑一次，改完再跑一次。

对存好的 .blend（命令行）。`<Blender>` 是 Blender 可执行文件：macOS `/Applications/Blender.app/Contents/MacOS/Blender`，Windows `C:\Program Files\Blender Foundation\Blender <版本>\blender.exe`（`scripts/selftest.py` 里的 `find_blender()` 会按环境变量 `BLENDER_EXECUTABLE`、PATH、常见安装位置自动找）：

```bash
<Blender> --background 场景.blend --python $HOME/Documents/Codex/seedance-previz/scripts/check_export.py -- --out 报告.json --grain coarse
```

对窗口里的活场景：SKILL.md 第 4 节步骤 ⑥ 的代码。

读报告：

- 不通过要修，修不了写进交接卡风险栏并告诉用户。
- 画高默认按像素量算（`frame_stats` 掩码渲染，每镜起中末三帧各渲一张小图）；`pixel=False` 退回包围盒投影，偏大一点。JSON 里两种都有。
- 结论分四档：不通过 / 警告 / 备注 / 通过。备注不影响结论：够大但不动的角色（对白镜、静止巨物）、段外的标记（分段自查时正常）、摄影棚光跟相机走（setup_workbench 传了 follow_camera）。
- 分段自查：`ce.run(frame_range=(546, 876))`，命令行 `--range 546 876`，查完恢复场景帧范围。
- 用户指定鲜明色：`ce.run(vivid=True)`，命令行 `--vivid`，③ 改报警告。
- 位移 = 角色包围盒中心在世界里挪了多远 ÷ 身高。原地转身、只动胳膊不算位移。
- 旧场景没按 `CHR_` 命名：命令行加 `--chr 名1,名2`，或 `ce.run(chr_names=[...])`，指定角色根物体。
- 四肢和辅助物体只算会渲出来的：用 hide_render 藏起来就不报。旧白模去四肢可以这样改。

## 5 官方插件替代路线

开着窗口的 Blender 可以直接用即梦插件直传：

1. 先 `pv.hide_overlays()`，再存 .blend（`bpy.ops.wm.save_as_mainfile(filepath=…, copy=True)`）。
2. 在这个 Blender 里装即梦官网的 Blender 插件（装插件是改用户配置，先问用户）。
3. 侧边栏 Jimeng 页签 →"相机渲染"；或"本地上传"，选 encode.py 出的 mp4。

插件"相机渲染"用哪种渲染、带不带 overlay，未核实。传之前看一眼它出的视频。

## 6 自测

改了脚本就跑一遍。临时文件都在 `<系统临时目录>/seedance-previz-selftest/`（`tempfile.gettempdir()`：macOS 是 `/var/folders/…/T`，Windows 是 `%TEMP%`）。

```bash
python3 -X utf8 $HOME/Documents/Codex/seedance-previz/scripts/selftest.py
```

`selftest.py` 自己找 Blender（环境变量 `BLENDER_EXECUTABLE` → PATH → 各平台常见安装位置），后台跑 `previz_lib.py` 自测；Windows 上 `python3` 不可用时换成 `py -3`。它等价于 `<Blender> --background --factory-startup --python previz_lib.py`。之后可分别对自测产物跑 check_export 和 encode：

```bash
<Blender> --background <临时目录>/seedance-previz-selftest/selftest.blend --python $HOME/Documents/Codex/seedance-previz/scripts/check_export.py -- --out <临时目录>/seedance-previz-selftest/check.json
python3 -X utf8 $HOME/Documents/Codex/seedance-previz/scripts/encode.py <临时目录>/seedance-previz-selftest/frames <临时目录>/seedance-previz-selftest/selftest.mp4 24
```

预期：

- 第一条打印 `SELFTEST OK`，渲出 frame_0001.png、frame_0037.png，存 selftest.blend；失败时进程非零退出。
- check_export 报"不通过"：CHR_Limbed_图2 带四肢、颜色 0.92；CHR_Tiny_图3 太小又不动；CHR_Hero_图1 通过。
- encode 只有"时长"不通过（2 帧只有 0.08 s），`_逐秒.png`、`_首中末.png` 都生成。

## 7 审看版

layout 没定稿前只交 .blend 和审看版。审看版 = 干净 mp4 叠字幕和镜号，直接出 mp4，不渲帧（Blender 剪辑器，2026-09-27 试过）：

```python
# execute_blender_code 里
result = pv.burn_subs("<白模目录>/<片名>_白模运镜_<YYMMDD>-<n>.mp4",
                      "<白模目录>/<片名>_审看_<YYMMDD>-<n>.mp4",
                      phrases=[(196, 211, "芳儿姐", "曲叔，"), ...],
                      cuts=[("1", 1, 96), ("2", 97, 216), ...])
```

- 字幕按短句卡在说话的帧上（一句话拆成短句，各有起止帧），底部居中，"说话人：短句"，白字黑边、半透明黑底；镜号左上角。用户靠它对说话节奏，软字幕轨不够用。
- 帧号按 mp4 的第 1 帧 = 1；给分段 mp4 烧字幕就传 offset=段首全片帧号 − 1。
- 定稿交付的分段不带字幕（用户 2026-09-27"去掉字幕"）；审看版全片超过 30 s 不上传。
- 本机 ffmpeg 没有 drawtext / subtitles 滤镜，别往那条路试。

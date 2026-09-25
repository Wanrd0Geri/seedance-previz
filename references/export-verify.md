# 渲染、导出与核对

## 1 渲染设置

`pv.setup_workbench(res, fps, sun_dir, frame_range)` 一次设好：

- Workbench 渲染器；物体色（OBJECT）；投影开；cavity 开；高光关；景深关。
- 视图变换 Standard：颜色按写进去的出，不被 AgX 压暗偏色。
- 摄影棚光改世界坐标，转到太阳方位：切镜后亮面不换边。要纯平光传 `light="FLAT"`。
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

在 Higgs 的 bl_execute 里分批渲 png，一次一批，别让单次调用太长。超时用 bl_job_status 查，别盲目重跑（blender-scene）：

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
bash ~/.claude/skills/seedance-previz/scripts/encode.sh "<白模目录>/frames" "<白模目录>/<片名>_白模运镜_<YYMMDD>-<n>.mp4" 24
```

encode.sh 做的事：

- 只收文件名以数字结尾的 png，按数字排序；帧号有缺口会提示。
- h264、yuv420p、crf 18；奇数宽高裁掉 1 像素。
- ffprobe 打印 width / height / fps / nb_frames / duration / size / codec，逐条对上传限制打"通过 / 不通过"。
- 出同名 `_逐秒.png`（每秒第一帧，5 列）和 `_首中末.png`（从 mp4 解出的首帧、中帧、末帧）。

## 4 核对

1. 用 Read 看 `_逐秒.png`：切点在不在对的秒上，主体在不在，有没有辅助线，投影朝哪边。
2. 用 Read 看 `_首中末.png`：首帧是镜头1 的起幅，末帧是最后一镜的落幅。
3. 跑 check_export。渲之前跑一次，改完再跑一次。

对存好的 .blend（命令行）：

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background 场景.blend --python ~/.claude/skills/seedance-previz/scripts/check_export.py -- --out 报告.json --grain coarse
```

对 Higgs 的活场景：SKILL.md 第 4 节步骤 ⑥ 的代码。

读报告：

- 结论三档：不通过 / 有警告 / 通过。不通过要修，修不了写进交接卡风险栏并告诉用户。
- 画高按包围盒投影算，比像素量偏大一点；很大的物体贴着画框边时，可能被算成在画内。拿不准就看渲染图。
- 位移 = 角色包围盒中心在世界里挪了多远 ÷ 身高。原地转身、只动胳膊不算位移。
- 旧场景没按 `CHR_` 命名：命令行加 `--chr 名1,名2`，或 `ce.run(chr_names=[...])`，指定角色根物体。
- 四肢和辅助物体只算会渲出来的：用 hide_render 藏起来就不报。旧白模去四肢可以这样改。

## 5 官方插件替代路线

Higgs 后台跑不了即梦插件。要用插件直传：

1. 先 `pv.hide_overlays()`，再 `bl_save_project` 存 .blend。
2. 用户在桌面 Blender 打开这个 .blend，装即梦官网的 Blender 插件。
3. 侧边栏 Jimeng 页签 →"相机渲染"；或"本地上传"，选 encode.sh 出的 mp4。

插件"相机渲染"用哪种渲染、带不带 overlay，未核实。传之前看一眼它出的视频。

## 6 自测

改了脚本就跑一遍。临时文件都在 `/tmp/seedance-previz-selftest/`。

```bash
B=/Applications/Blender.app/Contents/MacOS/Blender
S=~/.claude/skills/seedance-previz/scripts
$B --background --python $S/previz_lib.py
$B --background /tmp/seedance-previz-selftest/selftest.blend --python $S/check_export.py -- --out /tmp/seedance-previz-selftest/check.json
bash $S/encode.sh /tmp/seedance-previz-selftest/frames /tmp/seedance-previz-selftest/selftest.mp4 24
```

预期：

- 第一条打印 `SELFTEST OK`，渲出 frame_0001.png、frame_0037.png，存 selftest.blend；失败时进程非零退出。
- 第二条报"不通过"：CHR_Limbed_图2 带四肢、颜色 0.92；CHR_Tiny_图3 太小又不动；CHR_Hero_图1 通过。
- 第三条只有"时长"不通过（2 帧只有 0.08 s），`_逐秒.png`、`_首中末.png` 都生成。

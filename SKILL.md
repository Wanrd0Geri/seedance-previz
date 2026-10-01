---
name: seedance-previz
description: 用 Blender（本机 Blender MCP，连开着窗口的 Blender）搭 Seedance 2.5 白模预演，交付符合即梦白模要求的参考视频和给 aigc-video 写提示词用的交接卡。两条路线：已有精模就只做导入、摆放与运镜；没有素材就用几何体搭场景加只留躯体的角色代理（龙、蛇这类长条生物只留头部标记）。用于"搭白模 / 白模预演 / 用 Blender 做这段的运镜和调度 / 出白模参考视频"。不用于写视频提示词（那是 aigc-video）、精细建模、材质与最终渲染、非 Seedance 的 Blender 工作。
---

# Seedance 白模预演

## 1 定位

在 Blender 里搭白模，交两样东西：一段能直接传即梦的白模参考视频，一张交接卡。

分工：aigc-video 写提示词，这边搭模、定机位，两边只靠交接卡连接。aigc-video 的文件只读，不改。做过的案例在 `cases/`。

依赖本机的 Blender MCP（Claude Code 与 Codex 里都叫 `blender`；工具 `execute_blender_code`、`get_scene_info`、`get_addon_status`、`get_viewport_screenshot`），它连的是开着窗口的 Blender。调不通先看 Blender 开没开、插件的连接服务开没开；没开就用 `scripts/start_blender_mcp.py` 带窗口启动 Blender（命令见 README）。插件报版本旧、但 `execute_blender_code` 能用，就照常干活。这个插件默认把提示词、代码和截图发给插件方：开工时提醒用户一次，用户要关就调 `disable_telemetry`。

## 2 两条路线

先判断走哪条，写进任务卡。

- **A 已有精模 → 细颗粒度。** 导入副本 → 归一化到米 → 摆放 → 运镜 → 关辅助显示 → 导出。只动副本，原文件不碰。
- **B 没有素材 → 粗颗粒度。** 任务卡定世界布局 → 几何体搭场景 → 躯体代理 → 运镜 → 导出。官方说当前粗颗粒度效果更好，拿不准就走 B。
- **混合**（精模场景 + 躯体代理角色）：未试，只作可选项。用了就在交接卡里写明。
- **B′ 非人形长条生物（龙、蛇、鱼）→ 头部标记。** 身体一点不建，只建一颗带尖嘴的椭球标头的位置和朝向（`pv.head_marker`），镜头始终看它；环境做半透明起伏形体。带整条身体的代理会被成片照形状画（蛟龙案例，L152）。细则 `references/proxies.md` 第 1.1 节，案例 `cases/2026-10-01-jiao-tornado.md`。

## 3 必须守住

细则和来源在 `references/seedance-whitebox-rules.md`，这里只列底线：

1. 粗白模的角色不带四肢和翅膀，只留躯体。带了就得在提示词里写全四肢动作序列，否则成片僵化（官方手册）。龙、蛇这类长条生物连躯体都不要，只留头部标记（蛟龙案例：整条身体代理被成片照形状画，L152；一个案例）。
2. 颜色默认中性灰阶或近服装色，饱和度 ≤0.3（白模颜色会渗进成片，外部实测）。用户指定鲜明分色就照做：自查加 vivid 只报警告，交接卡加一句"服装颜色以参考图为准"。
3. 每镜主体画高 ≥ 一成，而且要动（本镜位移 ≥ 半个身高）。又小又不动会被整个丢掉（外部实测，L121）。
4. 轨迹线、坐标轴、相机框、overlay 全关。官方要求细颗粒度上传前去掉，粗的照样关。
5. 一盏主光带投影，方向 = 成片的光向。模型会从白模读光源方向、色温和投影（官方）。
6. 一段 2–30 秒，总长 ≤30 秒，24 fps 以上，短边 ≥480，mp4。超出就传不上去（官方上传限制）。
7. 切点和运镜按分镜。按稿写的机位在白模里拍不出来，报给用户，不硬凑。
8. 交付物进项目文件夹，不写桌面。

## 4 流程八步

① **读分镜。** 有 aigc-video 稿就读它的镜头表和世界布局，只读。

② **写任务卡**（`references/task-card.md`）。先定谁在哪、朝哪、看哪、光从哪来，按米写坐标，再推每镜机位能看见什么。

③ **开工。** `get_addon_status` → `get_scene_info`。场景里已有东西就先存恢复副本（`bpy.ops.wm.save_as_mainfile(filepath=…, copy=True)`）；新建的都进 `PREVIZ` 集合，不删不改不相干的物体（默认的 Cube、Light、Camera 只关渲染和显示）。在 `execute_blender_code` 里载入函数库：

```python
import sys, os, importlib
d = os.path.expanduser("~/Documents/Codex/seedance-previz/scripts")
if d not in sys.path: sys.path.insert(0, d)
import previz_lib as pv; importlib.reload(pv)
result = pv.setup_workbench(res=(1280, 544), fps=24, sun_dir=(-0.6, 0.75, 0.3), frame_range=(1, 480))
```

每次 `execute_blender_code` 都从前四行开头：同一个 Blender 进程里模块已加载，重复 import 不会重建场景；Blender 重开后 sys.path 会丢。`previz_lib.py` 的自测会清场景，只在命令行空白会话里跑；窗口会话里照常 import 和调用，只是不跑自测。

④ **搭建或导入。** A：导入副本（按格式用 `bpy.ops.wm.append` 或 `bpy.ops.import_scene.*`），量尺寸，归一化到米。B：按 `references/proxies.md`，用 `mk_box / mk_sphere / mk_cyl / roof / stairs` 搭场景，`torso_proxy` 做角色。

⑤ **相机与运镜**（`references/camera-moves.md`）。每镜一台相机：`camera_with_rig` + `aim_to` + `key_rig`；`set_marker_camera` 在切点帧绑相机。用户要在 Blender 里按空格从镜头看：`pv.view_through(cam)`；只在某几帧出现的物体（碎块、闪电）用 `pv.key_hide(…, viewport=True)`，窗口播放时显隐才对。

⑥ **逐镜核对。** 每镜起幅、中段、落幅各渲一张（`pv.still(路径, cam=…, frame=…)`），打开看（Claude Code 用 Read，Codex 用 view_image）。`get_viewport_screenshot` 只作辅助，可能停在旧画面，改完先 `bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)` 再截。按稿推算的可见内容和渲出来的对不上，以渲染为准，记进汇报。再跑自查，不通过就修：

```python
import sys, os, importlib
d = os.path.expanduser("~/Documents/Codex/seedance-previz/scripts")
if d not in sys.path: sys.path.insert(0, d)
import check_export as ce; importlib.reload(ce)
result = ce.run(out_json="/绝对路径/白模_<片名>/<片名>_自查_<YYMMDD>-<n>.json", grain="coarse")
```

⑦ **导出**（`references/export-verify.md`）。png 序列只渲进一个 `frames/`，每版覆盖；只改一镜就只重渲那段。在主机上跑 `scripts/encode.py`（跨平台，命令见 `references/export-verify.md` 第 3 节）出 mp4（分段传首帧、末帧）、逐秒拼图、首中末帧 → 打开看两张图。闪白帧和结尾白场在这一步加（`--flash`、`--fade-white`），不在 Blender 里做。审看版用 `pv.burn_subs` 在干净 mp4 上叠字幕，不再渲一套帧。

⑧ **收尾。** 写交接卡（`references/handoff-card.md`），`bpy.ops.wm.save_as_mainfile(filepath=…, copy=True)` 存 .blend，汇报。定稿后把 `frames/` 和过程版（旧 .blend、.blend1、改镜片段、字幕版）挪进废纸篓，目录只留最终一版：macOS 用 `mv` 进 `~/.Trash/<片名>_白模过程版_<YYMMDD>/`；Windows 用回收站（PowerShell 的 `Microsoft.VisualBasic.FileIO.FileSystem.DeleteDirectory(路径, 'OnlyErrorDialogs', 'SendToRecycleBin')`，或让用户手动删），不用永久删除。

## 5 做法要点

- **会话**：靠渲染帧核对，视窗截图只作辅助；大改前存恢复副本；装 Blender 扩展、插件或改偏好设置先问用户。
- **搭模（B 路线）**按五关走：轮廓 → 比例（按米核对）→ 层次 → 接触 → 相机读。
- **动画**：键控制器，不键一堆零碎子物体；插值有意选（贝塞尔缓入缓出 / 线性 / 常量）；旋转模式有意选，防中途翻转。逐帧算出来的复杂运动（沿路线走、按节拍变距离、方位和侧倾）写成一个 .py 放进白模目录，每次 `importlib.reload` 后重键，方便反复调。
- **相机**：先定主体、焦段、距离、高度；运动建在控制器上（RIG → HEAD → CAM）；一盏结构主光，保留投影。贴身追拍要不僵：相机状态按主体坐标系写成节拍表，关键帧之间 Catmull-Rom 过渡，加一个总幅度旋钮（`references/camera-moves.md` 第 9 节）。
- **核对**：从编码后的 mp4 解帧看（encode.py 的 `_首中末.png`），重渲一张不算证据。
- **Blender 5.x**：F 曲线走动作槽（previz_lib 已处理）；枚举值先读再设，别写死。

## 6 交付

放项目文件夹，和分镜稿同级建 `白模_<片名>/`。不知道项目文件夹在哪就问。

- `<片名>_白模_<YYMMDD>-<n>.blend`
- `<片名>_白模运镜_<YYMMDD>-<n>.mp4`（全片，干净）和分段 `<片名>_<段名>_白模运镜_…mp4`（上传用，不带字幕），各带同名 `_逐秒.png`、`_首中末.png`
- `<片名>_审看_<YYMMDD>-<n>.mp4`：字幕卡在说话帧、左上角镜号，只给用户审 layout，不上传
- `<片名>_任务卡_<YYMMDD>-<n>.md`、`<片名>_交接卡_<YYMMDD>-<n>.md`
- `<片名>_自查_<YYMMDD>-<n>.json`（check_export 输出）
- png 序列只放 `白模_<片名>/frames/` 一套；mp4 和两张图看过就把它挪进废纸篓（收尾必做，一版帧约 1 GB）。

汇报三块：

1. **自查结果**：check_export 的结论；不通过项逐条列，人工项写看过没有。
2. **几何问题**：按分镜写的机位在白模里做不到的（被挡、看不见、比例对不上），写成"机位 → 实际看到什么 → 建议改法"。例：猿三案例镜2，按稿写的机位被主殿屋檐挡住站在正脊上的主角。
3. **风险**：带四肢的镜、偏小的主体、超标的颜色、没验证过的写法。

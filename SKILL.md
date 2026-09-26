---
name: seedance-previz
description: 用 Blender（Higgsfield blender MCP）搭 Seedance 2.5 白模预演，交付符合即梦白模要求的参考视频和给 aigc-video 写提示词用的交接卡。两条路线：已有精模就只做导入、摆放与运镜；没有素材就用几何体搭场景加只留躯体的角色代理。用于"搭白模 / 白模预演 / 用 Blender 做这段的运镜和调度 / 出白模参考视频"。不用于写视频提示词（那是 aigc-video）、精细建模、材质与最终渲染、非 Seedance 的 Blender 工作。
---

# Seedance 白模预演

## 1 定位

在 Higgsfield 的后台 Blender 里搭白模，交两样东西：一段能直接传即梦的白模参考视频，一张交接卡。

分工：aigc-video 写提示词，这边搭模、定机位，两边只靠交接卡连接。aigc-video 的文件只读，不改。做过的案例在 `cases/`。

依赖 Higgsfield 的 Blender MCP（`higgsfield-use-blender`，工具名 `bl_*`），Claude Code 与 Codex 都要注册它。当前宿主调不到 `bl_health` 就停下，告诉用户这个宿主还没注册；不要改用别的 Blender MCP，比如 Codex 里名为 `blender` 的那个连的是开着窗口的 Blender，工具也不同。

## 2 两条路线

先判断走哪条，写进任务卡。

- **A 已有精模 → 细颗粒度。** 导入副本 → 归一化到米 → 摆放 → 运镜 → 关辅助显示 → 导出。只动副本，原文件不碰。
- **B 没有素材 → 粗颗粒度。** 任务卡定世界布局 → 几何体搭场景 → 躯体代理 → 运镜 → 导出。官方说当前粗颗粒度效果更好，拿不准就走 B。
- **混合**（精模场景 + 躯体代理角色）：未试，只作可选项。用了就在交接卡里写明。

## 3 必须守住

细则和来源在 `references/seedance-whitebox-rules.md`，这里只列底线：

1. 粗白模的角色不带四肢和翅膀，只留躯体。带了就得在提示词里写全四肢动作序列，否则成片僵化（官方手册）。
2. 颜色用中性灰阶或近服装色，饱和度 ≤0.3。白模颜色会渗进成片（外部实测）。
3. 每镜主体画高 ≥ 一成，而且要动（本镜位移 ≥ 半个身高）。又小又不动会被整个丢掉（外部实测，L121）。
4. 轨迹线、坐标轴、相机框、overlay 全关。官方要求细颗粒度上传前去掉，粗的照样关。
5. 一盏主光带投影，方向 = 成片的光向。模型会从白模读光源方向、色温和投影（官方）。
6. 一段 2–30 秒，总长 ≤30 秒，24 fps 以上，短边 ≥480，mp4。超出就传不上去（官方上传限制）。
7. 切点和运镜按分镜。按稿写的机位在白模里拍不出来，报给用户，不硬凑。
8. 交付物进项目文件夹，不写桌面。

## 4 流程八步

① **读分镜。** 有 aigc-video 稿就读它的镜头表和世界布局，只读。

② **写任务卡**（`references/task-card.md`）。先定谁在哪、朝哪、看哪、光从哪来，按米写坐标，再推每镜机位能看见什么。

③ **开工。** 按 blender-scene 的会话规则：`bl_health` → `bl_get_scene_summary`。场景里已有东西就先存恢复副本；新建的都进 `PREVIZ` 集合，不删不改不相干的物体。在 `bl_execute` 里载入函数库：

```python
import sys, os, importlib
d = os.path.expanduser("~/Documents/Codex/seedance-previz/scripts")
if d not in sys.path: sys.path.insert(0, d)
import previz_lib as pv; importlib.reload(pv)
result = pv.setup_workbench(res=(1280, 544), fps=24, sun_dir=(-0.6, 0.75, 0.3), frame_range=(1, 480))
```

每次 `bl_execute` 都从前四行开头：同一个 Blender 进程里模块已加载，重复 import 不会重建场景；进程重连后 sys.path 会丢。`previz_lib.py` 的自测会清场景，只在命令行空白会话里跑；Higgs 会话里照常 import 和调用，只是不跑自测。

④ **搭建或导入。** 先按路线读 Higgs 模块（第 5 节）。A：`bl_import_model` 导入副本，量尺寸，归一化到米。B：按 `references/proxies.md`，用 `mk_box / mk_sphere / mk_cyl / roof / stairs` 搭场景，`torso_proxy` 做角色。

⑤ **相机与运镜**（`references/camera-moves.md`）。每镜一台相机：`camera_with_rig` + `aim_to` + `key_rig`；`set_marker_camera` 在切点帧绑相机。

⑥ **逐镜核对。** 每镜起幅、中段、落幅各渲一张（`bl_set_frame` + `bl_render`），打开看（Claude Code 用 Read，Codex 用 view_image）。按稿推算的可见内容和渲出来的对不上，以渲染为准，记进汇报。再跑自查，不通过就修：

```python
import sys, os, importlib
d = os.path.expanduser("~/Documents/Codex/seedance-previz/scripts")
if d not in sys.path: sys.path.insert(0, d)
import check_export as ce; importlib.reload(ce)
result = ce.run(out_json="/绝对路径/白模_<片名>/<片名>_自查_<YYMMDD>-<n>.json", grain="coarse")
```

⑦ **导出**（`references/export-verify.md`）。分批渲 png 序列 → 在主机上跑 `scripts/encode.sh` 出 mp4、逐秒拼图、首中末帧 → 打开看两张图。

⑧ **收尾。** 写交接卡（`references/handoff-card.md`），`bl_save_project` 存 .blend，汇报。

## 5 Higgs 模块怎么读

开工先读 blender-scene（MCP 要求）。其余按路线读，清单和改动在 `references/higgs-modules.md`：

- A：blender-volatile、blender-lighting-camera（只读相机关）、blender-animation、blender-greybox（只读本地导出）、blender-audit-finalize。
- B：A 的全部，加 blender-scene-spec、blender-modeling（前五关）、blender-greybox（代理体与每镜记录）；室内再加 blender-camera-blocking（首次会装扩展，先问用户）。

只读要用的段，不整份读全部模块。模块里的云端工具名（`bl_render_motion_reference`、`bl_audit_motion` 等）本地没有，按 blender-volatile 的对照表换本地做法。blender-generation 只在用户点名时走（会花积分）；装 Blender 扩展或改偏好设置先问用户。

## 6 交付

放项目文件夹，和分镜稿同级建 `白模_<片名>/`。不知道项目文件夹在哪就问。

- `<片名>_白模_<YYMMDD>-<n>.blend`
- `<片名>_白模运镜_<YYMMDD>-<n>.mp4`，同名 `_逐秒.png`、`_首中末.png`
- `<片名>_任务卡_<YYMMDD>-<n>.md`、`<片名>_交接卡_<YYMMDD>-<n>.md`
- `<片名>_自查_<YYMMDD>-<n>.json`（check_export 输出）
- png 序列放 `白模_<片名>/frames/`；mp4 核对无误后，这个文件夹可以删。

汇报三块：

1. **自查结果**：check_export 的结论；不通过项逐条列，人工项写看过没有。
2. **几何问题**：按分镜写的机位在白模里做不到的（被挡、看不见、比例对不上），写成"机位 → 实际看到什么 → 建议改法"。例：猿三案例镜2，按稿写的机位被主殿屋檐挡住站在正脊上的主角。
3. **风险**：带四肢的镜、偏小的主体、超标的颜色、没验证过的写法。

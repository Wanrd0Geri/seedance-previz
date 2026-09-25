# 运镜在 Blender 里怎么做

这里只写做法。景别、角度、焦段怎么选，运镜术语怎么说，看 aigc-video（只读）：

- `~/.claude/skills/aigc-video/references/craft/camera.md`：第 1 节景别，第 2 节角度与高度，第 3 节光学，第 5–7 节运镜、一镜到底与切点。
- `~/.claude/skills/aigc-video/references/lexicon/camera-terms.md`、`camera-combo-terms.md`：术语词库，按小类 grep，不整份读。

函数都在 `scripts/previz_lib.py`，下文 `pv.` 开头。

## 1 三层相机

`cam, rig = pv.camera_with_rig("CAM_S1", lens=50, rig="dolly", loc=(2.4, 142.6, 94.0))` 一次建三层：

- `RIG_S1`：控制器。推轨、摇臂、环绕都键它。
- `HEAD_S1`：`pv.aim_to` 的 Track To 挂在这层，管镜头朝向。
- `CAM_S1`：相机本体。它自己的 Z 旋转就是 roll。

为什么分三层：Track To 会接管它所在物体的全部旋转。roll 放在下一层，荷兰角才键得动。

焦段按摄影组说法直接填：传感器宽 36 mm（全画幅）。clip_end 默认 5000 m，装得下几百米的巨物和远山。

重跑 `camera_with_rig` 会重建三层，控制器的关键帧和 aim_to 都要重做。只改焦段就直接改 `cam.data.lens`。

## 2 各种运镜

| 运镜 | 做法 |
|---|---|
| 推 / 拉 / 移（推轨） | `rig="dolly"`，`pv.key_rig(rig, f, loc=(x, y, z))` 键两个以上位置 |
| 升 / 降（摇臂） | `rig="crane"`，键 RIG 的 Z；同时改 XY 就是升降带横移 |
| 环绕 | `rig="orbit", pivot=主体坐标, radius=半径, height=机位高`，`pv.key_rig(rig, f, rot_z=弧度)`；正角度 = 俯视逆时针 |
| 摇 / 俯仰 | 相机不动，移 AIM：`aim = pv.aim_to(cam, (x, y, z))`，再 `pv.key_rig(aim, f, loc=...)` |
| 盯住移动的主体 | `pv.aim_to(cam, 主体根物体, offset=(0, 0, 1.4))`：AIM 挂在主体上跟着走，offset 按主体本地坐标 |
| 跟拍 | 控制器加 Copy Location 指向主体根物体，勾 Offset，RIG 自己的位置就是偏移（代码见下） |
| 手持 | `rig="handheld"`：RIG 位置挂 Noise，相机 roll 挂 0.3° 小 Noise；要左右上下晃，再给 AIM 挂 `pv.shake(aim, amp=...)` |
| 荷兰角 | `pv.key_rig(cam, f, rot_z=math.radians(12))`；正值 = 画面顺时针转、地平线右低（5.2.2 自测实测） |
| 变焦 | `cam.data.lens = 24; cam.data.keyframe_insert("lens", frame=f)`：焦段键在相机数据上，不在物体上 |

跟拍：

```python
c = rig.constraints.new('COPY_LOCATION'); c.target = 主体根物体; c.use_offset = True
```

手持幅度从小往大调：人物近景起步 0.02–0.05 m（`pv.shake(rig, amp=0.03, scale=10)`），scale 越大晃得越慢。以渲染为准。

## 3 节奏

- 默认贝塞尔：两个键之间自带缓入缓出。要匀速，在起点那个键写 `interp="LINEAR"`：interp 管的是这个键到下一个键那一段。
- 落幅留 6–12 帧稳定：最后两个键写同一个值。
- 24 fps 下一拍 0.5 s = 12 帧，按分镜的拍点放键。
- 抽查点：起点、起步、最快、落定、末帧（Higgs blender-animation）。每个点渲一张，用 Read 看。

## 4 切镜

每镜一台相机。切点帧打标记绑相机：`pv.set_marker_camera(97, cam_s2)`。整条一次渲完，到标记帧自动换相机。标记帧就是切点帧，要和镜头表对上（自查 ⑨）。

两条白模多机位（每条一个机位）：分两个场景或两段帧范围各渲一条，切点由提示词定（aigc-video `seedance-operations.md` 第 5 节）。

## 5 防翻转

- 本库的控制器和相机都是欧拉角，环绕只键 Z，从 0 转到 2π 不会翻。
- 导入的相机如果是四元数，又要逐帧键旋转：相邻两个键点积为负，就把后一个取反，不然插值绕远路，画面会翻一圈。

```python
if q_prev.dot(q) < 0: q.negate()
```

- 正上、正下方向看（俯仰接近 90°）时 Track To 会乱转：把 AIM 挪开一点。

## 6 按稿放机位，先验证

- 机位按米放，按分镜写的位置先渲一张看。被挡、看不见、比例不对，就报给用户，附"机位 → 实际看到什么 → 建议改法"。
- 猿三案例三条几何发现都是这样查出来的：按稿写的机位被屋檐挡住主角；从左前方看，主角身后是另一尊法相而不是巨猿；低机位仰拍时身后是巨猿腹部而不是下颌。见 `cases/2026-09-25-yuansan-faxiang.md`。

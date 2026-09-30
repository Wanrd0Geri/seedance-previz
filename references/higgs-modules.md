# Higgs 模块：借什么、改什么、按路线读哪些

用 `bl_get_skill(name)` 按需加载，只读要用的段，不复制内容。2026-09-25 用 bl_get_skill 逐个读过原文核对，出入记在第 4 节。

## 1 借用表

| 模块 | 拿什么 | 不拿 / 要改 |
|---|---|---|
| blender-scene | 会话规则：bl_health → bl_get_scene_summary；大改前存恢复副本；超时用 bl_job_status 查，不盲目重跑；没有视口，靠渲染帧核对 | — |
| blender-greybox | 按角色区分的语义代理体；每镜记录表；图片序列 → mp4 → 从 mp4 解帧核对 | **改**：第 2 节 ① |
| blender-camera-blocking（Blockstage 0.3.0） | 参数化房间、42 件家具、4 个带骨骼人偶、相机按参考图对位 | **改**：第 2 节 ② |
| blender-scene-spec | Scene Passport 精简成任务卡 | **改**：第 2 节 ③ |
| blender-modeling | 六关的前五关：轮廓 → 比例（按米核对）→ 层次 → 接触 → 相机读 | 不做第六关细节；硬表面放样不用 |
| blender-animation | 键控制器，不键一堆零碎子物体；插值有意选（贝塞尔缓入缓出 / 线性 / 常量）；旋转模式有意选，防中途翻转；运动抽查点：起点、起步、最快、落定、末帧 | — |
| blender-lighting-camera | 相机关：主体、焦段、距离、高度先定；相机运动建在语义父级控制器上（环绕 / 推轨 / 手持）；一盏结构主光，保留投影 | 三点光、反射、氛围不用 |
| bl_open_project / bl_import_model | A 路线导入精模 | 导入副本，不动原文件 |
| blender-audit-finalize | 交付前审核 + 存档；world_to_camera_view 取景核对 | **改**：第 2 节 ④ |
| blender-volatile | Blender 5.x 的坑：动作槽、EEVEE 枚举、影片输出；云端工具名 → 本地做法对照表 | — |
| 不用 | lookdev、pbr、hdri、stylized-materials、destruction；generation 只作 B 路线可选项（花积分，用户点名才走） | |

## 2 四处改动

① **greybox 的切镜规则。** 它规定一段视频只有一个主运镜，不许在一段里藏几个切镜。Seedance 粗白模恰恰要传切镜：一段 ≤30 s 里可以多镜硬切（时间轴标记绑相机），或者做两条白模各管一个机位。"一个主运镜"改成按镜算。它的代理体"按角色上色"，这里还要把饱和度压到 ≤0.3（颜色会渗进成片）。

② **camera-blocking 的人偶。** 四个人偶都带四肢和骨骼，只用来定站位、视线和机位。导出前把人偶藏起来（hide_render），原位放 `pv.torso_proxy`。它原文要求"不用几何体重建人偶"，这里导出时必须换。人偶面朝 -Y，和躯体代理的约定一致。古风场景不用它的家具，用几何体自搭。首次使用它会装扩展，先问用户（第 4 节）。

③ **scene-spec 的 Passport。** 删 LOOK（材质）、LIGHTING 细项、GEN 生成路线；光只留"光从哪来"一行；精度从 blockout / stylized / detailed 改成 Seedance 粗 / 细。结果就是 task-card.md。

④ **audit-finalize 的审核。** 结构、运动、画面三审照做，外加 Seedance 自查 10 项（seedance-whitebox-rules.md 第 7 节，脚本 check_export.py）。

## 3 按路线读哪几个

- 两条路线都先读 blender-scene：MCP 要求开工先读。
- **A 精模**：blender-volatile（只读用到的行）→ blender-lighting-camera（只读 Camera gate）→ blender-animation → blender-greybox（只读 Local motion export）→ blender-audit-finalize。
- **B 无素材**：A 的全部，再加 blender-scene-spec → blender-modeling（Blockout passes 前五关）→ blender-greybox（Motion video — shot planning、Build and motion gate）；室内场景再加 blender-camera-blocking，先问用户能不能装扩展。
- generation、hdri、pbr：用户点名才读。

## 4 核对备注（2026-09-25，bl_get_skill 读原文）

- "相机做语义父级控制器（环绕 / 推轨 / 手持）"写在 blender-lighting-camera 的相机关里，不在 blender-animation；"摇臂"两个模块都没提，是本 skill 加的。早先的借用表把它们记在 animation 行，已按原文挪。
- blender-animation 只说"四元数还是欧拉要有意选，防中途翻转"；"相邻键点积为负就取反"是本 skill 补的做法。
- camera-blocking 的"42 件家具""4 个人偶（Man、Woman、Heavy Man、Heavy Woman，IK / FK）"原文有；"家具偏现代"原文没写，是早先的判断，未核实。人偶四肢能不能单独隐藏，原文没说，所以这里用"整个人偶藏起来、换躯体代理"。
- camera-blocking 首次使用会往 Blender 装 Blockstage 扩展并保存偏好设置，原文说不必再问用户。这是改用户配置，本 skill 要求先问。
- audit-finalize 规定：passport 精度是 blockout 的资产，才允许以几何体原样出镜。所以 B 路线资产在任务卡里一律按"粗"登记（task-card.md 第 2 节最后一条）。
- greybox 的本地导出要求：从编码后的 mp4 解出首帧来核对，重渲一张不算证据。encode.py 的 `_首中末.png` 照这条做。
- blender-volatile 的 5.x 坑与原文一致；previz_lib.py 取 F 曲线用的就是它给的动作槽写法。

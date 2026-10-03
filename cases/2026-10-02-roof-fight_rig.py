# -*- coding: utf-8 -*-
"""屋脊打戏白模 v20（苏云 vs 白猿，9 镜约 8.5 秒，205 帧 @24fps，2518×1080 和原片同比例）：只管运镜和构图。
v23 = 用户看 v22 成片（视频节点 1 - 副本 (5).mp4）：空翻后白猿背对苏云落地，应该跳过来就朝着他。拧身提前到越过他头顶时（u 0.42–0.72），落地前已正面朝西；总长补到 168 帧 = 7 秒整。v22 脚本另存 roof_fight_rig_261002-22.py。
v22 = 用户：不要拨拳推人那一镜，节奏改成「击中棍子 → 白猿发力用棍把苏云顶飞 → 扫尾」；7 镜约 6.8 秒（白猿扛棍特写一并去掉）。v21 脚本另存 roof_fight_rig_261002-21.py。
v21 = 用户看 v20 成片（视频节点 1 - 副本 (3).mp4）：苏云不是被弹开的，是白猿一推把他顶开，要有推的过程——撞棍后白猿一沉一顶、拨拳后那只手顺势按肩一推；苏云近景挪到被推之后（刹车、压低、瞪眼），白猿特写挪到其后。v20 脚本另存 roof_fight_rig_261002-20.py。
v20 = 用户看 v19 成片（视频节点 1 - 副本 (2).mp4）：运镜少了动感、不如 v18 舒服；逐帧看僵硬、「像在运行程序」，
白猿空翻像落在苏云头上，落地那只脚踩得僵。改法：
  ① 全部原速，不再放慢（v19 的 1.2–1.8 倍放慢段被成片再拖长，整条往后错，最后一镜被压到 0.9 秒）；
  ② 身体分胸、胯、头三段，胸和头按身体转动自动带一点超前和滞后（不加四肢）；
  ③ 动作按预备 → 快速主动作 → 过冲回稳来键，跳跃按重力走抛物线；
  ④ 空翻顶点抬到离苏云头顶 2 米以上，机位改在南侧远一点看得见两人之间的空隙；
  ⑤ 落地：一侧先着地，往前滑半步，压到最低再弹起；落地镜跟着它起身往上摇；
  ⑥ 机位改成连续的样条路径（Catmull-Rom 式），手持晃动加大（高频抖 + 低频漂 + 画面旋转抖）；
  ⑦ 撞棍大特写机位在动（前顶、被震开、甩出去追人）；白猿特写改成边笑边把棍往肩上一扛。
v19 脚本另存 roof_fight_rig_261002-19.py；v18（已采用）另存 roof_fight_rig_261002-18.py。

窗口 Blender（MCP execute_blender_code）里：
    import sys, os, importlib
    for d in (os.path.expanduser("~/Documents/Codex/seedance-previz/scripts"),
              os.path.expanduser("~/Desktop/白模_屋脊打戏")):
        if d not in sys.path: sys.path.insert(0, d)
    import previz_lib as pv; importlib.reload(pv)
    import roof_fight_rig as rf; importlib.reload(rf)
    rf.build_all()

世界：米，Z 向上。正脊顺 X 轴（东 = +X），脊顶高 RZ。角色正面 = 本地 -Y。
轴线：镜1–6 苏云在东（南侧机位画右）、白猿在西；镜7 白猿从他头顶翻过落到东边 → 镜8、镜9 苏云画左、白猿画右（和图2 一致）。
"""
import math

import bmesh
import bpy
from mathutils import Vector

import previz_lib as pv

# ---------- 世界尺寸 ----------
RZ = 10.0
TAN30 = math.tan(math.radians(30.0))
RH = 0.35
EAVE_Y = 9.5
X_HALF = 14.0
A0X = -3.0          # 白猿起始站位
AX = A0X - 0.45     # 拨开时撤半步后的站位
ALX = 0.10          # 白猿空翻越过苏云后的落点（顶点正在苏云头顶上）

FPS = 24
CUTS = [1, 16, 32, 50, 66, 94, 116]
F_END = 168                                   # 7 秒整（v23 起白模总长取整秒，免得播放器向下取整）
SHOT_NAMES = ["飞入（远）", "撞棍大特写、白猿一顶把他顶飞", "苏云落地滑退（近景）", "金尾横扫、白猿起跳（贴瓦低机位）",
              "空翻越顶（南侧仰拍）", "落地（贴瓦特写）", "苏云单人右摇出画"]

# ---------- 代理尺寸 ----------
APE_H, APE_HEAD_D, APE_PIVOT = 4.5, 0.80, 1.9
YOUTH_H, YOUTH_HEAD_D, YOUTH_PIVOT = 1.75, 0.26, 0.85

# ---------- 颜色（饱和度 ≤0.3） ----------
APE_C = (0.80, 0.78, 0.74)
YOUTH_C = (0.40, 0.37, 0.33)
EYE_C = (0.14, 0.14, 0.15)
ROOF_C = (0.40, 0.41, 0.44)
RIDGE_C = (0.28, 0.28, 0.30)
WALL_C = (0.36, 0.34, 0.33)
GROUND_C = (0.62, 0.63, 0.65)
SKY_C = (0.70, 0.74, 0.78)
SUN_DIR = (-0.35, -0.50, 0.80)

W, E = -90.0, 90.0


def D(a):
    return math.radians(a)


def roof_z(y):
    a = abs(y)
    if a <= RH:
        return RZ
    return RZ - 0.25 - (a - RH) * TAN30


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lim):
    return max(-lim, min(lim, v))


def V(*a):
    return Vector(a)


# ---------- 通用 ----------

def K(ob, f, loc=None, rot=None, scale=None, interp="BEZIER"):
    paths = []
    if loc is not None:
        ob.location = loc
        ob.keyframe_insert("location", frame=f)
        paths.append("location")
    if rot is not None:
        ob.rotation_euler = rot
        ob.keyframe_insert("rotation_euler", frame=f)
        paths.append("rotation_euler")
    if scale is not None:
        ob.scale = scale
        ob.keyframe_insert("scale", frame=f)
        paths.append("scale")
    for fc in pv._fcurves(ob):
        if fc.data_path in paths:
            for kp in fc.keyframe_points:
                if abs(kp.co[0] - f) < 0.5:
                    kp.interpolation = interp


def clear():
    coll = bpy.data.collections.get(pv.COLL)
    if coll is not None:
        for ob in list(coll.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
    for blk in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights, bpy.data.actions):
        for d in list(blk):
            if d.users == 0:
                blk.remove(d)
    sc = bpy.context.scene
    for m in list(sc.timeline_markers):
        if m.name.startswith(("S", "CAM_")):
            sc.timeline_markers.remove(m)


def hide_defaults():
    for nm in ("Cube", "Light", "Camera"):
        ob = bpy.data.objects.get(nm)
        if ob is not None and not pv._owned(ob):
            ob.hide_render = True
            ob.hide_viewport = True


# ---------- 场景（只有屋顶、正脊、殿身、地面；参照方块 v17 起删掉，会被画成小房子） ----------

def _prism(name, prof, x0, x1, color):
    bm = bmesh.new()
    a = [bm.verts.new((x0, y, z)) for y, z in prof]
    b = [bm.verts.new((x1, y, z)) for y, z in prof]
    n = len(prof)
    bm.faces.new(list(reversed(a)))
    bm.faces.new(b)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return pv._mesh_obj(name, bm, (0.0, 0.0, 0.0), color)


def build_env():
    zE = roof_z(EAVE_Y)
    xr = X_HALF + 0.3
    prof = [(-EAVE_Y, zE - 0.35), (-EAVE_Y, zE), (-RH, RZ - 0.25), (RH, RZ - 0.25),
            (EAVE_Y, zE), (EAVE_Y, zE - 0.35), (0.0, RZ - 1.4)]
    _prism("ENV_大殿_屋面", prof, -xr, xr, ROOF_C)
    pv.mk_box("ENV_大殿_正脊", size=(2 * xr, 2 * RH, 0.6), loc=(0.0, 0.0, RZ - 0.6), color=RIDGE_C)
    pv.mk_box("ENV_大殿_殿身", size=(2 * X_HALF - 3.0, 2 * EAVE_Y - 4.0, zE), loc=(0.0, 0.0, 0.0), color=WALL_C)
    pv.mk_box("ENV_地面", size=(1600.0, 1600.0, 0.2), loc=(0.0, 0.0, -0.2), color=GROUND_C)


# ---------- 角色：胯、胸两块长方体 + 圆球头 + 长条眼睛 ----------

def _block_char(name, height, head_d, pivot_z, color, w_hip, w_chest, depth):
    """根空物体 name 在脚底 → Pivot（腰，pivot_z）挂胯块，Pivot 下的 Chest（腰）挂胸块，Chest 下的 Neck（肩）挂头和眼睛。
    整体转动键 Pivot；胸和头的超前、滞后由 apply_overlap 自动键。眼睛那面 = 脸 = 本地 -Y。mk_box 的 loc 是底面中心。"""
    root = pv._empty(name, (0.0, 0.0, 0.0), size=height * 0.15)
    root.rotation_mode = 'XYZ'
    root["previz_height"] = height
    root["previz_stature"] = height
    root["previz_pose"] = "stand"
    piv = pv._empty(f"{name}_Pivot", size=height * 0.08)
    pv._parent(piv, root)
    piv.location = (0.0, 0.0, pivot_z)
    piv.rotation_mode = 'XYZ'
    body_top = height - head_d + 0.05 * head_d
    hips = pv.mk_box(f"{name}_Hips", size=(w_hip, depth * 0.92, pivot_z), loc=(0.0, 0.0, -pivot_z), color=color)
    pv._parent(hips, piv)
    chest_e = pv._empty(f"{name}_Chest", size=height * 0.06)
    pv._parent(chest_e, piv)
    chest_e.rotation_mode = 'XYZ'
    chest = pv.mk_box(f"{name}_ChestBox", size=(w_chest, depth, body_top - pivot_z), loc=(0.0, 0.0, -0.02), color=color)
    pv._parent(chest, chest_e)
    neck = pv._empty(f"{name}_Neck", size=height * 0.05)
    pv._parent(neck, chest_e)
    neck.location = (0.0, 0.0, body_top - pivot_z)
    neck.rotation_mode = 'XYZ'
    hz = head_d / 2.0 - 0.05 * head_d
    head = pv.mk_sphere(f"{name}_Head", radius=head_d / 2.0, loc=(0.0, 0.0, hz), color=color)
    pv._parent(head, neck)
    eh = head_d * 0.13
    eye = pv.mk_box(f"{name}_Eye", size=(head_d * 0.75, head_d * 0.16, eh),
                    loc=(0.0, -head_d * 0.44, hz + head_d * 0.06 - eh / 2.0), color=EYE_C)
    pv._parent(eye, neck)
    return root


def build_chars():
    ape = _block_char("CHR_白猿_图1", APE_H, APE_HEAD_D, APE_PIVOT, APE_C, 1.30, 1.50, 0.95)
    ape.location = (A0X, 0.0, RZ)
    ape.rotation_euler = (0.0, 0.0, D(E))
    ctrl = pv._empty("CTRL_苏云", size=0.5)
    ctrl.rotation_mode = 'XYZ'
    yt = _block_char("CHR_苏云_图2", YOUTH_H, YOUTH_HEAD_D, YOUTH_PIVOT, YOUTH_C, 0.44, 0.52, 0.30)
    pv._parent(yt, ctrl)
    yt.location = (0.0, 0.0, -YOUTH_PIVOT)


# ---------- 动画 ----------

def ape_key(f, x=AX, y=0.0, z=RZ, yaw=E, pitch=0.0, roll=0.0, twist=0.0, sz=1.0, interp="BEZIER"):
    """根在脚底：x/y/z/yaw；身体绕腰转：pitch 正 = 往前俯、负 = 后仰；roll 正 = 往它自己左边歪；twist 正 = 往它左边拧。
    sz = 整个身子竖向压扁（蓄力、落地一沉）。"""
    K(bpy.data.objects["CHR_白猿_图1"], f, loc=(x, y, z), rot=(0.0, 0.0, D(yaw)), scale=(1.0, 1.0, sz), interp=interp)
    K(bpy.data.objects["CHR_白猿_图1_Pivot"], f, rot=(D(pitch), D(roll), D(twist)), interp=interp)


def youth_key(f, c, pitch=0.0, roll=0.0, yaw=W, sz=1.0, interp="BEZIER"):
    """CTRL 在腰（离脚底 0.85 m），身子绕它转；pitch 正 = 往前倾（前 = 脸朝的方向），负 = 往后仰。"""
    K(bpy.data.objects["CTRL_苏云"], f, loc=tuple(c), rot=(D(pitch), D(roll), D(yaw)), scale=(1.0, 1.0, sz),
      interp=interp)


def stand(xb, sz, lean, face=W, yb=0.0):
    """苏云脚底踩在屋面 (xb, yb) 处、往前倾 lean 度时 CTRL 的位置。"""
    h = YOUTH_PIVOT * sz
    fwd = -1.0 if face == W else 1.0
    g = max(roof_z(yb - 0.25), roof_z(yb + 0.25))
    return (xb + fwd * h * math.sin(D(lean)), yb, g + h * math.cos(D(lean)) + 0.12)


def animate():
    # ===== 苏云 =====
    # 镜1（f1–15）从画右上方飞入，越飞越快，右拳在前；f16 金拳砸在横棍上
    for f in range(1, 16):
        u = (f - 1) / 14.0
        e = u ** 1.25
        youth_key(f, (lerp(4.60, -1.42, e), lerp(-0.45, 0.0, e), RZ + lerp(5.40, 3.00, e) + 0.30 * math.sin(math.pi * e)),
                  pitch=lerp(38, 55, u), roll=lerp(-14, 0, u), sz=0.92, interp="LINEAR")
    youth_key(16, (-1.47, 0.0, RZ + 3.02), pitch=52, sz=0.90, interp="LINEAR")
    # 镜2（f16–21）拳顶在棍上：白猿先一沉吃住，再往前跟一步、双手一顶，他被顶得身子一压，跟着棍往后退
    youth_key(17, (-1.46, 0.0, RZ + 3.03), pitch=50, sz=0.90, interp="LINEAR")
    youth_key(19, (-1.42, 0.0, RZ + 3.00), pitch=46, sz=0.86)
    youth_key(21, (-1.24, 0.0, RZ + 3.00), pitch=38, sz=0.84, interp="LINEAR")
    # 镜2–3（f22–34）被顶飞，抛物线往东落回屋脊，身子往后仰
    for f in range(22, 35):
        u = (f - 21) / 13.0
        youth_key(f, (-1.24 + 1.54 * (1 - (1 - u) ** 1.6), 0.0, RZ + 3.00 + 0.8 * u - 3.20 * u * u + 0.12 * u),
                  pitch=38 - 70 * u + 22 * u * u, roll=-6 * math.sin(math.pi * u), sz=0.86, interp="LINEAR")
    # 镜3（f35–49）脚落瓦面还在往后滑，刹住，膝盖压到最低，抬眼盯着白猿，压低蓄势
    youth_key(35, stand(0.32, 0.80, -10), pitch=-10, sz=0.80, interp="LINEAR")
    youth_key(39, stand(0.50, 0.70, 6), pitch=6, sz=0.70)
    youth_key(42, stand(0.60, 0.60, 20), pitch=20, sz=0.60)                     # 刹住
    youth_key(44, stand(0.64, 0.50, 30), pitch=30, sz=0.50)                     # 压到最低
    youth_key(47, stand(0.65, 0.56, 32), pitch=32, sz=0.56)
    youth_key(49, stand(0.65, 0.52, 36), pitch=36, sz=0.52, interp="LINEAR")     # 一沉，要冲
    # 镜4（f50–65）低身往前一滑、金尾横扫（金尾交给文字）；白猿起跳时他压得更低
    for f in range(50, 62):
        u = (f - 49) / 12.0
        youth_key(f, stand(0.65 - 2.32 * (1 - (1 - u) ** 2), 0.50, 40), pitch=40, roll=-10 * math.sin(math.pi * u),
                  sz=0.50, interp="LINEAR")
    youth_key(65, stand(-1.70, 0.45, 30), pitch=30, sz=0.45)
    # 镜5（f66–93）白猿从头顶翻过时压到最低；它落到身后，他拧身转过来面朝东
    youth_key(72, stand(-1.72, 0.42, 26), pitch=26, sz=0.42)
    youth_key(81, stand(-1.74, 0.42, 26), pitch=26, sz=0.42)
    youth_key(87, stand(-1.76, 0.50, 20, E), pitch=20, yaw=0.0, sz=0.50)
    youth_key(92, stand(-1.76, 0.52, 28, E), pitch=28, yaw=E, sz=0.52)
    youth_key(99, stand(-1.76, 0.50, 32, E), pitch=32, yaw=E, sz=0.50)
    # 镜7（f116–164）一沉一蹬朝画面右上方横着扑出去，镜头往右摇追不上，他前半身冲出画右（同 v18）
    youth_key(117, stand(-1.76, 0.46, 36, E), pitch=36, yaw=E, sz=0.46)
    youth_key(120, stand(-1.78, 0.40, 42, E), pitch=42, yaw=E, sz=0.40, interp="LINEAR")
    for f, c, lean, s, yw in ((122, (-1.40, -0.05, RZ + 0.80), 55, 0.90, 88),
                              (127, (-0.85, -0.08, RZ + 1.05), 65, 1.0, 88),
                              (135, (-0.20, -0.10, RZ + 1.25), 72, 1.0, 88),
                              (147, (0.65, -0.12, RZ + 1.40), 75, 1.0, 88),
                              (163, (1.75, -0.12, RZ + 1.50), 75, 1.0, 88),
                              (168, (2.10, -0.12, RZ + 1.52), 75, 1.0, 88)):
        youth_key(f, c, pitch=lean, yaw=yw, sz=s)

    # ===== 白猿：动作小、出手晚、省力，但每一下都是它主动处理；每个动作前有预备，后有过冲回稳 =====
    ape_key(1, x=A0X, pitch=-2, twist=16)                                   # 棍拎在身侧
    ape_key(8, x=A0X, pitch=0, twist=24, roll=3)                            # 看着他扑来，身子往后一拧（预备）
    ape_key(13, x=A0X, pitch=-5, twist=-10, roll=-2, interp="LINEAR")       # 一拧身把棍横过来
    ape_key(15, x=A0X, pitch=-3, twist=-6, interp="LINEAR")
    ape_key(16, x=A0X, pitch=-7, twist=-6, interp="LINEAR")                 # 撞上，上身被顶得往后一仰
    ape_key(18, x=A0X, pitch=-10, twist=-8, sz=0.95)                        # 往下一沉吃住（预备）
    ape_key(21, x=A0X + 0.30, pitch=12, twist=6, roll=-3, sz=1.0, interp="LINEAR")  # 往前跟一步，双手握棍一顶
    ape_key(24, x=A0X + 0.30, pitch=5, twist=3)
    ape_key(32, x=AX, pitch=0, twist=0)                                      # 收回、退半步站定
    ape_key(48, x=AX, pitch=2, twist=-2)
    # 镜4–6 前空翻越顶：一沉蓄力 → 蹬起 → 重力抛物线飞过苏云头顶（顶点离他头顶 2 米多），空中抱紧翻一整圈，
    #   后半程拧身转过来 → 一侧先着地、往前滑半步、压到最低、弹起过冲、回稳
    ape_key(53, pitch=14, sz=0.84)
    ape_key(57, pitch=18, sz=0.80, interp="LINEAR")
    ape_key(59, x=AX + 0.20, z=RZ + 0.30, pitch=24, sz=1.06, interp="LINEAR")
    T0, T1 = 59, 96
    for f in range(T0 + 1, T1):
        u = (f - T0) / float(T1 - T0)
        z = RZ + 0.30 * (1 - u) + 4 * 3.25 * u * (1 - u)
        x = lerp(AX + 0.20, ALX, u)
        pch = 24 + 336 * (3 * u * u - 2 * u * u * u)
        yaw = E - 180 * smooth((u - 0.42) / 0.30)       # v23：越过他头顶的同时就拧身，落地前已经正面朝着苏云
        sq = 1.0 - 0.10 * smooth((u - 0.15) / 0.20) * (1 - smooth((u - 0.70) / 0.15))
        ape_key(f, x=x, z=z, yaw=yaw, pitch=pch, roll=-8 * math.sin(math.pi * u), sz=sq, interp="LINEAR")
    ape_key(96, x=ALX, z=RZ, yaw=W, pitch=368, roll=10, sz=0.95, interp="LINEAR")        # 一侧先着地
    ape_key(98, x=ALX + 0.15, yaw=W, pitch=376, roll=2, sz=0.86)                        # 另一侧落下，往前滑
    ape_key(101, x=ALX + 0.30, yaw=W, pitch=384, roll=0, sz=0.78)                       # 压到最低
    ape_key(105, x=ALX + 0.35, yaw=W, pitch=374, sz=0.92)
    ape_key(109, x=ALX + 0.35, yaw=W, pitch=364, sz=1.03)                               # 弹起过冲
    ape_key(112, x=ALX + 0.35, yaw=W, pitch=368, twist=-6, sz=1.0)                      # 回稳，棍横起来
    ape_key(115, x=ALX + 0.35, yaw=W, pitch=368, twist=-8, sz=1.0)
    # 镜7 是苏云单人镜头：白猿在镜头背后，仰拍时画面顶会扫到它，这一镜里不显示
    for part in ("Hips", "ChestBox", "Head", "Eye"):
        pv.key_hide(bpy.data.objects[f"CHR_白猿_图1_{part}"], [(1, False), (CUTS[-1], True)], viewport=True)
    apply_overlap()
    bpy.context.scene.frame_set(1)


def _rot_at(ob, f):
    r = [ob.rotation_euler[i] for i in range(3)]
    for fc in pv._fcurves(ob):
        if fc.data_path == "rotation_euler":
            r[fc.array_index] = fc.evaluate(f)
    return r


def apply_overlap():
    """胸超前、头滞后：按身体转动的速度自动键 Chest 和 Neck 的附加转动（逐帧，限幅），读起来身体能拧、头慢半拍。"""
    pairs = [("CHR_白猿_图1", bpy.data.objects["CHR_白猿_图1_Pivot"], bpy.data.objects["CHR_白猿_图1"]),
             ("CHR_苏云_图2", bpy.data.objects["CTRL_苏云"], None)]
    for name, body, yaw_ob in pairs:
        chest = bpy.data.objects[f"{name}_Chest"]
        neck = bpy.data.objects[f"{name}_Neck"]

        def S(f):
            r = _rot_at(body, f)
            if yaw_ob is not None:                      # 白猿：身体转在 Pivot，朝向转在根
                return [r[0], r[1], r[2] + _rot_at(yaw_ob, f)[2]]
            return [r[0], r[1], r[2]]                    # 苏云：全部在 CTRL（pitch、roll、yaw）
        for f in range(1, F_END + 1):
            a, b, c3 = S(f), S(f - 2), S(f - 3)
            lead = [clamp(0.30 * (a[i] - b[i]), D(10)) for i in range(3)]
            lag = [clamp(-0.50 * (a[i] - c3[i]), D(16)) for i in range(3)]
            K(chest, f, rot=tuple(lead), interp="LINEAR")
            K(neck, f, rot=tuple(lag), interp="LINEAR")


# ---------- 相机 ----------

def _ctrl_at(f):
    return pv._loc_at(bpy.data.objects["CTRL_苏云"], f)


def _ape_at(f):
    return pv._loc_at(bpy.data.objects["CHR_白猿_图1"], f)


def _spline(keys, f):
    """keys = [(帧, 值)]，值是数或 Vector；三次 Hermite、切线按相邻键差分（Catmull-Rom 式），过键时速度连续，不再分段起停。"""
    if f <= keys[0][0]:
        return keys[0][1]
    if f >= keys[-1][0]:
        return keys[-1][1]
    n = len(keys)
    for i in range(n - 1):
        f0, p0 = keys[i]
        f1, p1 = keys[i + 1]
        if f0 <= f <= f1:
            h = float(f1 - f0)
            t = (f - f0) / h
            m0 = (p1 - p0) / h if i == 0 else (p1 - keys[i - 1][1]) / float(f1 - keys[i - 1][0])
            m1 = (p1 - p0) / h if i + 1 == n - 1 else (keys[i + 2][1] - p0) / float(keys[i + 2][0] - f0)
            t2, t3 = t * t, t * t * t
            return (p0 * (2 * t3 - 3 * t2 + 1) + m0 * h * (t3 - 2 * t2 + t)
                    + p1 * (-2 * t3 + 3 * t2) + m1 * h * (t3 - t2))
    return keys[-1][1]


def _jolt(f, jolts):
    off = Vector((0.0, 0.0, 0.0))
    for fj, v in jolts:
        if f >= fj:
            off += Vector(v) * math.exp(-(f - fj) / 1.6) * math.cos((f - fj) * 1.9)
    return off


def _drift(f, idx, amp=1.0):
    """手持的低频漂移（几种频率叠加，每台机位相位不同）。"""
    ph = idx * 1.7
    return V(0.045 * math.sin(f * 0.19 + ph) + 0.02 * math.sin(f * 0.47 + ph * 2.1),
             0.035 * math.sin(f * 0.15 + ph * 1.3) + 0.015 * math.sin(f * 0.53 + ph),
             0.035 * math.sin(f * 0.23 + ph * 0.7) + 0.015 * math.sin(f * 0.61 + ph * 1.9)) * amp


def shot(idx, lens, rig_fn, aim_fn, roll_keys, jolts=(), hand=1.0):
    """一镜一台相机，逐帧键：样条路径 + 碰撞一震 + 低频漂移；再挂高频手持抖动（位置和画面旋转）。"""
    f0 = CUTS[idx - 1]
    f1 = CUTS[idx] - 1 if idx < len(CUTS) else F_END
    cam, rig = pv.camera_with_rig(f"CAM_S{idx}", lens=lens, rig="dolly", loc=tuple(rig_fn(f0)))
    aim = pv.aim_to(cam, tuple(aim_fn(f0)))
    for f in range(f0, f1 + 1):
        K(rig, f, loc=tuple(Vector(rig_fn(f)) + _jolt(f, jolts) + _drift(f, idx, hand)), interp="LINEAR")
        K(aim, f, loc=tuple(aim_fn(f)), interp="LINEAR")
        roll = _spline(roll_keys, f) + 2.2 * hand * math.sin(f * 0.31 + idx)
        pv.key_rig(cam, f, rot_z=D(roll), interp="LINEAR")
    pv.shake(rig, amp=0.05 * hand, scale=2.5)
    pv.shake(cam, amp=D(2.5 * hand), scale=2.5, channel="rotation_euler", indices=(2,))
    pv.set_marker_camera(f0, cam, name=f"S{idx}")
    return cam


def build_cams():
    """9 镜：远景打底，关键几拍切特写和新机位；超广角、贴近、斜角，全程手持、碰撞一震。侧面机位都在屋脊南侧。全部原速。"""
    c = _ctrl_at
    P_HIT = V(-2.35, 0.0, RZ + 3.00)

    # 镜1 远景飞入：南侧低机位仰拍，往前推、往左摇着迎他，白猿画左、苏云从画右上方飞进来
    shot(1, 13, lambda f: _spline([(1, V(-0.70, -2.60, RZ + 1.15)), (15, V(-1.15, -2.00, RZ + 1.55))], f),
         lambda f: _spline([(1, V(-0.60, 0.0, RZ + 3.60)), (15, V(-1.90, 0.0, RZ + 3.00))], f),
         [(1, 10.0), (15, 3.0)])

    # 镜2 撞棍大特写：镜头贴在撞击点旁，撞上被震得往后一弹；白猿一沉一顶时镜头跟着往前拱，苏云被顶飞时甩出去追他
    shot(2, 16, lambda f: _spline([(16, V(-2.02, -0.78, RZ + 2.82)), (18, V(-1.95, -0.92, RZ + 2.78)),
                                   (21, V(-1.85, -0.85, RZ + 2.84)), (25, V(-1.55, -1.15, RZ + 2.60)),
                                   (31, V(-1.20, -1.30, RZ + 2.30))], f),
         lambda f: (P_HIT + V(0.25 * smooth((f - 18) / 3.0), 0.0, 0.0)).lerp(c(f) + V(-0.3, 0.0, 0.0), smooth((f - 21) / 6.0)),
         [(16, 12.0), (21, 2.0), (31, -12.0)], jolts=[(16, (0.12, -0.16, 0.08)), (21, (0.08, -0.06, 0.05))])

    # 镜3 苏云近景：镜头在他南侧晚半拍跟着他落地往后滑，刹住、压低一震，他抬眼盯着白猿
    def r3(f):
        q = c(f - 2) + V(-0.60, -1.50, 0.30)
        q.z = max(q.z, roof_z(q.y) + 0.25)
        return q

    shot(3, 18, r3, lambda f: c(f) + V(0.0, 0.0, 0.45), [(32, 12.0), (40, -4.0), (49, 10.0)],
         jolts=[(35, (0.0, 0.0, 0.06)), (44, (0.0, 0.0, 0.04))])

    # 镜4 贴瓦低机位：两人之间往上仰；苏云从画右低身滑扫过来，白猿在画左一沉、蹬离瓦面，镜头跟着往上仰
    shot(4, 14, lambda f: _spline([(50, V(-1.95, -1.60, roof_z(1.60) + 0.18)), (65, V(-2.45, -1.70, roof_z(1.70) + 0.24))], f),
         lambda f: _spline([(50, V(-2.10, 0.0, RZ + 0.90)), (58, V(-2.85, 0.0, RZ + 1.20)), (65, V(-2.85, 0.0, RZ + 2.70))], f),
         [(50, -12.0), (65, -2.0)], jolts=[(54, (0.0, -0.04, 0.05)), (59, (0.0, 0.0, 0.07))])

    # 镜5 南侧远一点仰拍：苏云压在画面下方，白猿抱紧翻过他头顶、两人之间有空隙；镜头往右摇着跟它落向另一边
    shot(5, 12, lambda f: _spline([(66, V(-2.30, -3.60, RZ + 0.65)), (93, V(-0.30, -3.70, RZ + 0.75))], f),
         lambda f: (c(f) + V(0.0, 0.0, 0.30)).lerp(_ape_at(f) + V(0.0, 0.0, 1.90), 0.45),
         [(66, -8.0), (79, 6.0), (93, 14.0)])

    # 镜6 落地特写：镜头贴着瓦面，它一侧先着地、往前滑、压到最低、弹起；镜头跟着它起身往上摇、往上抬
    shot(6, 16, lambda f: _spline([(94, V(ALX - 0.75, -1.25, roof_z(1.25) + 0.15)), (115, V(ALX - 0.85, -1.35, roof_z(1.35) + 0.60))], f),
         lambda f: _spline([(94, V(ALX + 0.10, 0.0, RZ + 1.00)), (98, V(ALX + 0.25, 0.0, RZ + 0.60)),
                            (109, V(ALX + 0.35, 0.0, RZ + 1.40)), (115, V(ALX + 0.35, 0.0, RZ + 1.90))], f),
         [(94, 10.0), (115, 2.0)], jolts=[(96, (0.0, 0.0, 0.12)), (98, (0.0, 0.0, 0.08))])

    # 镜7 苏云单人：南侧贴屋面低机位往上仰，荷兰角；他扑出去，镜头往右摇着追，跟不上，他前半身冲出画右
    shot(7, 20, lambda f: _spline([(116, V(-1.05, -1.45, RZ - 0.30)), (168, V(-0.83, -1.50, RZ - 0.28))], f),
         lambda f: _spline([(116, V(-1.90, 0.0, RZ + 0.65)), (123, V(-1.60, 0.0, RZ + 0.80)),
                            (139, V(-0.95, -0.05, RZ + 1.10)), (163, V(-0.55, -0.05, RZ + 1.45)), (168, V(-0.45, -0.05, RZ + 1.50))], f),
         [(116, -14.0), (129, -18.0), (168, -25.0)], jolts=[(117, (0.0, 0.0, 0.06)), (122, (-0.06, 0.0, 0.05))])


# ---------- 总装 ----------

def build_all():
    clear()
    hide_defaults()
    sc = bpy.context.scene
    if "previz_retimed" in sc:
        del sc["previz_retimed"]
    ws = pv.setup_workbench(res=(2518, 1080), fps=FPS, sun_dir=SUN_DIR, frame_range=(1, F_END), bg=SKY_C,
                            shadow_intensity=0.45, follow_camera=True)
    build_env()
    build_chars()
    animate()
    build_cams()
    sc.frame_set(1)
    return {"workbench": ws}


def review_frames():
    ends = CUTS[1:] + [F_END + 1]
    out = []
    for st, e in zip(CUTS, ends):
        out += [st, (st + e - 1) // 2, e - 1]
    return out


def stills(out_dir, frames=None, res_pct=25):
    import os
    os.makedirs(out_dir, exist_ok=True)
    done = []
    for f in (frames or review_frames()):
        p = os.path.join(out_dir, f"f{f:04d}.png")
        pv.still(p, cam=None, frame=f, res_pct=res_pct)
        done.append(p)
    return done


def _pts(dg, name):
    ob = bpy.data.objects[name].evaluated_get(dg)
    return [ob.matrix_world @ v.co for v in ob.data.vertices]


def clearance():
    """穿帮自检（顶点粗估）：两人身体顶点最近距离、各自最低点比屋面高多少、相机比屋面高多少。"""
    sc = bpy.context.scene
    out = {}
    for f in range(1, sc.frame_end + 1):
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ypts = sum((_pts(dg, f"CHR_苏云_图2_{p}") for p in ("Hips", "ChestBox", "Head")), [])
        apts = sum((_pts(dg, f"CHR_白猿_图1_{p}") for p in ("Hips", "ChestBox", "Head")), [])
        best = min((p - q).length for p in apts for q in ypts)
        cam = sc.camera.matrix_world.translation
        out[f] = {"youth_ape": round(best, 3),
                  "youth_floor": round(min(q.z - roof_z(q.y) for q in ypts), 3),
                  "ape_floor": round(min(q.z - roof_z(q.y) for q in apts), 3),
                  "cam_floor": round(cam.z - roof_z(cam.y), 3)}
    sc.frame_set(1)
    return out

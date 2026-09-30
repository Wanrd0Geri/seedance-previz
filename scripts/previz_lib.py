# -*- coding: utf-8 -*-
"""seedance-previz 帮助函数库：纯 bpy；frame_stats、compare_cams 另用 Blender 自带的 numpy。

在 Higgs 的 bl_execute 里用（后台 Blender 会话）：
    import sys, os, importlib
    d = os.path.join(os.path.expanduser("~"), "Documents", "Codex", "seedance-previz", "scripts")
    if d not in sys.path: sys.path.insert(0, d)
    import previz_lib as pv; importlib.reload(pv)
    pv.setup_workbench(res=(1280, 544), fps=24, sun_dir=(-0.6, 0.75, 0.3))

命令行自测（只在空白会话里跑，会建场景，渲图和两段 mp4 到 <系统临时目录>/seedance-previz-selftest/）：
    python3 -X utf8 selftest.py        # 跨平台入口，自己找 Blender
    Blender --background --factory-startup --python previz_lib.py     # 等价的直接写法

约定：米制，Z 向上，角色正面 = 本地 -Y。新建的物体都进 PREVIZ 集合；
同名物体如果不在 PREVIZ 集合里，函数直接报错，不覆盖用户的东西。
"""
import bisect
import math
import os
import re
import tempfile
import sys

import bmesh
import bpy
from mathutils import Vector

COLL = "PREVIZ"
GREY = (0.5, 0.5, 0.5)
# Blender 5.2.2 实测：Workbench 默认摄影棚光（Default）开世界坐标时，
# studiolight_rotate_z = 0 的主光方位约 -108°（从 +X 逆时针量），rotate_z 加大 = 光顺时针转。
STUDIO_AZ0_DEG = -108.0
# 四肢命名：和 check_export.py 共用 is_limb_name。正则只管英文（_ArmL、_Leg_R、.Wing、_Hands）；
# 中文按 _ - . 空格切段，某一段整段是四肢词才算（"展臂法相""盘腿座"不算）
LIMB_RE = re.compile(r"(?i)(?:^|[_\-. ])(?:arm|leg|wing|hand|foot)s?(?:[_\-. ]?[lr])?(?:$|[_\-. \d])")
LIMB_ZH = frozenset(("臂", "左臂", "右臂", "手臂", "上臂", "前臂", "腿", "左腿", "右腿", "大腿", "小腿",
                     "翅", "翅膀", "左翅", "右翅", "手", "左手", "右手", "脚", "左脚", "右脚"))
_SEG_RE = re.compile(r"[_\-. ]+")
# 审看版字幕字体（带中文）：按平台找系统自带字体，都没有就返回 None（burn_subs 退回 Blender 默认字体）
def _default_font():
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    for p in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",           # macOS
              os.path.join(windir, "Fonts", "msyh.ttc"),                        # Windows 微软雅黑
              os.path.join(windir, "Fonts", "msyh.ttf"),
              os.path.join(windir, "Fonts", "simhei.ttf"),
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):        # Linux
        if os.path.isfile(p):
            return p
    return None


FONT = _default_font()
# 会渲出来、能用物体色（ob.color）涂色的物体类型
PAINTABLE = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD'}
# frame_stats 掩码颜色（线性值；比对时过 sRGB）：角色按序取色，其他物体中灰，分批时别批的角色深灰，背景黑
MASK_COLORS = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 0.0), (1.0, 0.0, 1.0),
               (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 0.5, 0.0), (0.5, 0.0, 1.0), (0.0, 1.0, 0.5)]
MASK_ENV = (0.5, 0.5, 0.5)
MASK_OTHER = (0.2, 0.2, 0.2)
# 光带锥度：尾细头圆（沿曲线 0 → 1 的半径系数）
TAPER = [(0.0, 0.06), (0.35, 0.3), (0.7, 0.7), (0.92, 1.0), (1.0, 1.0)]


# ---------- 内部工具 ----------

def _scene():
    return bpy.context.scene


def _coll():
    c = bpy.data.collections.get(COLL)
    if c is None:
        c = bpy.data.collections.new(COLL)
    sc = _scene()
    if c.name not in {x.name for x in sc.collection.children_recursive}:
        sc.collection.children.link(c)
    return c


def _owned(ob):
    c = bpy.data.collections.get(COLL)
    return c is not None and ob.name in c.objects


def _remove(ob):
    data = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Camera):
            bpy.data.cameras.remove(data)
        elif isinstance(data, bpy.types.Light):
            bpy.data.lights.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)


def _fresh(name):
    """重跑时删掉本库之前建的同名物体和它的部件（本库建的、名字以 name_ 开头的子物体）；
    别的子物体（如挂在角色上的 AIM）先摘下、保持原位，返回给调用方挂回新物体。
    同名物体不是本库建的就报错。"""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return []
    if not _owned(ob):
        raise ValueError(f"{name} 已存在且不在 {COLL} 集合里：不覆盖用户的物体，换个名字")
    parts = [c for c in ob.children_recursive if _owned(c) and c.name.startswith(name + "_")]
    doomed = set(parts) | {ob}
    keep = []
    if ob.children:
        bpy.context.view_layer.update()   # 刚建的物体世界矩阵还没算，先刷新
    for c in list(ob.children_recursive):
        if c in doomed or c.parent not in doomed:
            continue
        # 用存着的数据算相对位置，不用 matrix_local（它依赖可能过期的世界矩阵）
        local = (c.matrix_parent_inverse @ c.matrix_basis) if c.parent == ob else None
        mw = c.matrix_world.copy()
        c.parent = None
        c.matrix_world = mw
        if local is not None:
            keep.append((c, local))
    for c in parts:
        _remove(c)
    _remove(ob)
    return keep


def _reattach(ob, keep):
    """把 _fresh 摘下的子物体挂回新建的同名物体，保持原来的相对位置。"""
    for c, local in keep:
        c.parent = ob
        c.matrix_parent_inverse.identity()
        c.matrix_basis = local


def _rgba(color):
    c = tuple(color)
    return c if len(c) == 4 else (c[0], c[1], c[2], 1.0)


def _mesh_obj(name, bm, loc, color, rot=(0.0, 0.0, 0.0)):
    keep = _fresh(name)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    _coll().objects.link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    ob.color = _rgba(color)
    _reattach(ob, keep)
    return ob


def _empty(name, loc=(0.0, 0.0, 0.0), size=1.0):
    keep = _fresh(name)
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = size
    _coll().objects.link(ob)
    ob.location = loc
    _reattach(ob, keep)
    return ob


def _parent(child, parent):
    """父子关系，子物体坐标按父物体本地坐标写（父逆矩阵保持单位阵）。"""
    child.parent = parent
    child.matrix_parent_inverse.identity()


def _fcurves(idb):
    """Blender 5.x 动作槽写法；老版本退回 action.fcurves。"""
    ad = getattr(idb, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    act = ad.action
    slot = getattr(ad, "action_slot", None)
    if slot is not None and hasattr(act, "layers"):
        return [fc for layer in act.layers for strip in layer.strips
                for cb in strip.channelbags if cb.slot_handle == slot.handle
                for fc in cb.fcurves]
    return list(getattr(act, "fcurves", []))


def _all_fcurves(act):
    """一个动作里的全部 F 曲线，不分槽位（5.x：layers → strips → channelbags → fcurves；没有 layers 就退回 action.fcurves）。"""
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for cb in getattr(strip, "channelbags", []):
                out.extend(cb.fcurves)
    if not out:
        out = list(getattr(act, "fcurves", []))
    return out


def _obj(x):
    """物体或物体名 → 物体。"""
    if isinstance(x, bpy.types.Object):
        return x
    ob = bpy.data.objects.get(x)
    if ob is None:
        raise KeyError(f"找不到物体 {x}")
    return ob


def _geom_parts(root):
    """根物体和它全部子孙里会渲出来的几何部件（网格、曲线等；空物体不算）。"""
    return [o for o in [root] + list(root.children_recursive) if o.type in PAINTABLE]


def _chr_roots(prefix="CHR_"):
    """场景里全部角色根物体：名字带前缀、上面没有同前缀的父物体（含隐藏的）。"""
    out = []
    for ob in _scene().objects:
        if not ob.name.startswith(prefix):
            continue
        p = ob.parent
        while p is not None and not p.name.startswith(prefix):
            p = p.parent
        if p is None:
            out.append(ob)
    return sorted(out, key=lambda o: o.name)


def _drop_keys(idb, data_path, a=None, b=None, index=None):
    """删掉 idb（物体或数据块）上 data_path 在第 a–b 帧之间的键；a、b 为 None 就不限。返回删了几个。"""
    n = 0
    for fc in _fcurves(idb):
        if fc.data_path != data_path or (index is not None and fc.array_index != index):
            continue
        for kp in reversed(list(fc.keyframe_points)):
            x = kp.co[0]
            if (a is None or x >= a - 1e-6) and (b is None or x <= b + 1e-6):
                fc.keyframe_points.remove(kp, fast=True)
                n += 1
        fc.update()
    return n


def _set_interp(idb, paths, interp):
    """idb 上 data_path 以 paths 里任一开头的曲线，全部键改成 interp。"""
    for fc in _fcurves(idb):
        if fc.data_path.startswith(tuple(paths)):
            for kp in fc.keyframe_points:
                kp.interpolation = interp


def _loc_at(ob, frame):
    """物体在某帧的 location：有位置键就按曲线求值，没有就是当前值。"""
    loc = ob.location.copy()
    for fc in _fcurves(ob):
        if fc.data_path == "location" and len(fc.keyframe_points):
            loc[fc.array_index] = fc.evaluate(frame)
    return loc


def _lerp_keys(v, f):
    """v 是数就原样返回；是 [(帧, 值), …] 就按帧线性插值，两头之外取端值。"""
    if isinstance(v, (int, float)):
        return float(v)
    pts = sorted((float(a), float(b)) for a, b in v)
    if f <= pts[0][0]:
        return pts[0][1]
    for (fa, va), (fb, vb) in zip(pts, pts[1:]):
        if f <= fb:
            return va + (vb - va) * (f - fa) / max(fb - fa, 1e-9)
    return pts[-1][1]


def _srgb(c):
    """线性值 → sRGB 显示值（Standard 视图变换下渲出来的像素值）。"""
    return tuple(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055 for v in c)


def _png_on(r):
    """临时把输出改成 png / RGB / 8 位，返回旧设置给 _png_off 恢复。"""
    im = r.image_settings
    saved = (getattr(im, "media_type", None), im.file_format, im.color_mode, im.color_depth)
    if hasattr(im, "media_type"):
        im.media_type = 'IMAGE'
    im.file_format = 'PNG'
    im.color_mode = 'RGB'
    im.color_depth = '8'
    return saved


def _png_off(r, saved):
    im = r.image_settings
    for attr, v in zip(("media_type", "file_format", "color_mode", "color_depth"), saved):
        if v is None or not hasattr(im, attr):
            continue
        try:
            setattr(im, attr, v)
        except (TypeError, ValueError):
            pass


def _governing_marker(sc, frame):
    """管这一帧的相机标记：≤ frame 的最后一个绑了相机的标记；都在后面就取最早的那个（和 Blender 切相机的规则一样）。"""
    ms = [m for m in sc.timeline_markers if m.camera is not None]
    if not ms:
        return None
    before = [m for m in ms if m.frame <= frame]
    return max(before, key=lambda m: m.frame) if before else min(ms, key=lambda m: m.frame)


def is_limb_name(name):
    """名字像四肢就返回 True（check_export 也用它，两处一致）。
    英文：_Arm、_ArmL、_Leg_R、.Wing、_Hands、_Foot 这类分段词（正则 LIMB_RE）；
    中文：按 _ - . 空格切开，某一段整段是四肢词（臂、左臂、腿、大腿、翅膀、手、左手、脚……）才算。
    "展臂法相""盘腿座""曲伯双手"不算，_Lap（坐姿的腿部块）不算。"""
    if LIMB_RE.search(name):
        return True
    return any(seg in LIMB_ZH for seg in _SEG_RE.split(name))


# ---------- 几何体 ----------

def mk_box(name, size=(1.0, 1.0, 1.0), loc=(0.0, 0.0, 0.0), color=GREY,
           rot=(0.0, 0.0, 0.0), bottom=True):
    """方块。size 是 (宽 X, 深 Y, 高 Z) 米；bottom=True 时原点在底面中心（放地上就写地面坐标）。"""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1],
                       v.co.z * size[2] + (size[2] / 2.0 if bottom else 0.0)))
    return _mesh_obj(name, bm, loc, color, rot)


def mk_sphere(name, radius=1.0, loc=(0.0, 0.0, 0.0), color=GREY,
              scale=(1.0, 1.0, 1.0), segs=24, rings=12):
    """球，原点在球心。scale 压扁成云：如 (2, 1, 0.2)。"""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    for v in bm.verts:
        v.co = Vector((v.co.x * scale[0], v.co.y * scale[1], v.co.z * scale[2]))
    ob = _mesh_obj(name, bm, loc, color)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def mk_cyl(name, radius=0.5, depth=1.0, loc=(0.0, 0.0, 0.0), color=GREY,
           rot=(0.0, 0.0, 0.0), bottom=True, verts=24):
    """圆柱，轴向本地 Z；bottom=True 时原点在底面圆心。"""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts,
                          radius1=radius, radius2=radius, depth=depth)
    if bottom:
        for v in bm.verts:
            v.co.z += depth / 2.0
    return _mesh_obj(name, bm, loc, color, rot)


def roof(name, width, depth, height, loc=(0.0, 0.0, 0.0), color=(0.3, 0.3, 0.32), rot_z=0.0):
    """四坡屋顶（庑殿式）：底面 width×depth 在 loc 的高度（檐口），正脊顺长边，高 height。
    出檐就把 width/depth 放大；方形底面自动变攒尖。"""
    w2, d2 = width / 2.0, depth / 2.0
    bm = bmesh.new()
    base = [bm.verts.new(p) for p in ((-w2, -d2, 0), (w2, -d2, 0), (w2, d2, 0), (-w2, d2, 0))]
    if width >= depth:
        r = (width - depth) / 2.0
        ra, rb = bm.verts.new((-r, 0, height)), bm.verts.new((r, 0, height))
        faces = [(base[0], base[1], rb, ra), (base[2], base[3], ra, rb),
                 (base[1], base[2], rb), (base[3], base[0], ra)]
    else:
        r = (depth - width) / 2.0
        ra, rb = bm.verts.new((0, -r, height)), bm.verts.new((0, r, height))
        faces = [(base[1], base[2], rb, ra), (base[3], base[0], ra, rb),
                 (base[0], base[1], ra), (base[2], base[3], rb)]
    for f in faces:
        bm.faces.new(f)
    bm.faces.new(list(reversed(base)))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh_obj(name, bm, loc, color, (0.0, 0.0, rot_z))


def stairs(name, width, run, rise, steps, loc=(0.0, 0.0, 0.0), color=(0.62, 0.62, 0.64), rot_z=0.0):
    """整段台阶合成一个物体：宽 width，水平进深 run，总高 rise，steps 级，默认朝 +Y 往上走。
    原点在第一级前沿底边中点。"""
    d, h = run / steps, rise / steps
    prof = [(0.0, 0.0)]
    for i in range(steps):
        prof += [(i * d, (i + 1) * h), ((i + 1) * d, (i + 1) * h)]
    prof.append((run, 0.0))
    bm = bmesh.new()
    vs = [bm.verts.new((-width / 2.0, y, z)) for y, z in prof]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    moved = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=moved, vec=(width, 0.0, 0.0))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh_obj(name, bm, loc, color, (0.0, 0.0, rot_z))


# ---------- 角色躯体代理 ----------

def _lap_bm(height):
    """坐姿的腿部：从臀部往前（本地 -Y）伸的一整块，像长袍盖着腿；截面圆角八边形。
    长 0.30、宽 0.21、厚 0.10 身高，不做两条腿（用户偏好）。"""
    L, w, h = 0.30 * height, 0.21 * height, 0.10 * height
    bm = bmesh.new()
    rings = []
    for y, sx, sz in ((0.0, 1.0, 1.0), (-0.75, 0.96, 0.92), (-1.0, 0.82, 0.78)):
        ring = []
        for k in range(8):
            a = 2.0 * math.pi * (k + 0.5) / 8.0
            ring.append(bm.verts.new((0.5 * w * sx * math.cos(a), y * L, 0.5 * h * sz * math.sin(a))))
        rings.append(ring)
    for ra, rb in zip(rings[:-1], rings[1:]):
        for k in range(8):
            bm.faces.new((ra[k], ra[(k + 1) % 8], rb[(k + 1) % 8], rb[k]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def torso_proxy(name, height, color, face_dir=(0.0, -1.0, 0.0), loc=(0.0, 0.0, 0.0),
                head_ratio=1.0 / 7.0, width_ratio=0.28, depth_ratio=0.65, pose="stand", lap_pitch=-50.0):
    """躯体代理：胶囊躯干 + 头球 + 嘴部小球，无四肢。返回根空物体（原点在脚底；坐姿在臀下）。
    name 用 CHR_<角色>_<图N>；height 米（身高）；face_dir 是脸朝的世界方向（嘴部小球标朝向）。
    头身比 head_ratio 默认 1/7，猿类或 Q 版可改 1/5～1/4。
    pose="sit"：头顶在 0.55 × 身高，躯干按这个高度做、头球和嘴球跟着降，加一块合在一起的腿部 <name>_Lap
    （从臀部往前伸，lap_pitch 负值 = 往下斜，默认 -50° 顺着坐面往下），不做两条腿（用户偏好）。
    根物体写 previz_height（头顶高）、previz_stature（身高）、previz_pose。"""
    if pose not in ("stand", "sit"):
        raise ValueError("pose 只能是 stand / sit")
    if is_limb_name(name):
        raise ValueError(f"代理名 {name} 像四肢命名：check_export 会当成四肢，换个名字")
    root = _empty(name, loc, size=height * 0.15)
    fx, fy = face_dir[0], face_dir[1]
    if abs(fx) + abs(fy) < 1e-9:
        raise ValueError("face_dir 要有水平分量")
    root.rotation_euler = (0.0, 0.0, math.atan2(fx, -fy))  # 本地 -Y 转到 face_dir

    top = height if pose == "stand" else 0.55 * height     # 头顶高
    head_d = height * head_ratio
    rh = head_d / 2.0
    rb = height * width_ratio / 2.0
    body_h = top - head_d + 0.15 * head_d          # 躯干顶稍微插进头球
    cyl = max(body_h - 2.0 * rb, 0.0)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=13, radius=rb)
    for v in bm.verts:
        v.co.z += cyl / 2.0 if v.co.z > 0 else -cyl / 2.0
        v.co.y *= depth_ratio
        v.co.z += rb + cyl / 2.0
    body = _mesh_obj(f"{name}_Body", bm, (0.0, 0.0, 0.0), color)

    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=rh)
    head = _mesh_obj(f"{name}_Head", bm, (0.0, 0.0, top - rh), color)

    rm = rh * 0.42
    dark = tuple(c * 0.75 for c in _rgba(color)[:3])  # 同色相、同饱和度，暗一档
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=rm)
    muzzle = _mesh_obj(f"{name}_Muzzle", bm, (0.0, -rh * 0.85, top - rh * 1.1), dark)

    for part in (body, head, muzzle):
        for p in part.data.polygons:
            p.use_smooth = True
        _parent(part, root)
    if pose == "sit":
        lap = _mesh_obj(f"{name}_Lap", _lap_bm(height), (0.0, -0.03 * height, 0.055 * height), color,
                        (-math.radians(lap_pitch), 0.0, 0.0))
        _parent(lap, root)
    root["previz_height"] = top
    root["previz_stature"] = height
    root["previz_pose"] = pose
    return root


def key_hide(ob, frames_states):
    """[(帧, 是否隐藏), …] 键 hide_render。布尔键是常量插值：到下一个键之前一直保持，第一个键之前同第一个键。"""
    ob = _obj(ob)
    for f, state in frames_states:
        ob.hide_render = bool(state)
        ob.keyframe_insert("hide_render", frame=f)
    return ob


def set_alpha(root, frame, alpha, interp="BEZIER"):
    """给根物体下全部几何部件键物体色的 alpha（Workbench 物体色 alpha < 1 = 半透明）。返回部件数。"""
    parts = _geom_parts(_obj(root))
    for p in parts:
        c = p.color
        p.color = (c[0], c[1], c[2], float(alpha))
        p.keyframe_insert("color", index=3, frame=frame)
        for fc in _fcurves(p):
            if fc.data_path == "color" and fc.array_index == 3:
                for kp in fc.keyframe_points:
                    if abs(kp.co[0] - frame) < 0.5:
                        kp.interpolation = interp
    return len(parts)


def reveal(root, f_from, f_to, alpha=(0.0, 1.0), mid=None):
    """从无到有显形：f_from 之前 hide_render，f_from 起显示，透明度 alpha[0] → alpha[1]（f_to 到位）；
    mid=(帧, 值) 加一个中间键。只用于"从无到有"；变淡、缥缈、飘散不在白模里做，交给提示词（用户 2026-09-27）。"""
    root = _obj(root)
    parts = _geom_parts(root)
    for p in parts:
        key_hide(p, [(f_from - 1, True), (f_from, False)])
    set_alpha(root, f_from, alpha[0])
    if mid is not None:
        set_alpha(root, mid[0], mid[1])
    set_alpha(root, f_to, alpha[1])
    return {"parts": len(parts), "frames": [f_from, f_to]}


def stand_up(seated, standing, f0, dur=18):
    """坐着的人站起来：坐姿、站姿两个代理（torso_proxy pose="sit" / "stand"）换着显示。
    f0 之前只显示坐姿、f0 起只显示站姿（全部几何部件键 hide_render）。
    站姿根先摆在站起来以后的位置（调用时它的 location 就是终点；重跑前先清掉它的位置键），
    从"坐姿的 xy、z 降 drop"起身，dur 帧后到终点；终点 xy 可以和坐姿不同 = 边起边让位。
    drop = 站姿 previz_height − 坐姿 previz_height：起身那一帧两个头顶一样高。rot_z 沿用站姿根现值。
    换代理那一下会有跳变：交接卡风险栏写"真实动作是连贯起身"。"""
    seat, stand = _obj(seated), _obj(standing)
    if "previz_height" not in seat or "previz_height" not in stand:
        raise ValueError("坐姿、站姿都要是 torso_proxy 建的根物体（要有 previz_height）")
    drop = float(stand["previz_height"]) - float(seat["previz_height"])
    end = stand.location.copy()
    s = _loc_at(seat, f0)
    for p in _geom_parts(seat):
        key_hide(p, [(f0 - 1, False), (f0, True)])
    for p in _geom_parts(stand):
        key_hide(p, [(f0 - 1, True), (f0, False)])
    key_rig(stand, f0, loc=(s.x, s.y, s.z - drop), rot_z=stand.rotation_euler[2])
    key_rig(stand, f0 + dur, loc=tuple(end))
    return {"drop": round(drop, 4), "frames": [f0, f0 + dur]}


# ---------- 相机与运镜 ----------

def _base(name):
    return name[4:] if name.startswith("CAM_") else name


def shake(obj, amp=0.03, scale=10.0, channel="location", indices=(0, 1, 2)):
    """给物体的位置（或 rotation_euler）F 曲线挂 Noise 修改器，做手持抖动。
    amp：最大偏移（米或弧度）；scale：抖动快慢（帧，越大越慢）。重跑会先清掉旧的 Noise。"""
    sc = _scene()
    have = {(fc.data_path, fc.array_index) for fc in _fcurves(obj)}
    for i in indices:
        if (channel, i) not in have:
            obj.keyframe_insert(channel, index=i, frame=sc.frame_start)
    for fc in _fcurves(obj):
        if fc.data_path == channel and fc.array_index in indices:
            for m in [m for m in fc.modifiers if m.type == 'NOISE']:
                fc.modifiers.remove(m)
            m = fc.modifiers.new('NOISE')
            m.strength = amp * 2.0          # Noise 输出约 ±strength/2
            m.scale = scale
            m.phase = 1.0 + 3.7 * fc.array_index + (sum(map(ord, obj.name)) % 17)
    return obj


def camera_with_rig(name, lens=35.0, rig="dolly", loc=(0.0, -10.0, 1.6),
                    pivot=None, radius=10.0, height=1.6, clip_end=5000.0):
    """三层相机：RIG_<名>（控制器，键它）→ HEAD_<名>（aim_to 的 Track To 挂这层）→ CAM_<名>（自己的 Z 旋转 = roll）。
    rig：dolly 推轨（键 RIG 位移）| crane 摇臂（键 RIG 的 Z）| orbit 环绕（RIG 放在 pivot，键 RIG 的 Z 旋转）
         | handheld 手持（RIG 位置挂 Noise，相机 roll 挂小 Noise）。
    返回 (cam, rig_obj)。没有 aim_to 时相机默认水平看 +Y。"""
    if rig not in ("dolly", "crane", "orbit", "handheld"):
        raise ValueError("rig 只能是 dolly / crane / orbit / handheld")
    b = _base(name)
    if rig == "orbit":
        p = Vector(pivot if pivot is not None else loc)
        rig_ob = _empty(f"RIG_{b}", p, size=radius * 0.1)
        head = _empty(f"HEAD_{b}", (0.0, -radius, height), size=0.3)
    else:
        rig_ob = _empty(f"RIG_{b}", loc, size=0.5)
        head = _empty(f"HEAD_{b}", (0.0, 0.0, 0.0), size=0.3)
    rig_ob["previz_rig"] = rig
    _parent(head, rig_ob)
    head.rotation_euler = (math.pi / 2.0, 0.0, 0.0)   # 水平看 +Y

    keep = _fresh(f"CAM_{b}")
    cd = bpy.data.cameras.new(f"CAM_{b}")
    cd.lens = lens
    cd.sensor_width = 36.0
    cd.clip_start = 0.1
    cd.clip_end = clip_end
    cd.dof.use_dof = False
    cd.show_limits = cd.show_mist = cd.show_sensor = cd.show_name = False
    cam = bpy.data.objects.new(f"CAM_{b}", cd)
    _coll().objects.link(cam)
    _parent(cam, head)
    _reattach(cam, keep)
    cam.rotation_mode = 'XYZ'
    if rig == "handheld":
        shake(rig_ob, amp=0.03, scale=10.0)
        shake(cam, amp=math.radians(0.3), scale=14.0, channel="rotation_euler", indices=(2,))
    if _scene().camera is None:
        _scene().camera = cam
    return cam, rig_ob


def aim_to(cam, target, offset=(0.0, 0.0, 0.0)):
    """建 AIM_<名> 空物体并让相机朝向它（Track To 挂在 HEAD 层）。
    target 是物体：AIM 挂在它身上跟着走，offset 按它的本地坐标（如对准胸口 (0,0,1.3)）；
    target 是坐标：AIM 放在那里，键 AIM 的位置就是摇 / 俯仰。返回 AIM。"""
    head = cam.parent if cam.parent is not None and cam.parent.name.startswith("HEAD_") else cam
    b = _base(cam.name)
    aim = _empty(f"AIM_{b}", (0.0, 0.0, 0.0), size=0.3)
    if isinstance(target, bpy.types.Object):
        _parent(aim, target)
        aim.location = offset
    else:
        aim.location = Vector(target) + Vector(offset)
    for c in [c for c in head.constraints if c.name == "PREVIZ_AIM"]:
        head.constraints.remove(c)
    con = head.constraints.new('TRACK_TO')
    con.name = "PREVIZ_AIM"
    con.target = aim
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    return aim


def key_rig(obj, frame, loc=None, rot_z=None, interp="BEZIER"):
    """在 frame 键位置和 / 或 Z 旋转（弧度）。对控制器、AIM、角色根、相机（rot_z = roll）都能用。
    interp 管这个键到下一个键那一段：BEZIER 缓入缓出（默认），LINEAR 匀速，CONSTANT 跳变。"""
    paths = []
    if loc is not None:
        obj.location = loc
        obj.keyframe_insert("location", frame=frame)
        paths.append("location")
    if rot_z is not None:
        if obj.rotation_mode not in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'):
            raise ValueError(f"{obj.name} 是 {obj.rotation_mode} 旋转，key_rig 只键欧拉角")
        obj.rotation_euler[2] = rot_z
        obj.keyframe_insert("rotation_euler", index=2, frame=frame)
        paths.append("rotation_euler")
    for fc in _fcurves(obj):
        if fc.data_path in paths:
            for kp in fc.keyframe_points:
                if abs(kp.co[0] - frame) < 0.5:
                    kp.interpolation = interp
    return obj


def set_marker_camera(frame, cam, name=None):
    """在切点帧打时间轴标记并绑相机，渲染时到这一帧自动切到这台相机。"""
    sc = _scene()
    m = next((m for m in sc.timeline_markers if m.frame == frame), None)
    if m is None:
        m = sc.timeline_markers.new(name or cam.name, frame=frame)
    m.name = name or cam.name
    m.camera = cam
    if frame <= sc.frame_start:
        sc.camera = cam
    return m


def orbit(rig, aim, center, radius, a0, a1, f0, f1, z=0.0, screen_offset=0.0, aim_dist=None, aim_z=None):
    """环绕：以 center 为圆心、半径不变、匀速；f0 到 f1 每帧一个 LINEAR 键（第一帧就在动，最后一帧还在动，不留落幅）。
    角度从圆心的 +Y 方向起、往 +X 量（度），a0 → a1 线性；机位 = center + (R·sin θ, R·cos θ, z)，
    z 是相对 center.z 的高度，可以是数或 [(帧, 高), …]。
    aim 每帧放在"相机看向圆心的方向再偏 screen_offset 度"处，距相机 aim_dist（默认 = radius），高 aim_z（默认 = center.z）。
    screen_offset 正值 = 主体落在画右（E02S08 镜3c 用 12°，罗大娘在画右 0.53 处）；也可以是 [(帧, 度), …]，
    目标点匀速移向另一个人就靠它。aim_z 同样可以写 [(帧, 高), …]。
    rig 用 camera_with_rig 的 dolly 控制器；aim 用坐标型 AIM（aim_to(cam, (x, y, z))），别挂在角色上。
    先清掉 rig、aim 在 f0–f1 之间的位置键。返回 {"deg_per_s", "radius", "frames"}；
    转速超过 6°/s 时加 "note"（用户偏好近景跟拍 ≤6°/s）。"""
    rig, aim = _obj(rig), _obj(aim)
    if rig.get("previz_rig") == "orbit":
        raise ValueError(f"{rig.name} 是 orbit 控制器：pv.orbit 直接键机位，用 dolly 控制器")
    if rig.parent is not None or aim.parent is not None:
        raise ValueError("rig、aim 都不能有父物体：pv.orbit 按世界坐标键位置（aim 用 aim_to(cam, (x, y, z)) 建）")
    f0, f1 = int(f0), int(f1)
    if f1 <= f0:
        raise ValueError("f1 要大于 f0")
    sc = _scene()
    c = Vector(center)
    R = float(radius)
    ad = R if aim_dist is None else float(aim_dist)
    for ob in (rig, aim):
        _drop_keys(ob, "location", f0, f1)
    for f in range(f0, f1 + 1):
        u = (f - f0) / (f1 - f0)
        th = a0 + (a1 - a0) * u
        t = math.radians(th)
        p = c + Vector((R * math.sin(t), R * math.cos(t), _lerp_keys(z, f)))
        key_rig(rig, f, loc=tuple(p), interp="LINEAR")
        az = math.radians(-th + _lerp_keys(screen_offset, f))     # 看圆心 = -θ，再往左偏 → 主体落画右
        tgt = p + Vector((math.sin(az), -math.cos(az), 0.0)) * ad
        tgt.z = c.z if aim_z is None else _lerp_keys(aim_z, f)
        key_rig(aim, f, loc=tuple(tgt), interp="LINEAR")
    fps = sc.render.fps / (sc.render.fps_base or 1.0)
    dps = abs(a1 - a0) / ((f1 - f0) / fps)
    out = {"deg_per_s": round(dps, 3), "radius": R, "frames": [f0, f1]}
    if dps > 6.0:
        out["note"] = "超过 6°/s"
    return out


def _focus_target(cam, target):
    """对焦目标 → 物体或距离（米）。"AIM" = 这台相机的 AIM_<名>。"""
    if isinstance(target, (int, float)):
        return float(target)
    if isinstance(target, str) and target == "AIM":
        name = f"AIM_{_base(cam.name)}"
        ob = bpy.data.objects.get(name)
        if ob is None:
            raise KeyError(f"{cam.name} 没有 {name}：先 aim_to")
        return ob
    return _obj(target)


def rack_focus(cam, seq, ease=True):
    """移焦：seq = [(帧, 目标), …]，目标 = 物体 / 物体名 / "AIM" / 距离（米）。
    两点之间逐帧插值对焦距离（目标是物体就每帧算相机到它的距离；ease=True 用 smoothstep 缓入缓出），
    逐帧键在相机数据的 dof.focus_distance 上，focus_object 清空；先清掉这台相机旧的对焦距离键。
    要看得见虚实还得开景深：一般通过 apply_dof 的 ("RACK", seq) 调用。"""
    cam = _obj(cam)
    sc = _scene()
    pts = sorted(((int(f), _focus_target(cam, t)) for f, t in seq), key=lambda x: x[0])
    if len(pts) < 2:
        raise ValueError("移焦至少要两个点")
    d = cam.data.dof
    d.focus_object = None
    _drop_keys(cam.data, "dof.focus_distance")
    orig = (sc.frame_current, sc.frame_subframe, sc.camera)
    n = 0
    try:
        for f in range(pts[0][0], pts[-1][0] + 1):
            sc.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            cp = cam.evaluated_get(dg).matrix_world.translation

            def dist(t):
                return t if isinstance(t, float) else (t.evaluated_get(dg).matrix_world.translation - cp).length

            (fa, ta), (fb, tb) = pts[-2], pts[-1]
            for s0, s1 in zip(pts, pts[1:]):
                if s0[0] <= f <= s1[0]:
                    (fa, ta), (fb, tb) = s0, s1
                    break
            w = 1.0 if fb == fa else min(1.0, max(0.0, (f - fa) / (fb - fa)))
            if ease:
                w = w * w * (3.0 - 2.0 * w)
            da = dist(ta)
            d.focus_distance = da + (dist(tb) - da) * w
            cam.data.keyframe_insert("dof.focus_distance", frame=f)
            n += 1
    finally:
        sc.frame_set(orig[0], subframe=orig[1])
        sc.camera = orig[2]
    _set_interp(cam.data, ("dof.focus_distance",), 'LINEAR')
    return {"camera": cam.name, "frames": [pts[0][0], pts[-1][0]], "keys": n}


def apply_dof(table):
    """浅景深按镜头开：table = {相机或相机名: (光圈 f 值, 目标)}，
    目标 = "AIM"（这台相机的 AIM_<名>，它就在人脸上）| 物体或物体名 | 距离（米）| ("RACK", [(帧, 目标), …]) 移焦。
    打开 Workbench 景深总开关；表里的相机开 dof（光圈叶片 0 = 圆形散景），场景里其他相机关掉。
    表里的相机先清掉旧的对焦距离键（旧移焦键会顶掉固定对焦）。返回 {相机名: (f 值, 描述)}。
    近景、过肩 f/2–2.8；中景 f/2.8–4；全景不开（references/camera-moves.md 第 7 节）。"""
    sc = _scene()
    cams = {o.name: o for o in sc.objects if o.type == 'CAMERA'}
    tab = {}
    for k, v in table.items():
        ob = _obj(k)
        if ob.name not in cams:
            raise ValueError(f"{ob.name} 不是场景里的相机")
        tab[ob.name] = v
    sc.display.shading.use_dof = True
    out = {}
    for name, ob in sorted(cams.items()):
        d = ob.data.dof
        if name not in tab:
            d.use_dof = False
            continue
        fstop, target = tab[name]
        d.use_dof = True
        d.aperture_fstop = float(fstop)
        d.aperture_blades = 0
        _drop_keys(ob.data, "dof.focus_distance")
        if isinstance(target, (tuple, list)) and len(target) == 2 and target[0] == "RACK":
            rack_focus(ob, target[1])
            names = []
            for _f, t in sorted(target[1], key=lambda x: x[0]):
                t = _focus_target(ob, t)
                names.append(f"{t:g} m" if isinstance(t, float) else t.name)
            out[name] = (float(fstop), "RACK " + " → ".join(names))
            continue
        t = _focus_target(ob, target)
        if isinstance(t, float):
            d.focus_object = None
            d.focus_distance = t
            out[name] = (float(fstop), f"{t:g} m")
        else:
            d.focus_object = t
            out[name] = (float(fstop), t.name)
    return out


# ---------- 时间 ----------

def retime_map(segments):
    """整体重排时间的帧号映射 T(x)。segments = [(旧起, 旧止, 新起, 新止), …]：按旧起升序、首尾相接
    （旧止 + 1 = 下一段旧起，不接就报错），帧号含首尾，新段也要递增。
    段内线性（单帧段按平移）；两段之间的半帧、手柄线性过渡；第一段之前整体平移 新起₁ − 旧起₁，
    最后一段之后整体平移 新止_N − 旧止_N。
    例：[(1, 96, 1, 48), (97, 216, 49, 120)] → T(96)=48、T(97)=49、T(216)=120、T(217)=121、T(1540)=1444。"""
    segs = [tuple(float(v) for v in s) for s in segments]
    if not segs:
        raise ValueError("segments 不能为空")
    for i, (oa, ob, na, nb) in enumerate(segs):
        if ob < oa or nb < na:
            raise ValueError(f"第 {i + 1} 段起止颠倒：{tuple(segments[i])}")
        if i:
            pa, pb, qa, qb = segs[i - 1]
            if abs(pb + 1.0 - oa) > 1e-9:
                raise ValueError(f"第 {i} 段和第 {i + 1} 段不首尾相接：旧止 {pb:g} + 1 要等于下一段旧起 {oa:g}")
            if na <= qb:
                raise ValueError(f"第 {i + 1} 段新起 {na:g} 要大于上一段新止 {qb:g}")

    def T(x):
        x = float(x)
        if x < segs[0][0]:
            return x + segs[0][2] - segs[0][0]
        if x > segs[-1][1]:
            return x + segs[-1][3] - segs[-1][1]
        for i, (oa, ob, na, nb) in enumerate(segs):
            if oa <= x <= ob:
                return na + (x - oa) if ob == oa else na + (x - oa) * (nb - na) / (ob - oa)
            if i + 1 < len(segs) and ob < x < segs[i + 1][0]:
                na2 = segs[i + 1][2]
                return nb + (x - ob) * (na2 - nb) / (segs[i + 1][0] - ob)
        return x

    return T


def retime(segments, tag=None, round_keys=False):
    """整体重排时间（比如镜1、镜2 压短，后面整体提前）：全部动作的每个键和两个手柄过 T（retime_map），
    时间轴标记帧 = round(T)，scene.frame_end = round(T(frame_end))，frame_start 不动。
    物体、相机数据（焦距、移焦）、曲线数据（bevel）、材质的键都在 bpy.data.actions 里，一次全改；
    5.x 动作按 layers → strips → channelbags → fcurves 遍历（没有 layers 就退回 action.fcurves）。
    防重复：tag（默认由 segments 生成）记进 scene["previz_retimed"]（分号拼接），已经有就什么都不改，
    返回 {"skipped": True, "tag"}。round_keys=True：键的帧号四舍五入到整数，两个手柄平移同样的差；
    默认 False——逐帧 LINEAR 键（orbit、rack_focus、光带）压缩后落在半帧，保持小数才不会两键重叠
    （E02S08 实跑就是小数）。不管 NLA 条和蜡笔帧。
    返回 {"keys", "fcurves", "markers", "frame_end": [旧, 新], "tag"}。"""
    sc = _scene()
    T = retime_map(segments)
    if tag is None:
        tag = ",".join("%g-%g>%g-%g" % tuple(s) for s in segments)
    done = [t for t in str(sc.get("previz_retimed", "")).split(";") if t]
    if tag in done:
        return {"skipped": True, "tag": tag}
    nk = nf = 0
    for act in bpy.data.actions:
        for fc in _all_fcurves(act):
            for kp in fc.keyframe_points:
                x, hl, hr = T(kp.co[0]), T(kp.handle_left[0]), T(kp.handle_right[0])
                if round_keys:
                    dx = round(x) - x
                    x, hl, hr = x + dx, hl + dx, hr + dx
                kp.co[0], kp.handle_left[0], kp.handle_right[0] = x, hl, hr
                nk += 1
            fc.update()
            nf += 1
    nm = 0
    for m in sc.timeline_markers:
        m.frame = int(round(T(m.frame)))
        nm += 1
    fe0 = sc.frame_end
    sc.frame_end = int(round(T(fe0)))
    sc["previz_retimed"] = ";".join(done + [tag])
    return {"keys": nk, "fcurves": nf, "markers": nm, "frame_end": [fe0, sc.frame_end], "tag": tag}


# ---------- 特效 ----------

def _catmull(pts, n=200):
    P = [Vector(p) for p in pts]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(P[-2].copy())
    return out


def _resample(pts, ds=0.2):
    """按弧长每 ds 米重采样，返回 (点列, 总长)。"""
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + (pts[i] - pts[i - 1]).length)
    total = cum[-1]
    n = max(2, int(total / ds))
    res = []
    for i in range(n + 1):
        s = total * i / n
        k = max(1, min(bisect.bisect_left(cum, s), len(pts) - 1))
        w = (s - cum[k - 1]) / max(1e-9, cum[k] - cum[k - 1])
        res.append(pts[k - 1].lerp(pts[k], w))
    return res, total


def _cdf(a, b, n=4000):
    """速度 ∝ u^a (1-u)^b 时飞过的路程比例（0 → 1）。"""
    acc = [0.0]
    for i in range(1, n + 1):
        u0, u1 = (i - 1) / n, i / n
        acc.append(acc[-1] + 0.5 * ((u0 ** a) * ((1 - u0) ** b) + (u1 ** a) * ((1 - u1) ** b)) / n)
    return [x / acc[-1] for x in acc]


class StreamPath:
    """light_stream 的路径：head(f) = 第 f 帧光头位置，total = 路径长度（米），s_at(f) = 第 f 帧飞过的路程。"""

    def __init__(self, points, f_start, f_arrive, profile):
        self.pts, self.total = _resample(_catmull(points), 0.2)
        if self.total < 1e-6:
            raise ValueError("光带路径长度为 0：points 至少要有两个不同的点")
        self.f_start, self.f_arrive = f_start, f_arrive
        self.S = _cdf(*profile)

    def s_at(self, f):
        if f <= self.f_start:
            return 0.0
        if f >= self.f_arrive:
            return self.total
        u = (f - self.f_start) / (self.f_arrive - self.f_start)
        n = len(self.S) - 1
        j = min(int(u * n), n - 1)
        return (self.S[j] + (self.S[j + 1] - self.S[j]) * (u * n - j)) * self.total

    def point(self, s):
        x = max(0.0, min(1.0, s / self.total)) * (len(self.pts) - 1)
        i = min(int(x), len(self.pts) - 2)
        return self.pts[i].lerp(self.pts[i + 1], x - i)

    def head(self, f):
        return self.point(self.s_at(f))


def _new_curve(name, dims):
    """重跑时先删掉本库之前建的同名物体，再建曲线数据（名字不带 .001）。返回 (曲线数据, 摘下的子物体)。"""
    keep = _fresh(name)
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = dims
    return cu, keep


def _curve_obj(name, cu, keep):
    ob = bpy.data.objects.new(name, cu)
    _coll().objects.link(ob)
    _reattach(ob, keep)
    return ob


def _tube(name, pts, radius, rgba):
    """沿点列的 POLY 曲线管（bevel 成圆管，两端封口；bevel_factor 按样条长度算，拖尾靠它）。"""
    cu, keep = _new_curve(name, '3D')
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p, v in zip(sp.points, pts):
        p.co = (v.x, v.y, v.z, 1.0)
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    cu.bevel_factor_mapping_start = 'SPLINE'
    cu.bevel_factor_mapping_end = 'SPLINE'
    ob = _curve_obj(name, cu, keep)
    ob.color = rgba
    ob.display.show_shadows = False
    return ob


def _taper_curve(name):
    cu, keep = _new_curve(name, '2D')
    sp = cu.splines.new('POLY')
    sp.points.add(len(TAPER) - 1)
    for p, (x, y) in zip(sp.points, TAPER):
        p.co = (x, y, 0.0, 1.0)
    ob = _curve_obj(name, cu, keep)
    ob.hide_render = True
    return ob


def light_stream(name, points, f_start, f_arrive, f_gone=None, color=(0.2, 0.5, 1.0),
                 core_r=(0.10, 0.045), glow_r=(0.28, 0.12), lag=(10, 16), profile=(1.3, 2.2),
                 head_scale=(2.2, 1.0)):
    """人化作一道流光飞来：points 连成 Catmull-Rom 路径、按弧长重采样，f_start 起飞，f_arrive 到最后一个点。
    速度 ∝ u^a (1-u)^b（profile=(a, b)：慢慢升起、中途快、到了慢慢停）。
    两根曲线管 <name>_光晕（alpha 0.25）、<name>_亮芯 逐帧键 bevel_factor_start/end 做拖尾（lag = 光晕、亮芯各拖几帧），
    锥度曲线 <name>_锥度（不渲染）让尾细头圆；管子半径按飞过的路程从远到近插值
    （core_r、glow_r = (起点, 终点)，按路程比例的平方：远处保持粗、好看清，飞近才变细）；
    <name>_光头 小球逐帧键位置，大小按 head_scale 从远到近，f_arrive 后缩到 0.05，拖尾收进光头；
    f_gone（默认 f_arrive + 34）起全部隐藏。部件不投影，都进 PREVIZ 集合。
    返回 StreamPath：path.head(f) = 第 f 帧光头位置（角色看光用），path.total = 路径长度。
    光带颜色饱和度高：check_export ③ 按环境物体报警告，属正常，交接卡写映射句（handoff-card.md）。"""
    f_start, f_arrive = int(f_start), int(f_arrive)
    if f_arrive <= f_start:
        raise ValueError("f_arrive 要大于 f_start")
    f_gone = f_arrive + 34 if f_gone is None else int(f_gone)
    if f_gone <= f_arrive:
        raise ValueError("f_gone 要大于 f_arrive")
    if len(points) < 2:
        raise ValueError("points 至少两个点")
    path = StreamPath(points, f_start, f_arrive, profile)
    rgb = tuple(float(c) for c in color[:3])
    head_rgb = tuple(c + (1.0 - c) * 0.25 for c in rgb)            # 光头亮一档

    def far_near(f):                                              # 0 = 起点（远），1 = 到了（近）
        p = path.s_at(f) / path.total
        return p * p

    taper = _taper_curve(f"{name}_锥度")
    glow = _tube(f"{name}_光晕", path.pts, glow_r[0], rgb + (0.25,))
    core = _tube(f"{name}_亮芯", path.pts, core_r[0], rgb + (1.0,))
    for ob, (r0, r1), lg in ((glow, glow_r, lag[0]), (core, core_r, lag[1])):
        cu = ob.data
        cu.taper_object = taper
        cu.use_map_taper = True
        for f in range(f_start, f_gone + 1):
            if f <= f_arrive:
                cu.bevel_depth = r0 + (r1 - r0) * far_near(f)
                cu.keyframe_insert("bevel_depth", frame=f)
            cu.bevel_factor_end = path.s_at(f) / path.total
            cu.bevel_factor_start = path.s_at(max(f_start, f - lg)) / path.total
            cu.keyframe_insert("bevel_factor_end", frame=f)
            cu.keyframe_insert("bevel_factor_start", frame=f)
        _set_interp(cu, ("bevel_",), 'LINEAR')

    head = mk_sphere(f"{name}_光头", radius=0.1, color=head_rgb, segs=16, rings=8)
    head.display.show_shadows = False
    for f in range(f_start, f_gone + 1):
        head.location = path.head(f)
        head.keyframe_insert("location", frame=f)
        if f <= f_arrive:
            s = head_scale[0] + (head_scale[1] - head_scale[0]) * far_near(f)
            head.scale = (s, s, s)
            head.keyframe_insert("scale", frame=f)
    tail = f_gone - f_arrive
    for f, s in ((f_arrive + max(1, round(tail * 18 / 34)), 0.6 * head_scale[1]), (f_gone, 0.05)):
        head.scale = (s, s, s)
        head.keyframe_insert("scale", frame=f)
    _set_interp(head, ("location", "scale"), 'LINEAR')

    # 到了以后：光晕、亮芯先淡掉，光头随后淡掉；f_gone + 1 起全部隐藏
    fades = ((glow, 0.25, f_arrive, f_arrive + max(1, round(tail * 16 / 34))),
             (core, 1.0, f_arrive, f_arrive + max(1, round(tail * 18 / 34))),
             (head, 1.0, f_arrive + round(tail * 6 / 34), f_gone))
    for ob, a, fa, fb in fades:
        for f, al in ((fa, a), (fb, 0.0)):
            c = ob.color
            ob.color = (c[0], c[1], c[2], al)
            ob.keyframe_insert("color", index=3, frame=f)
        key_hide(ob, [(f_start - 1, True), (f_start, False), (f_gone + 1, True)])
    return path


# ---------- 渲染设置 ----------

def setup_workbench(res=(1280, 720), fps=24, sun_dir=(-0.5, 0.6, 0.6), frame_range=None,
                    light="STUDIO", bg=(0.35, 0.35, 0.37), shadow_intensity=0.6, studio_light="Default",
                    follow_camera=False, adopt_material_colors=True, dof=None):
    """Workbench 白模渲染：物体色、投影、cavity、Standard 视图变换。
    sun_dir 是"光从哪来"：从场景指向太阳的世界方向，z 要 >0。如 (-0.6, 0.75, 0.3) = 光从左后方低斜来。
    Workbench 不认灯物体：投影方向写进 scene.display.light_direction（5.2.2 实测换算），
    摄影棚光改世界坐标并转到同一方位；另建 LGT_sun 记录光向（切 EEVEE 时直接可用）。
    逆光看不清：shadow_intensity 调小（如 0.4）；再不行 follow_camera=True——摄影棚光跟相机走，
    投影方向仍按 sun_dir 固定，场景记 previz_light_follow，check_export 只记备注。
    仰拍底面全黑：studio_light="studio.sl"（5.2.2 有 Default、basic.sl、outdoor.sl、paint.sl、rim.sl、studio.sl）。
    adopt_material_colors=True：物体色还是默认白 (1, 1, 1, 1) 又有材质的几何体，先把第一个材质的颜色抄进物体色，
    旧场景是材质色时不会渲成全白。景深：dof=None 不碰（按镜头用 apply_dof 开），True / False 直接开关总开关。"""
    sc = _scene()
    s = Vector(sun_dir)
    if s.length < 1e-9 or s.normalized().z <= 0.0:
        raise ValueError("sun_dir 的 z 要 >0：太阳要在地平线以上")
    s.normalize()
    r = sc.render
    r.engine = 'BLENDER_WORKBENCH'
    r.resolution_x, r.resolution_y = int(res[0]), int(res[1])
    r.resolution_percentage = 100
    r.fps, r.fps_base = int(fps), 1.0
    r.film_transparent = False
    r.use_stamp = False
    if frame_range is not None:
        sc.frame_start, sc.frame_end = int(frame_range[0]), int(frame_range[1])
    im = r.image_settings
    if hasattr(im, "media_type"):
        im.media_type = 'IMAGE'
    im.file_format = 'PNG'
    im.color_mode = 'RGB'
    im.color_depth = '8'

    adopted = 0
    if adopt_material_colors:
        for ob in sc.objects:
            if ob.type not in PAINTABLE or any(abs(c - 1.0) > 1e-6 for c in ob.color):
                continue
            mat = next((slot.material for slot in ob.material_slots if slot.material), None)
            if mat is None:
                continue
            ob.color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], 1.0)
            adopted += 1

    sh = sc.display.shading
    sh.light = light
    sh.color_type = 'OBJECT'
    sh.show_shadows = True
    sh.shadow_intensity = shadow_intensity
    sh.show_cavity = True
    sh.show_specular_highlight = False
    if dof is not None and hasattr(sh, "use_dof"):
        sh.use_dof = bool(dof)
    sc.display.light_direction = (s.x, s.z, -s.y)   # 光行进方向 = (-lx, lz, -ly)
    az = math.degrees(math.atan2(s.y, s.x))
    if light == 'STUDIO':
        try:
            sh.studio_light = studio_light
        except TypeError:
            pass
        sh.use_world_space_lighting = not follow_camera
        if not follow_camera:
            rz = (STUDIO_AZ0_DEG - az + 180.0) % 360.0 - 180.0
            sh.studiolight_rotate_z = math.radians(rz)
    if follow_camera:
        sc["previz_light_follow"] = True
    elif "previz_light_follow" in sc:
        del sc["previz_light_follow"]

    vs = sc.view_settings
    vs.view_transform = 'Standard'
    vs.look = 'None'
    vs.exposure, vs.gamma = 0.0, 1.0

    if sc.world is None:
        sc.world = bpy.data.worlds.new("PREVIZ_World")
    sc.world.color = bg[:3]

    sun = bpy.data.objects.get("LGT_sun")
    if sun is not None and _owned(sun):
        _remove(sun)
        sun = None
    if sun is None:
        ld = bpy.data.lights.new("LGT_sun", type='SUN')
        ld.energy = 3.0
        ld.angle = math.radians(2.0)
        ld.use_shadow = True
        sun = bpy.data.objects.new("LGT_sun", ld)
        _coll().objects.link(sun)
    sun.rotation_euler = (-s).to_track_quat('-Z', 'Y').to_euler()   # 灯的 -Z = 光行进方向
    return {"engine": r.engine, "res": [r.resolution_x, r.resolution_y], "fps": r.fps,
            "frames": [sc.frame_start, sc.frame_end], "sun_dir": [round(v, 4) for v in s],
            "light_direction": [round(v, 4) for v in sc.display.light_direction],
            "sun_azimuth_deg": round(az, 1),
            "studiolight_rotate_z_deg": round(math.degrees(sh.studiolight_rotate_z), 1),
            "studio_light": sh.studio_light, "follow_camera": bool(follow_camera),
            "shadow_intensity": round(sh.shadow_intensity, 3), "adopted": adopted}


def hide_overlays():
    """关掉视口 overlay / gizmo、相机框和名字、物体轴向和名字、stamp 烧字。
    F12（render.render）本来不画这些；这是给桌面插件"相机渲染"或视口渲染准备的。"""
    n = {"view3d": 0, "cameras": 0, "objects": 0}
    for scr in bpy.data.screens:
        for area in scr.areas:
            if area.type != 'VIEW_3D':
                continue
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.overlay.show_overlays = False
                    sp.show_gizmo = False
                    n["view3d"] += 1
    for ob in bpy.data.objects:
        if ob.show_name or ob.show_axis:
            ob.show_name = ob.show_axis = False
            n["objects"] += 1
        if ob.type == 'CAMERA':
            cd = ob.data
            cd.show_limits = cd.show_mist = cd.show_sensor = cd.show_name = False
            cd.show_safe_areas = cd.show_safe_center = False
            n["cameras"] += 1
    _scene().render.use_stamp = False
    return n


def still(path, cam=None, frame=None, res_pct=None):
    """用指定相机（物体或名字；None = 这一帧本来的相机）在指定帧渲一张 png 到 path。
    渲之前把绑了相机的时间轴标记临时解绑（不然 frame_set / render 会把 scene.camera 顶回标记的相机），渲完绑回；
    分辨率百分比、输出格式（临时 PNG / RGB / 8 位）、输出路径、scene.camera、当前帧全部恢复。返回 path 是否存在。"""
    sc = _scene()
    r = sc.render
    old = (sc.camera, r.resolution_percentage, r.filepath, sc.frame_current, sc.frame_subframe)
    saved = _png_on(r)
    unbound = []
    try:
        if frame is not None:
            sc.frame_set(int(frame))
        use = _obj(cam) if cam is not None else sc.camera
        if use is None:
            raise ValueError(f"第 {sc.frame_current} 帧没有相机")
        for m in sc.timeline_markers:
            if m.camera is not None:
                unbound.append((m, m.camera))
                m.camera = None
        sc.camera = use
        if res_pct is not None:
            r.resolution_percentage = int(res_pct)
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        r.filepath = path
        bpy.ops.render.render(write_still=True)
    finally:
        for m, c in unbound:
            m.camera = c
        _png_off(r, saved)
        r.resolution_percentage, r.filepath = old[1], old[2]
        sc.frame_set(old[3], subframe=old[4])
        sc.camera = old[0]
    return os.path.exists(path)


# ---------- 分析与审看 ----------

def _read_png(path):
    """读 png → (h, w, 3) 显示值数组（0–1），第 0 行是画面顶端。"""
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        ch = img.channels
        buf = np.empty(w * h * ch, dtype=np.float32)
        img.pixels.foreach_get(buf)
        px = buf.reshape(h, w, ch)[::-1, :, :3].copy()
    finally:
        bpy.data.images.remove(img)
    return px


def _classify(px, palette, tol):
    """逐像素找最近的颜色（欧氏距离）：返回下标图，离最近色超过 tol 的记 -1。"""
    import numpy as np
    best = np.full(px.shape[:2], np.inf, dtype=np.float32)
    idx = np.full(px.shape[:2], -1, dtype=np.int32)
    for i, c in enumerate(palette):
        d = np.sqrt(((px - np.asarray(c, dtype=np.float32)) ** 2).sum(axis=-1))
        m = d < best
        best[m] = d[m]
        idx[m] = i
    idx[best > tol] = -1
    return idx


def _mask_stats(mask):
    """一个角色的像素掩码 → 面积占比、包围框（画面比例，原点左上）、画高、贴着哪条边。"""
    import numpy as np
    h, w = mask.shape
    n = int(mask.sum())
    if n == 0:
        return {"area": 0.0, "bbox": None, "height": 0.0, "cut": []}
    ys = np.nonzero(mask.any(axis=1))[0]
    xs = np.nonzero(mask.any(axis=0))[0]
    y0, y1, x0, x1 = int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1
    cut = [e for e, hit in (("top", y0 <= 1), ("bottom", y1 >= h - 1), ("left", x0 <= 1), ("right", x1 >= w - 1))
           if hit]
    return {"area": round(n / float(w * h), 5),
            "bbox": [round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)],
            "height": round((y1 - y0) / float(h), 4), "cut": cut}


def _stats_from_png(path, colors):
    """旧渲染图按色度分类：像素先转回线性，色度 = rgb ÷ 三者之和，最近邻、容差 0.06；另有中性灰一类算环境。"""
    import numpy as np
    if not colors:
        raise ValueError("量旧图要给 colors={名: (r, g, b)}")
    px = _read_png(path)
    h, w = px.shape[:2]
    lin = np.where(px <= 0.04045, px / 12.92, ((px + 0.055) / 1.055) ** 2.4)
    tot = lin.sum(axis=-1)
    chroma = lin / np.maximum(tot, 1e-6)[..., None]
    names = list(colors)
    cand = []
    for n in names:
        c = np.asarray(colors[n][:3], dtype=np.float32)
        cand.append(c / max(float(c.sum()), 1e-6))
    cand.append(np.full(3, 1.0 / 3.0, dtype=np.float32))      # 中性灰 = 环境
    idx = _classify(chroma, cand, 0.06)
    idx[tot <= 0.02] = -1                                    # 太暗的像素色度不稳，不算
    out, sky = {}, None
    for k, n in enumerate(names):
        if n in ("sky", "天空"):
            sky = round(float((idx == k).mean()), 4)
        else:
            out[n] = _mask_stats(idx == k)
    return {"frame": None, "res": [w, h], "chars": out, "sky": sky,
            "env": round(float((idx == len(names)).mean()), 4), "path": path}


def frame_stats(frame=None, chars=None, res_pct=50, out_png=None, path=None, colors=None):
    """按像素量构图：每个角色的面积占比、包围框、画高、贴着哪条边，外加天空、环境占比。
    默认做一次掩码渲染再数像素：临时切 Workbench 平光、物体色，关投影 / cavity / 景深 / 描边 / 抗锯齿，
    Standard 视图，世界色黑；角色（chars 默认全部 CHR_ 根物体，含隐藏的）每人一种纯色，其他几何体中灰，
    超过 10 个角色分批渲；部件上的 color 曲线（显形的 alpha 键）临时静音。用这一帧本来的相机（标记管的那台）渲，
    out_png 给了就把掩码图留下（分批时留最后一批）。渲完颜色、alpha、静音、着色、世界色、渲染设置、分辨率、相机、帧全部恢复。
    返回 {"frame", "res": [w, h], "chars": {根名: {"area", "bbox", "height", "cut"}}, "sky", "env"}：
    area 是面积占比；bbox = [x0, y0, x1, y1] 画面比例、原点左上（不在画里是 None）；height = 包围框高 ÷ 画高；
    cut 列出包围框贴着的边（距边 ≤1 像素，如 ["top"] = 头被上框裁掉）；sky = 背景占比，env = 其他物体占比。
    path + colors={名: (r, g, b)}：不渲，直接量这张旧渲染图，按色度（rgb ÷ 三者之和）最近邻分类、容差 0.06；
    colors 写物体色（线性 RGB，任务卡上那三个数），名叫 "sky" 或 "天空" 的一项算天空。
    适合鲜明分色的旧图（E02S08 就这样量出原图曲伯 18.8%）；低饱和的灰阶色彼此色度太近，分不开。
    宿主 python3 没有 numpy：这个函数只能在 Blender 里跑。"""
    if path is not None:
        return _stats_from_png(path, colors)
    import numpy as np
    sc = _scene()
    r, disp, vs = sc.render, sc.display, sc.view_settings
    sh = disp.shading
    roots = _chr_roots() if chars is None else [_obj(c) for c in chars]
    f = sc.frame_current if frame is None else int(frame)
    part_of = {}
    for i, rt in enumerate(roots):
        for p in _geom_parts(rt):
            part_of.setdefault(p.name, i)
    paint = [o for o in bpy.data.objects if o.type in PAINTABLE and o.library is None]
    r_keys = ("engine", "film_transparent", "dither_intensity", "use_compositing", "use_sequencer")
    sh_keys = ("light", "color_type", "show_shadows", "show_cavity", "use_dof", "show_object_outline",
               "show_xray", "show_specular_highlight")
    saved_r = {k: getattr(r, k) for k in r_keys if hasattr(r, k)}
    saved_sh = {k: getattr(sh, k) for k in sh_keys if hasattr(sh, k)}
    saved_aa = disp.render_aa
    saved_vs = (vs.view_transform, vs.look, vs.exposure, vs.gamma)
    orig = (sc.frame_current, sc.frame_subframe, sc.camera)
    world_tmp = sc.world is None
    world_col = None
    saved_col = {}
    muted = []
    tmp = out_png or os.path.join(bpy.app.tempdir or tempfile.gettempdir(), f"previz_mask_{os.getpid()}.png")
    chars_out, sky, env, res = {}, None, None, None
    try:
        sc.frame_set(f)
        cam = sc.camera
        if cam is None:
            raise ValueError(f"第 {f} 帧没有相机")
        for o in paint:
            saved_col[o.name] = tuple(o.color)
            for fc in _fcurves(o):
                if fc.data_path == "color" and not fc.mute:
                    fc.mute = True
                    muted.append(fc)
        r.engine = 'BLENDER_WORKBENCH'
        r.film_transparent = False
        for k, v in (("dither_intensity", 0.0), ("use_compositing", False), ("use_sequencer", False)):
            if hasattr(r, k):
                setattr(r, k, v)
        sh.light = 'FLAT'
        sh.color_type = 'OBJECT'
        for k in ("show_shadows", "show_cavity", "use_dof", "show_object_outline", "show_xray"):
            if hasattr(sh, k):
                setattr(sh, k, False)
        disp.render_aa = 'OFF'
        vs.view_transform, vs.look, vs.exposure, vs.gamma = 'Standard', 'None', 0.0, 1.0
        if world_tmp:
            sc.world = bpy.data.worlds.new("TMP_MASK_World")
        world_col = tuple(sc.world.color)
        sc.world.color = (0.0, 0.0, 0.0)
        batches = [roots[i:i + len(MASK_COLORS)] for i in range(0, len(roots), len(MASK_COLORS))] or [[]]
        multi = len(batches) > 1
        for bi, batch in enumerate(batches):
            slot = {roots.index(rt): k for k, rt in enumerate(batch)}
            for o in paint:
                i = part_of.get(o.name)
                col = MASK_ENV if i is None else (MASK_COLORS[slot[i]] if i in slot else MASK_OTHER)
                o.color = (col[0], col[1], col[2], 1.0)
            still(tmp, cam=cam, res_pct=res_pct)
            px = _read_png(tmp)
            h, w = px.shape[:2]
            res = [w, h]
            pal = [_srgb(MASK_COLORS[k]) for k in range(len(batch))] + [_srgb(MASK_ENV), (0.0, 0.0, 0.0)]
            if multi:
                pal.append(_srgb(MASK_OTHER))
            idx = _classify(px, pal, 0.12)
            for k, rt in enumerate(batch):
                chars_out[rt.name] = _mask_stats(idx == k)
            if bi == 0:
                env = round(float(np.mean(idx == len(batch))), 4)
                sky = round(float(np.mean(idx == len(batch) + 1)), 4)
    finally:
        for o in paint:
            if o.name in saved_col:
                o.color = saved_col[o.name]
        for fc in muted:
            fc.mute = False
        for k, v in saved_sh.items():
            try:
                setattr(sh, k, v)
            except (TypeError, ValueError):
                pass
        disp.render_aa = saved_aa
        vs.view_transform, vs.look, vs.exposure, vs.gamma = saved_vs
        if world_tmp and sc.world is not None:
            w_tmp = sc.world
            sc.world = None
            bpy.data.worlds.remove(w_tmp)
        elif world_col is not None:
            sc.world.color = world_col
        for k, v in saved_r.items():
            setattr(r, k, v)
        sc.frame_set(orig[0], subframe=orig[1])
        sc.camera = orig[2]
        if out_png is None and os.path.isfile(tmp):
            os.remove(tmp)
    return {"frame": f, "res": res, "chars": chars_out, "sky": sky, "env": env}


def _grid_png(paths, out, cols=2, pad=4):
    """几张同尺寸的 png 按 cols 列拼成一张（黑底、间隔 pad 像素）。"""
    import numpy as np
    tiles = []
    for p in paths:
        img = bpy.data.images.load(p, check_existing=False)
        try:
            w, h = img.size
            ch = img.channels
            buf = np.empty(w * h * ch, dtype=np.float32)
            img.pixels.foreach_get(buf)
            a = buf.reshape(h, w, ch)
            if ch == 3:
                a = np.concatenate([a, np.ones((h, w, 1), np.float32)], axis=-1)
            tiles.append(a[::-1])                      # 第 0 行 = 画面顶端
        finally:
            bpy.data.images.remove(img)
    th = max(a.shape[0] for a in tiles)
    tw = max(a.shape[1] for a in tiles)
    cols = max(1, min(int(cols), len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    H, W = rows * th + (rows - 1) * pad, cols * tw + (cols - 1) * pad
    grid = np.zeros((H, W, 4), dtype=np.float32)
    grid[..., 3] = 1.0
    for i, a in enumerate(tiles):
        rr, cc = divmod(i, cols)
        y, x = rr * (th + pad), cc * (tw + pad)
        grid[y:y + a.shape[0], x:x + a.shape[1]] = a
    img = bpy.data.images.new("TMP_GRID", W, H, alpha=True)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(grid[::-1]).ravel())
        img.filepath_raw = out
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)
    return out


def compare_cams(frame, cands, out_dir, res_pct=50, dof=None, cols=2):
    """候选机位对比图（用户问"有什么建议"时渲 3–4 个候选拼一张给他挑）。
    cands = {"A": (焦段 mm, 机位 (x, y, z), 目标点 (x, y, z)), "B": …}。建临时 TMP_CAM + TMP_AIM（Track To），
    把管这一帧的时间轴标记（≤ frame 的最后一个绑了相机的标记）临时换成 TMP_CAM，scene.camera 也指过去；
    每个候选渲一张 out_dir/<标签>.png，stamp 只开 note，把标签烧进左上角；再用 numpy 按 cols 列拼成
    out_dir/compare_<帧>.png。dof=(光圈 f 值, 对焦物体或名字) 时临时相机开景深。
    渲完标记、scene.camera、stamp 各项、分辨率百分比、帧全部恢复，临时物体和相机数据删掉。
    坑：标记绑了相机，只改 scene.camera 渲会被顶回标记的相机，几张图一模一样（E02S08 第一轮）。
    返回 {"grid": 拼图路径, "tiles": {标签: 路径}}。"""
    sc = _scene()
    r = sc.render
    frame = int(frame)
    os.makedirs(out_dir, exist_ok=True)
    mk = _governing_marker(sc, frame)
    ref = mk.camera if mk is not None else sc.camera
    cd = bpy.data.cameras.new("TMP_CAM")
    if ref is not None and ref.type == 'CAMERA':
        rd = ref.data
        cd.sensor_width, cd.sensor_height, cd.sensor_fit = rd.sensor_width, rd.sensor_height, rd.sensor_fit
        cd.clip_start, cd.clip_end = rd.clip_start, rd.clip_end
    else:
        cd.sensor_width, cd.clip_start, cd.clip_end = 36.0, 0.1, 5000.0
    cam = bpy.data.objects.new("TMP_CAM", cd)
    aim = bpy.data.objects.new("TMP_AIM", None)
    sc.collection.objects.link(cam)
    sc.collection.objects.link(aim)
    con = cam.constraints.new('TRACK_TO')
    con.target = aim
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    if dof is not None:
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = float(dof[0])
        cd.dof.aperture_blades = 0
        cd.dof.focus_object = _obj(dof[1])
    stamp_keys = [p.identifier for p in r.bl_rna.properties if p.identifier.startswith("use_stamp")]
    saved = {k: getattr(r, k) for k in stamp_keys + ["stamp_note_text", "stamp_font_size",
                                                      "resolution_percentage", "filepath"]}
    png = _png_on(r)
    orig = (sc.frame_current, sc.frame_subframe, sc.camera)
    mk_cam = mk.camera if mk is not None else None
    tiles = {}
    try:
        if mk is not None:
            mk.camera = cam
        for k in stamp_keys:
            setattr(r, k, False)
        r.use_stamp = True
        r.use_stamp_note = True
        r.stamp_font_size = 24
        r.resolution_percentage = int(res_pct)
        for label, (lens, cam_loc, aim_loc) in cands.items():
            cd.lens = float(lens)
            cam.location = cam_loc
            aim.location = aim_loc
            r.stamp_note_text = str(label)
            sc.frame_set(frame)
            sc.camera = cam
            p = os.path.join(out_dir, f"{label}.png")
            r.filepath = p
            bpy.ops.render.render(write_still=True)
            tiles[str(label)] = p
    finally:
        if mk is not None:
            mk.camera = mk_cam
        for k, v in saved.items():
            setattr(r, k, v)
        _png_off(r, png)
        sc.frame_set(orig[0], subframe=orig[1])
        sc.camera = orig[2]
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.objects.remove(aim, do_unlink=True)
        if cd.users == 0:
            bpy.data.cameras.remove(cd)
    grid = _grid_png(list(tiles.values()), os.path.join(out_dir, f"compare_{frame}.png"), cols)
    return {"grid": grid, "tiles": tiles}


def burn_subs(src_mp4, out_mp4, phrases, cuts=(), offset=0, font=FONT, size=40, tag_size=24):
    """审看版：在干净 mp4 上叠短句字幕和镜号，直接出 mp4（Blender 剪辑器，不渲帧）。
    phrases = [(起帧, 止帧, 说话人, 短句), …]：底部居中"说话人：短句"，白字黑边、半透明黑底；
    cuts = [(标签, 起帧, 止帧), …]：左上角"镜<标签>"。帧号按 mp4 的第 1 帧 = 1；
    给分段 mp4 烧字幕传 offset = 段首全片帧号 − 1（帧号都减 offset）。字号按像素，720p 下 40 / 24 合适。
    建临时场景 SUB_REVIEW（分辨率、fps 跟源，sRGB + Standard，颜色和源一致），H.264 mp4、无音轨，
    渲完删掉临时场景，主场景不动。返回 {"out", "frames", "seconds"}。"""
    src = os.path.abspath(src_mp4)
    out = os.path.abspath(out_mp4)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    old = bpy.data.scenes.get("SUB_REVIEW")
    if old is not None:
        bpy.data.scenes.remove(old)
    sub = bpy.data.scenes.new("SUB_REVIEW")
    fnt = None
    try:
        se = sub.sequence_editor_create()
        strips = se.strips
        r = sub.render
        mov = strips.new_movie(name="CLEAN", filepath=src, channel=1, frame_start=1)
        fps = float(mov.fps) or 24.0
        if abs(fps - r.fps / r.fps_base) > 1e-3:          # 场景 fps 先对上源，再重放一次视频条
            r.fps = max(1, int(round(fps)))
            r.fps_base = r.fps / fps
            strips.remove(mov)
            mov = strips.new_movie(name="CLEAN", filepath=src, channel=1, frame_start=1)
        el = mov.elements[0]
        r.resolution_x, r.resolution_y, r.resolution_percentage = el.orig_width, el.orig_height, 100
        n = int(mov.duration)
        sub.frame_start, sub.frame_end = 1, n
        r.use_sequencer = True
        sub.view_settings.view_transform = 'Standard'
        sub.view_settings.look = 'None'
        sub.sequencer_colorspace_settings.name = 'sRGB'
        im = r.image_settings
        if hasattr(im, "media_type"):
            im.media_type = 'VIDEO'
        im.file_format = 'FFMPEG'
        ff = r.ffmpeg
        ff.format = 'MPEG4'
        ff.codec = 'H264'
        ff.constant_rate_factor = 'HIGH'
        ff.ffmpeg_preset = 'GOOD'
        ff.audio_codec = 'NONE'
        if font and os.path.isfile(font):
            fnt = bpy.data.fonts.load(font, check_existing=True)

        def text(name, s, ch, a, b, sz, loc, ax, ay, box_alpha):
            a, b = max(1, int(a) - offset), min(n, int(b) - offset)
            if b < a:
                return None
            t = strips.new_effect(name=name, type='TEXT', channel=ch, frame_start=a, length=b - a + 1)
            t.text = s
            if fnt is not None:
                t.font = fnt
            t.font_size = sz
            t.color = (1.0, 1.0, 1.0, 1.0)
            t.use_outline = True
            t.outline_color = (0.0, 0.0, 0.0, 1.0)
            t.outline_width = 0.06
            t.use_box = True
            t.box_color = (0.0, 0.0, 0.0, box_alpha)
            t.box_margin = 0.012
            t.location = loc
            t.anchor_x, t.anchor_y = ax, ay
            t.alignment_x = 'CENTER' if ax == 'CENTER' else 'LEFT'
            return t

        for i, (a, b, who, txt) in enumerate(phrases):
            text(f"D{i:03d}", f"{who}：{txt}" if who else str(txt), 2, a, b, size, (0.5, 0.055), 'CENTER', 'BOTTOM', 0.5)
        for label, a, b in cuts:
            text(f"S{label}", f"镜{label}", 3, a, b, tag_size, (0.02, 0.965), 'LEFT', 'TOP', 0.35)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        r.filepath = out
        bpy.ops.render.render(animation=True, scene=sub.name)
        seconds = n / (r.fps / r.fps_base)
    finally:
        bpy.data.scenes.remove(sub)
        if fnt is not None and fnt.users == 0:
            bpy.data.fonts.remove(fnt)
    return {"out": out, "frames": n, "seconds": round(seconds, 3)}


# ---------- 自测 ----------

def _launched_as_script():
    argv = sys.argv
    for i, a in enumerate(argv[:-1]):
        if a in ("--python", "-P") and os.path.basename(argv[i + 1]) == "previz_lib.py":
            return True
    return False


def _selftest():
    import shutil
    import subprocess
    import time
    from bpy_extras.object_utils import world_to_camera_view
    extra = {o.name for o in bpy.data.objects} - {"Cube", "Light", "Camera"}
    if bpy.data.filepath or extra:
        raise RuntimeError("自测只在空白会话里跑（会清空场景），当前会话有内容")
    t0 = time.time()
    out = os.path.join(tempfile.gettempdir(), "seedance-previz-selftest")
    frames = os.path.join(out, "frames")
    os.makedirs(frames, exist_ok=True)
    for f in os.listdir(frames):
        if f.endswith(".png"):
            os.remove(os.path.join(frames, f))
    for f in ("A.png", "B.png", "compare_37.png", "selftest_clean.mp4", "selftest_review.mp4"):
        if os.path.isfile(os.path.join(out, f)):
            os.remove(os.path.join(out, f))
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    sc = _scene()
    sun_dir = (-0.5, 0.6, 0.62)
    info = setup_workbench(res=(854, 480), fps=24, sun_dir=sun_dir, frame_range=(1, 72))
    errs = []

    def chk(group, ok, msg):
        if not ok:
            errs.append(f"组{group}：{msg}")

    mk_box("ENV_ground", size=(400, 400, 0.2), loc=(0, 60, -0.2), color=(0.5, 0.5, 0.5))
    mk_box("ENV_hut", size=(6, 5, 3), loc=(-7, 10, 0), color=(0.45, 0.45, 0.48))
    roof("ENV_hut_roof", width=7, depth=6, height=2, loc=(-7, 10, 3))
    stairs("ENV_stairs", width=3, run=4, rise=2, steps=8, loc=(6, 8, 0))
    mk_sphere("ENV_cloud", radius=6, loc=(0, 60, 14), color=(0.6, 0.6, 0.62), scale=(2, 1, 0.2))

    hero = torso_proxy("CHR_Hero_图1", height=1.8, color=(0.55, 0.50, 0.45))
    key_rig(hero, 1, loc=(0, 0, 0))
    key_rig(hero, 72, loc=(0, -3.0, 0))
    # 故意做错一：带四肢 + 高饱和色，check_export 要报出来
    bad = torso_proxy("CHR_Limbed_图2", height=1.7, color=(1.0, 0.42, 0.08), loc=(2.2, 1.5, 0))
    for side, x in (("L", 0.28), ("R", -0.28)):
        arm = mk_cyl(f"CHR_Limbed_图2_Arm{side}", radius=0.06, depth=0.7,
                     loc=(x, 0, 0.75), color=(1.0, 0.42, 0.08))
        leg = mk_cyl(f"CHR_Limbed_图2_Leg{side}", radius=0.08, depth=0.8,
                     loc=(x * 0.5, 0, 0), color=(1.0, 0.42, 0.08))
        _parent(arm, bad)
        _parent(leg, bad)
    key_rig(bad, 1, loc=(2.2, 1.5, 0))
    key_rig(bad, 72, loc=(2.2, 0.3, 0))
    # 故意做错二：过小又不动的主体
    torso_proxy("CHR_Tiny_图3", height=1.7, color=(0.35, 0.36, 0.40), loc=(4, 160, 0))

    # 组1：坐姿代理 + 起身；四肢命名
    seat = torso_proxy("CHR_Sit_图4", 1.6, (0.55, 0.50, 0.45), pose="sit", loc=(-2, 1, 0))
    stand = torso_proxy("CHR_Sit_图4_站", 1.6, (0.55, 0.50, 0.45), loc=(-2.3, 1, 0))
    up = stand_up(seat, stand, 50, 18)
    # 组2：从无到有显形
    ghost = torso_proxy("CHR_Ghost_图5", 1.7, (0.35, 0.36, 0.40), loc=(-4, 3, 0))
    reveal(ghost, 10, 30)
    # 组3：光带
    path = light_stream("FX_test", [(20, 30, 5), (10, 15, 8), (2, 3, 3)], 10, 60)

    cam_a, rig_a = camera_with_rig("CAM_A", lens=35, rig="dolly", loc=(0.8, -7, 1.6))
    aim_to(cam_a, hero, offset=(0, 0, 1.4))
    key_rig(rig_a, 1, loc=(0.8, -7, 1.6))
    key_rig(rig_a, 36, loc=(0.8, -5, 1.5))
    cam_b, rig_b = camera_with_rig("CAM_B", lens=50, rig="orbit", pivot=(0, 0, 0), radius=6, height=1.2)
    aim_to(cam_b, (0, 0, 1.3))
    key_rig(rig_b, 37, rot_z=0.0)
    key_rig(rig_b, 72, rot_z=math.radians(30))
    key_rig(cam_b, 37, rot_z=0.0)
    key_rig(cam_b, 72, rot_z=math.radians(12))          # 荷兰角
    camera_with_rig("CAM_C", lens=24, rig="crane", loc=(-3, -6, 2))
    cam_d, rig_d = camera_with_rig("CAM_D", lens=35, rig="handheld", loc=(3, -6, 1.6))
    # 组4：环绕
    cam_e, rig_e = camera_with_rig("CAM_E", 40, "dolly")
    aim_e = aim_to(cam_e, (0, 0, 1.3))
    orb = orbit(rig_e, aim_e, (0, 0, 1.3), 4.0, -10, 20, 40, 72, z=0.2, screen_offset=12)
    # 组5：景深按镜头开（CAM_B 移焦）
    dof = apply_dof({cam_a: (2.0, "AIM"), cam_b: (2.8, ("RACK", [(37, hero), (72, 3.0)]))})
    set_marker_camera(1, cam_a)
    set_marker_camera(37, cam_b)
    hide_overlays()

    # 组1–5 断言
    seat_p, stand_p = _geom_parts(seat), _geom_parts(stand)
    sc.frame_set(49)
    chk(1, not any(p.hide_render for p in seat_p) and all(p.hide_render for p in stand_p),
        "第 49 帧应只显示坐姿")
    sc.frame_set(50)
    chk(1, all(p.hide_render for p in seat_p) and not any(p.hide_render for p in stand_p),
        "第 50 帧应只显示站姿")
    chk(1, (stand.location - Vector((-2.0, 1.0, -up["drop"]))).length < 1e-4,
        f"第 50 帧站姿根应在 (-2, 1, -{up['drop']})，实际 {tuple(round(v, 4) for v in stand.location)}")
    sc.frame_set(68)
    chk(1, (stand.location - Vector((-2.3, 1.0, 0.0))).length < 1e-4,
        f"第 68 帧站姿根应在 (-2.3, 1, 0)，实际 {tuple(round(v, 4) for v in stand.location)}")
    chk(1, bpy.data.objects.get("CHR_Sit_图4_Lap") is not None and abs(seat["previz_height"] - 0.88) < 1e-6,
        "坐姿代理缺 _Lap 或 previz_height 不是 0.55 × 身高")
    for n, want in (("CHR_Sit_图4_Lap", False), ("展臂法相", False), ("盘腿座", False),
                    ("CHR_X_左臂", True), ("CHR_X_ArmL", True)):
        chk(1, is_limb_name(n) == want, f"is_limb_name({n!r}) 应为 {want}")
    ghost_p = _geom_parts(ghost)
    sc.frame_set(9)
    chk(2, all(p.hide_render for p in ghost_p), "第 9 帧应隐藏")
    sc.frame_set(10)
    chk(2, not any(p.hide_render for p in ghost_p) and all(abs(p.color[3]) < 1e-4 for p in ghost_p),
        "第 10 帧应显示且 alpha 0")
    sc.frame_set(30)
    chk(2, all(abs(p.color[3] - 1.0) < 1e-4 for p in ghost_p), "第 30 帧 alpha 应为 1")
    fx = {k: bpy.data.objects.get(f"FX_test_{k}") for k in ("光晕", "亮芯", "锥度", "光头")}
    chk(3, all(fx.values()), f"缺光带部件：{[k for k, v in fx.items() if v is None]}")
    if all(fx.values()):
        core, head = fx["亮芯"], fx["光头"]
        sc.frame_set(10)
        e10 = core.data.bevel_factor_end
        sc.frame_set(60)
        e60, h60 = core.data.bevel_factor_end, head.matrix_world.translation.copy()
        chk(3, abs(e10) < 1e-3 and abs(e60 - 1.0) < 1e-3, f"bevel_factor_end 第 10 帧 {e10:.4f}、第 60 帧 {e60:.4f}")
        chk(3, (h60 - Vector((2, 3, 3))).length < 0.05, f"第 60 帧光头应在 (2, 3, 3)，实际 {tuple(round(v, 3) for v in h60)}")
        sc.frame_set(1)
        hid1 = head.hide_render
        sc.frame_set(60 + 34 + 1)
        chk(3, hid1 and head.hide_render, "光头第 1 帧、f_gone+1 帧应隐藏")
    chk(3, path.total > 0, "path.total 应 >0")
    for f in (40, 56, 72):
        sc.frame_set(f)
        chk(4, abs(math.hypot(rig_e.location.x, rig_e.location.y) - 4.0) < 1e-3, f"第 {f} 帧环绕半径不是 4")
    ang = math.degrees(math.atan2(rig_e.location.x, rig_e.location.y))
    chk(4, abs(ang - 20.0) < 0.01, f"第 72 帧角度应 20°，实际 {ang:.3f}")
    loc_fc = [fc for fc in _fcurves(rig_e) if fc.data_path == "location"]
    keys = [[kp for kp in fc.keyframe_points if 40 - 1e-6 <= kp.co[0] <= 72 + 1e-6] for fc in loc_fc]
    chk(4, len(loc_fc) == 3 and all(len(k) == 33 and all(kp.interpolation == 'LINEAR' for kp in k) for k in keys),
        f"RIG_E 位置曲线在 40–72 应各 33 个 LINEAR 键，实际 {[len(k) for k in keys]}")
    chk(4, abs(orb["deg_per_s"] - 22.5) < 1e-3, f"deg_per_s 应 22.5，实际 {orb['deg_per_s']}")
    da, db = cam_a.data.dof, cam_b.data.dof
    dc = bpy.data.objects["CAM_C"].data.dof
    chk(5, sc.display.shading.use_dof, "Workbench 景深总开关没开")
    chk(5, da.use_dof and da.focus_object is not None and da.focus_object.name == "AIM_A"
        and abs(da.aperture_fstop - 2.0) < 1e-6, "CAM_A 应 f/2.0 对焦 AIM_A")
    fd = [fc for fc in _fcurves(cam_b.data) if fc.data_path == "dof.focus_distance"]
    nk = sum(len(fc.keyframe_points) for fc in fd)
    chk(5, db.use_dof and nk == 36 and fd and abs(fd[0].evaluate(72) - 3.0) < 1e-4,
        f"CAM_B 应有 36 个对焦距离键、第 72 帧 3.0，实际 {nk} 个")
    chk(5, not dc.use_dof, "CAM_C 不在表里，应关景深")
    sc.frame_set(1)

    # 渲 2 帧（1 和 37，各属一镜），走正式导出同一条 render(animation=True)
    sc.render.filepath = os.path.join(frames, "frame_")
    sc.frame_start, sc.frame_end, sc.frame_step = 1, 37, 36
    try:
        bpy.ops.render.render(animation=True)
    finally:
        sc.frame_start, sc.frame_end, sc.frame_step = 1, 72, 1

    for f in ("frame_0001.png", "frame_0037.png"):
        p = os.path.join(frames, f)
        chk(0, os.path.isfile(p) and os.path.getsize(p) > 0, f"缺渲染文件 {p}")
    sc.frame_set(37)
    chk(0, sc.camera.name == "CAM_B", f"第 37 帧相机应是 CAM_B，实际 {sc.camera.name}")
    sc.frame_set(1)
    chk(0, sc.camera.name == "CAM_A", f"第 1 帧相机应是 CAM_A，实际 {sc.camera.name}")
    s = Vector(sun_dir).normalized()
    chk(0, (Vector(sc.display.light_direction) - Vector((s.x, s.z, -s.y))).length <= 1e-4, "light_direction 换算不对")
    chk(0, cam_a.parent.name == "HEAD_A" and cam_a.parent.parent.name == "RIG_A", "相机层级不是 RIG → HEAD → CAM")
    chk(0, not any(is_limb_name(c.name) for c in hero.children), "躯体代理带了四肢")
    noise = [fc for fc in _fcurves(rig_d) if fc.data_path == "location"
             and any(m.type == 'NOISE' for m in fc.modifiers)]
    chk(0, len(noise) == 3, f"手持控制器应有 3 条带 Noise 的位置曲线，实际 {len(noise)}")
    p1 = cam_a.matrix_world.translation.copy()
    sc.frame_set(36)
    p2 = cam_a.matrix_world.translation.copy()
    chk(0, abs((p2 - p1).length - 2.0) <= 0.05, f"推轨位移应约 2 m，实际 {(p2 - p1).length:.3f}")
    sc.frame_set(37)
    upv = Vector((0, 0, 1))
    r0 = math.degrees(math.atan2(upv.dot(cam_b.matrix_world.col[0].xyz), upv.dot(cam_b.matrix_world.col[1].xyz)))
    sc.frame_set(72)
    r1 = math.degrees(math.atan2(upv.dot(cam_b.matrix_world.col[0].xyz), upv.dot(cam_b.matrix_world.col[1].xyz)))
    # 相机 roll +12° 后，世界"上"在画面里偏向右侧 = 地平线顺时针转、右边低
    chk(0, abs(r0) <= 0.5 and abs(r1 - 12.0) <= 0.5, f"荷兰角不对：第 37 帧 {r0:.2f}°，第 72 帧 {r1:.2f}°（应 0 与 +12）")

    # 组6：按像素量构图（掩码渲染后全部恢复）
    sc.frame_set(5)
    aa0, wc0 = sc.display.render_aa, tuple(sc.world.color)
    st = frame_stats(frame=1)
    hs, ts = st["chars"].get("CHR_Hero_图1", {}), st["chars"].get("CHR_Tiny_图3", {})
    chk(6, 0.005 < hs.get("area", 0.0) < 0.30 and hs.get("bbox") is not None,
        f"CHR_Hero_图1 面积应在 0.5%–30%，实际 {hs.get('area')}")
    chk(6, ts.get("area", 1.0) < 0.001, f"CHR_Tiny_图3 面积应 <0.1%，实际 {ts.get('area')}")
    body = tuple(bpy.data.objects["CHR_Hero_图1_Body"].color)
    chk(6, all(abs(a - b) < 1e-4 for a, b in zip(body, (0.55, 0.50, 0.45, 1.0))), f"hero 躯干颜色没恢复：{body}")
    sh = sc.display.shading
    chk(6, sh.light == 'STUDIO' and sh.show_shadows, "着色没恢复（light / show_shadows）")
    chk(6, sc.display.render_aa == aa0 and tuple(sc.world.color) == wc0, "render_aa 或世界色没恢复")
    chk(6, sc.camera is not None and sc.camera.name == "CAM_A" and sc.frame_current == 5,
        f"相机或当前帧没恢复：{sc.camera.name if sc.camera else None}，第 {sc.frame_current} 帧")
    sc.frame_set(1)
    dg = bpy.context.evaluated_depsgraph_get()
    pts = [o.evaluated_get(dg).matrix_world @ Vector(c) for o in _geom_parts(hero) for c in o.evaluated_get(dg).bound_box]
    ys = [v.y for v in (world_to_camera_view(sc, sc.camera, p) for p in pts) if v.z > 0]
    bb = max(0.0, min(1.0, max(ys))) - max(0.0, min(ys)) if ys else None     # 同 check_export._frame_ratio
    chk(6, bb is not None and hs.get("height", 1.0) <= bb + 0.02,
        f"像素画高 {hs.get('height')} 应 ≤ 包围盒画高 {bb} + 0.02")

    # 组7：候选机位对比图
    m37 = next(m for m in sc.timeline_markers if m.frame == 37)
    cam_before = sc.camera
    cmp = compare_cams(37, {"A": (35, (0.8, -7, 1.6), (0, 0, 1.3)), "B": (50, (3, -6, 1.6), (0, 0, 1.3))}, out)
    chk(7, os.path.isfile(cmp["grid"]) and len(cmp["tiles"]) == 2
        and all(os.path.isfile(p) for p in cmp["tiles"].values()), "对比图或两张候选图没生成")
    chk(7, m37.camera is not None and m37.camera.name == "CAM_B", "第 37 帧标记的相机没恢复成 CAM_B")
    chk(7, sc.camera == cam_before, "scene.camera 没恢复")
    chk(7, not any(o.name.startswith("TMP_") for o in bpy.data.objects)
        and not any(c.name.startswith("TMP_") for c in bpy.data.cameras), "临时相机没删干净")
    chk(7, not sc.render.use_stamp and sc.render.resolution_percentage == 100, "stamp 或分辨率百分比没恢复")

    # 组8：审看版字幕（先用 Blender 自己的 FFMPEG 出一段干净 mp4）
    clean = os.path.join(out, "selftest_clean.mp4")
    review = os.path.join(out, "selftest_review.mp4")
    r = sc.render
    im = r.image_settings
    fmt0 = (im.media_type, im.file_format, im.color_mode)
    keep0 = (r.resolution_percentage, sc.frame_start, sc.frame_end, sc.frame_step, r.filepath)
    try:
        im.media_type = 'VIDEO'
        im.file_format = 'FFMPEG'
        ff = r.ffmpeg
        ff.format, ff.codec, ff.constant_rate_factor, ff.ffmpeg_preset, ff.audio_codec = \
            'MPEG4', 'H264', 'HIGH', 'GOOD', 'NONE'
        r.resolution_percentage = 60      # 50% 是 427×240：H.264 要偶数边，Blender 报 width not divisible by 2
        sc.frame_start, sc.frame_end, sc.frame_step = 1, 24, 1
        r.filepath = clean
        bpy.ops.render.render(animation=True)
    finally:
        im.media_type, im.file_format, im.color_mode = fmt0
        r.resolution_percentage, sc.frame_start, sc.frame_end, sc.frame_step, r.filepath = keep0
    subs = burn_subs(clean, review, [(3, 20, "英雄", "测试字幕")], [("1", 1, 24)])
    chk(8, os.path.isfile(review) and os.path.getsize(review) > 0, "审看版 mp4 没生成")
    chk(8, [x.name for x in bpy.data.scenes] == [sc.name], f"临时场景没删：{[x.name for x in bpy.data.scenes]}")
    probe = shutil.which("ffprobe") or next((p for p in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe")
                                             if os.path.isfile(p)), None)
    if not probe:
        ff_exe = shutil.which("ffmpeg")
        if ff_exe:
            cand = os.path.join(os.path.dirname(ff_exe), "ffprobe.exe" if os.name == "nt" else "ffprobe")
            probe = cand if os.path.isfile(cand) else None
    nb = None
    if probe and os.path.isfile(review):
        res = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-count_frames",
                              "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", review],
                             capture_output=True, text=True)
        nb = res.stdout.strip()
        chk(8, nb == "24", f"审看版应 24 帧，ffprobe 读出 {nb!r}")

    sc.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "selftest.blend"))

    # 组9：整体重排时间（存盘之后跑，selftest.blend 不受影响）
    def xs(idb, dp):
        return sorted(kp.co[0] for fc in _fcurves(idb) if fc.data_path == dp for kp in fc.keyframe_points)

    rt = retime([(1, 36, 1, 18), (37, 72, 19, 60)])
    rx = xs(rig_a, "location")
    chk(9, any(abs(x - 18) < 1e-6 for x in rx) and not any(abs(x - 36) < 1e-6 for x in rx),
        f"RIG_A 第 36 帧的键应到 18，现有 {sorted(set(round(x, 3) for x in rx))}")
    fdx = xs(cam_b.data, "dof.focus_distance")
    chk(9, bool(fdx) and abs(fdx[-1] - 60) < 1e-6, f"CAM_B 对焦距离最后一个键应在 60，实际 {fdx[-1] if fdx else None}")
    t60 = 19 + 23 * 41 / 35
    bx = xs(bpy.data.objects["FX_test_亮芯"].data, "bevel_factor_end")
    chk(9, any(abs(x - t60) < 0.01 for x in bx), f"光带 bevel_factor_end 第 60 帧的键应到 {t60:.2f}")
    chk(9, any(m.frame == 19 and m.camera is not None and m.camera.name == "CAM_B" for m in sc.timeline_markers),
        "第 37 帧的标记应到 19")
    chk(9, sc.frame_end == 60, f"frame_end 应为 60，实际 {sc.frame_end}")
    rt2 = retime([(1, 36, 1, 18), (37, 72, 19, 60)])
    chk(9, rt2.get("skipped") is True and any(abs(x - 18) < 1e-6 for x in xs(rig_a, "location")),
        "同样的 retime 第二次应跳过")

    dt = time.time() - t0
    print("SELFTEST info:", info)
    print(f"SELFTEST roll: f37={r0:.2f}° f72={r1:.2f}°（正值 = 世界上方在画面里偏右 = 地平线顺时针转）")
    print(f"SELFTEST 组1 起身 drop={up['drop']}；组3 光带 total={path.total:.2f} m；组4 环绕 {orb}")
    print(f"SELFTEST 组5 景深 {dof}")
    print(f"SELFTEST 组6 frame_stats res={st['res']} sky={st['sky']} env={st['env']} "
          f"Hero={hs} Tiny={ts} 包围盒画高={bb:.4f}" if bb is not None else "SELFTEST 组6 包围盒画高 None")
    print(f"SELFTEST 组7 {cmp}")
    print(f"SELFTEST 组8 {subs}，ffprobe 帧数 {nb}")
    print(f"SELFTEST 组9 {rt}；第二次 {rt2}")
    for g in range(0, 10):
        bad_g = [e for e in errs if e.startswith(f"组{g}：")]
        print(f"SELFTEST 组{g}：{'不过' if bad_g else '过'}" + ("（原有断言）" if g == 0 else ""))
    print(f"SELFTEST 用时 {dt:.1f} s")
    if errs:
        for e in errs:
            print("SELFTEST FAIL:", e)
        sys.exit(1)
    print("SELFTEST OK: 2 帧已渲到", frames, "；场景存为", os.path.join(out, "selftest.blend"))


if __name__ == "__main__" and _launched_as_script():
    try:
        _selftest()
    except SystemExit:
        raise
    except Exception as e:  # 自测失败要让进程非零退出
        import traceback
        traceback.print_exc()
        print("SELFTEST FAIL:", e)
        sys.exit(1)

# -*- coding: utf-8 -*-
"""seedance-previz 帮助函数库：纯 bpy，无第三方依赖。

在 Higgs 的 bl_execute 里用（后台 Blender 会话）：
    import sys, os, importlib
    d = os.path.expanduser("~/.claude/skills/seedance-previz/scripts")
    if d not in sys.path: sys.path.insert(0, d)
    import previz_lib as pv; importlib.reload(pv)
    pv.setup_workbench(res=(1280, 544), fps=24, sun_dir=(-0.6, 0.75, 0.3))

命令行自测（只在空白会话里跑，会建场景、渲 2 帧到 /tmp/seedance-previz-selftest/）：
    /Applications/Blender.app/Contents/MacOS/Blender --background --python previz_lib.py

约定：米制，Z 向上，角色正面 = 本地 -Y。新建的物体都进 PREVIZ 集合；
同名物体如果不在 PREVIZ 集合里，函数直接报错，不覆盖用户的东西。
"""
import math
import os
import re
import sys

import bmesh
import bpy
from mathutils import Vector

COLL = "PREVIZ"
GREY = (0.5, 0.5, 0.5)
# Blender 5.2.2 实测：Workbench 默认摄影棚光（Default）开世界坐标时，
# studiolight_rotate_z = 0 的主光方位约 -108°（从 +X 逆时针量），rotate_z 加大 = 光顺时针转。
STUDIO_AZ0_DEG = -108.0
# 四肢命名：和 check_export.py 用同一条规则（_ArmL、_Leg_R、.Wing、_Hands、臂 / 腿 / 翅）
LIMB_RE = re.compile(r"(?i)(?:^|[_\-. ])(?:arm|leg|wing|hand|foot)s?(?:[_\-. ]?[lr])?(?:$|[_\-. \d])|臂|腿|翅")


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

def torso_proxy(name, height, color, face_dir=(0.0, -1.0, 0.0), loc=(0.0, 0.0, 0.0),
                head_ratio=1.0 / 7.0, width_ratio=0.28, depth_ratio=0.65):
    """躯体代理：胶囊躯干 + 头球 + 嘴部小球，无四肢。返回根空物体（原点在脚底）。
    name 用 CHR_<角色>_<图N>；height 米；face_dir 是脸朝的世界方向（嘴部小球标朝向）。
    头身比 head_ratio 默认 1/7，猿类或 Q 版可改 1/5～1/4。"""
    if LIMB_RE.search(name):
        raise ValueError(f"代理名 {name} 像四肢命名：check_export 会当成四肢，换个名字")
    root = _empty(name, loc, size=height * 0.15)
    fx, fy = face_dir[0], face_dir[1]
    if abs(fx) + abs(fy) < 1e-9:
        raise ValueError("face_dir 要有水平分量")
    root.rotation_euler = (0.0, 0.0, math.atan2(fx, -fy))  # 本地 -Y 转到 face_dir

    head_d = height * head_ratio
    rh = head_d / 2.0
    rb = height * width_ratio / 2.0
    body_h = height - head_d + 0.15 * head_d          # 躯干顶稍微插进头球
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
    head = _mesh_obj(f"{name}_Head", bm, (0.0, 0.0, height - rh), color)

    rm = rh * 0.42
    dark = tuple(c * 0.75 for c in _rgba(color)[:3])  # 同色相、同饱和度，暗一档
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=rm)
    muzzle = _mesh_obj(f"{name}_Muzzle", bm, (0.0, -rh * 0.85, height - rh * 1.1), dark)

    for part in (body, head, muzzle):
        for p in part.data.polygons:
            p.use_smooth = True
        _parent(part, root)
    root["previz_height"] = height
    return root


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


# ---------- 渲染设置 ----------

def setup_workbench(res=(1280, 720), fps=24, sun_dir=(-0.5, 0.6, 0.6), frame_range=None,
                    light="STUDIO", bg=(0.35, 0.35, 0.37)):
    """Workbench 白模渲染：物体色、投影、cavity、Standard 视图变换、关景深。
    sun_dir 是"光从哪来"：从场景指向太阳的世界方向，z 要 >0。如 (-0.6, 0.75, 0.3) = 光从左后方低斜来。
    Workbench 不认灯物体：投影方向写进 scene.display.light_direction（5.2.2 实测换算），
    摄影棚光改世界坐标并转到同一方位；另建 LGT_sun 记录光向（切 EEVEE 时直接可用）。"""
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

    sh = sc.display.shading
    sh.light = light
    sh.color_type = 'OBJECT'
    sh.show_shadows = True
    sh.shadow_intensity = 0.6
    sh.show_cavity = True
    sh.show_specular_highlight = False
    if hasattr(sh, "use_dof"):
        sh.use_dof = False
    sc.display.light_direction = (s.x, s.z, -s.y)   # 光行进方向 = (-lx, lz, -ly)
    az = math.degrees(math.atan2(s.y, s.x))
    if light == 'STUDIO':
        try:
            sh.studio_light = 'Default'
        except TypeError:
            pass
        sh.use_world_space_lighting = True
        rz = (STUDIO_AZ0_DEG - az + 180.0) % 360.0 - 180.0
        sh.studiolight_rotate_z = math.radians(rz)

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
            "studiolight_rotate_z_deg": round(math.degrees(sh.studiolight_rotate_z), 1)}


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


# ---------- 自测 ----------

def _launched_as_script():
    argv = sys.argv
    for i, a in enumerate(argv[:-1]):
        if a in ("--python", "-P") and os.path.basename(argv[i + 1]) == "previz_lib.py":
            return True
    return False


def _selftest():
    extra = {o.name for o in bpy.data.objects} - {"Cube", "Light", "Camera"}
    if bpy.data.filepath or extra:
        raise RuntimeError("自测只在空白会话里跑（会清空场景），当前会话有内容")
    out = "/tmp/seedance-previz-selftest"
    frames = os.path.join(out, "frames")
    os.makedirs(frames, exist_ok=True)
    for f in os.listdir(frames):
        if f.endswith(".png"):
            os.remove(os.path.join(frames, f))
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    sc = _scene()
    sun_dir = (-0.5, 0.6, 0.62)
    info = setup_workbench(res=(854, 480), fps=24, sun_dir=sun_dir, frame_range=(1, 72))

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
    set_marker_camera(1, cam_a)
    set_marker_camera(37, cam_b)
    hide_overlays()

    # 渲 2 帧（1 和 37，各属一镜），走正式导出同一条 render(animation=True)
    sc.render.filepath = os.path.join(frames, "frame_")
    sc.frame_start, sc.frame_end, sc.frame_step = 1, 37, 36
    try:
        bpy.ops.render.render(animation=True)
    finally:
        sc.frame_start, sc.frame_end, sc.frame_step = 1, 72, 1

    errs = []
    for f in ("frame_0001.png", "frame_0037.png"):
        p = os.path.join(frames, f)
        if not (os.path.isfile(p) and os.path.getsize(p) > 0):
            errs.append(f"缺渲染文件 {p}")
    sc.frame_set(37)
    if sc.camera.name != "CAM_B":
        errs.append(f"第 37 帧相机应是 CAM_B，实际 {sc.camera.name}")
    sc.frame_set(1)
    if sc.camera.name != "CAM_A":
        errs.append(f"第 1 帧相机应是 CAM_A，实际 {sc.camera.name}")
    s = Vector(sun_dir).normalized()
    if (Vector(sc.display.light_direction) - Vector((s.x, s.z, -s.y))).length > 1e-4:
        errs.append("light_direction 换算不对")
    if not (cam_a.parent.name == "HEAD_A" and cam_a.parent.parent.name == "RIG_A"):
        errs.append("相机层级不是 RIG → HEAD → CAM")
    if any(LIMB_RE.search(c.name) for c in hero.children):
        errs.append("躯体代理带了四肢")
    noise = [fc for fc in _fcurves(rig_d) if fc.data_path == "location"
             and any(m.type == 'NOISE' for m in fc.modifiers)]
    if len(noise) != 3:
        errs.append(f"手持控制器应有 3 条带 Noise 的位置曲线，实际 {len(noise)}")
    p1 = cam_a.matrix_world.translation.copy()
    sc.frame_set(36)
    p2 = cam_a.matrix_world.translation.copy()
    if abs((p2 - p1).length - 2.0) > 0.05:
        errs.append(f"推轨位移应约 2 m，实际 {(p2 - p1).length:.3f}")
    sc.frame_set(37)
    up = Vector((0, 0, 1))
    r0 = math.degrees(math.atan2(up.dot(cam_b.matrix_world.col[0].xyz), up.dot(cam_b.matrix_world.col[1].xyz)))
    sc.frame_set(72)
    r1 = math.degrees(math.atan2(up.dot(cam_b.matrix_world.col[0].xyz), up.dot(cam_b.matrix_world.col[1].xyz)))
    # 相机 roll +12° 后，世界"上"在画面里偏向右侧 = 地平线顺时针转、右边低
    if abs(r0) > 0.5 or abs(r1 - 12.0) > 0.5:
        errs.append(f"荷兰角不对：第 37 帧 {r0:.2f}°，第 72 帧 {r1:.2f}°（应 0 与 +12）")
    sc.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "selftest.blend"))

    print("SELFTEST info:", info)
    print(f"SELFTEST roll: f37={r0:.2f}° f72={r1:.2f}°（正值 = 世界上方在画面里偏右 = 地平线顺时针转）")
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

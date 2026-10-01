# -*- coding: utf-8 -*-
"""Seedance 白模导出前自查。只读：采样时会切帧，结束后恢复原帧和原相机。
像素画高会做掩码渲染（previz_lib.frame_stats），渲完恢复颜色、着色和渲染设置。

命令行：
    Blender --background 场景.blend --python check_export.py -- --out 报告.json [--grain coarse|fine] [--chr 名1,名2]
        [--range 首帧 末帧] [--vivid] [--no-pixel]
Blender MCP 的 execute_blender_code 里（开着窗口的 Blender）：
    import sys, os, importlib
    d = os.path.join(os.path.expanduser("~"), "Documents", "Codex", "seedance-previz", "scripts")
    if d not in sys.path: sys.path.insert(0, d)
    import check_export as ce; importlib.reload(ce)
    result = ce.run(out_json="/绝对路径/片名_自查_260925-1.json", grain="coarse")
    分段自查加 frame_range=(546, 876)（查完恢复场景帧范围）；用户指定鲜明色加 vivid=True；只按包围盒算加 pixel=False。

查什么（编号对应 references/seedance-whitebox-rules.md 的自查 10 项）：
② CHR_ 角色的四肢：子物体名（_ArmL、_Leg_R、_Wing、_Hand；中文整段是臂 / 腿 / 翅 / 手 / 脚这类词，
   和 previz_lib.is_limb_name 同一条规则）或骨骼
③ 物体色饱和度 >0.3（按显示色 RGB 算 (最大-最小)/最大）：角色取根下全部部件的最大值（不管隐藏）；
   vivid=True / --vivid（用户指定鲜明色）时角色超标只报警告；环境物体按采样帧里看得见的算，报警告
④ 按时间轴标记分镜，每镜起 / 中 / 末三帧算 CHR_ 角色的画高占比与本镜位移（相对身高）；画高默认按像素量
   （掩码渲染，25% 分辨率），--no-pixel 按包围盒投影；够大但不动只记备注
⑤ stamp 烧字、会渲出来的辅助线和蜡笔、相机显示与视口 overlay；景深不报警告，开了景深的相机列在 settings.dof
⑥ Workbench 投影开没开、和 LGT_sun 方向对不对得上；摄影棚光跟相机走（setup_workbench follow_camera）只记备注
⑦⑧ 总时长、fps、分辨率、宽高比；⑨ 列出切点帧，帧范围外的标记只记备注（分段自查时正常）；① ⑩ 与颜色映射留给人工
结论：不通过 / 有警告 / 通过；备注单列，不影响结论。
--chr 可把不带 CHR_ 前缀的旧场景物体（如 Yuansan）当角色查。
"""
import argparse
import json
import math
import os
import re
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import previz_lib  # noqa: E402  四肢命名 is_limb_name、像素画高 frame_stats

BONE_RE = re.compile(r"(?i)arm|leg|thigh|shin|calf|hand|foot|wing|clavicle|elbow|knee|臂|腿|翅")
GUIDE_RE = re.compile(r"(?i)guide|traj|path|axis|helper|辅助|轨迹|坐标")
GEOM = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}
GP = {'GREASEPENCIL', 'GPENCIL'}
SAT_MAX, H_MIN, MOVE_MIN = 0.3, 0.10, 0.5


def _sat(rgb):
    mx, mn = max(rgb), min(rgb)
    return 0.0 if mx <= 1e-6 else (mx - mn) / mx


def _visible(ob, vl):
    if ob.hide_render or ob.name not in vl.objects:
        return False
    return not any(c.hide_render for c in ob.users_collection)


def _chr_roots(sc, prefix, extra):
    def is_chr(o):
        return o.name.startswith(prefix) or o.name in extra
    roots = []
    for ob in sc.objects:
        if not is_chr(ob):
            continue
        p = ob.parent
        while p is not None and not is_chr(p):
            p = p.parent
        if p is None:
            roots.append(ob)
    return roots


def _parts(root, vl):
    return [o for o in [root] + list(root.children_recursive) if o.type in GEOM and _visible(o, vl)]


def _limbs(root, vl):
    """只算会渲出来的：四肢用 hide_render 藏起来就不算。骨骼只算驱动着可见网格的。"""
    desc = [root] + list(root.children_recursive)
    objs = [o.name for o in desc[1:] if previz_lib.is_limb_name(o.name) and _visible(o, vl)]
    rigs = set()
    for o in desc:
        if o.type not in GEOM or not _visible(o, vl):
            continue
        for m in getattr(o, "modifiers", []):
            if m.type == 'ARMATURE' and m.object is not None:
                rigs.add(m.object)
        if o.parent is not None and o.parent.type == 'ARMATURE' and o.parent_type in ('ARMATURE', 'BONE'):
            rigs.add(o.parent)
    bones = sorted({b.name for a in rigs for b in a.data.bones if BONE_RE.search(b.name)})
    return objs, bones, sorted(a.name for a in rigs)


def _colors(ob, sh, engine):
    if engine != 'BLENDER_WORKBENCH':
        return None
    ct = sh.color_type
    if ct == 'OBJECT':
        return [tuple(ob.color[:3])]
    if ct == 'MATERIAL':
        mats = [s.material for s in ob.material_slots if s.material]
        return [tuple(m.diffuse_color[:3]) for m in mats] or [(0.8, 0.8, 0.8)]
    if ct == 'SINGLE':
        return [tuple(sh.single_color[:3])]
    return None


def _frame_ratio(sc, cam, pts):
    xs, ys = [], []
    for p in pts:
        v = world_to_camera_view(sc, cam, p)
        if v.z > 0:
            xs.append(v.x)
            ys.append(v.y)
    if not xs or max(xs) < 0 or min(xs) > 1 or max(ys) < 0 or min(ys) > 1:
        return None
    return max(0.0, min(1.0, max(ys)) - max(0.0, min(ys)))


def _shots(sc):
    fs, fe = sc.frame_start, sc.frame_end
    ms = sorted((m for m in sc.timeline_markers if fs <= m.frame <= fe), key=lambda m: m.frame)
    shots = []
    if not ms or ms[0].frame > fs:
        shots.append({"start": fs, "end": (ms[0].frame - 1) if ms else fe, "marker": None})
    for i, m in enumerate(ms):
        end = ms[i + 1].frame - 1 if i + 1 < len(ms) else fe
        shots.append({"start": m.frame, "end": end, "marker": m.name,
                      "marker_camera": m.camera.name if m.camera else None})
    return shots


def _dof(sc):
    """开了景深的相机：{相机名: {"fstop", "focus": 对焦物体名 / 距离 m / "keyed"（逐帧移焦）}}。"""
    out = {}
    for ob in sorted((o for o in sc.objects if o.type == 'CAMERA'), key=lambda o: o.name):
        d = ob.data.dof
        if not d.use_dof:
            continue
        keyed = any(fc.data_path == "dof.focus_distance" and len(fc.keyframe_points)
                    for fc in previz_lib._fcurves(ob.data))
        if keyed:
            focus = "keyed"
        elif d.focus_object is not None:
            focus = d.focus_object.name
        else:
            focus = round(d.focus_distance, 3)
        out[ob.name] = {"fstop": round(d.aperture_fstop, 2), "focus": focus}
    return out


def run(out_json=None, grain="coarse", chr_names=None, prefix="CHR_", quiet=False, vivid=False,
        frame_range=None, pixel=True):
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    r = sc.render
    sh = sc.display.shading
    engine = r.engine
    extra = set(chr_names or [])
    fails, warns, notes = [], [], []

    def fail(item, msg):
        fails.append({"item": item, "detail": msg})

    def warn(item, msg):
        warns.append({"item": item, "detail": msg})

    def note(item, msg):
        notes.append({"item": item, "detail": msg})

    orig_range = (sc.frame_start, sc.frame_end)
    orig_frame, orig_sub, orig_cam = sc.frame_current, sc.frame_subframe, sc.camera
    try:
        if frame_range is not None:
            a, b = int(frame_range[0]), int(frame_range[1])
            if b < a:
                raise ValueError(f"frame_range 首帧 {a} 大于末帧 {b}")
            sc.frame_start, sc.frame_end = a, b

        fps = r.fps / (r.fps_base or 1.0)
        w = round(r.resolution_x * r.resolution_percentage / 100)
        h = round(r.resolution_y * r.resolution_percentage / 100)
        frames = sc.frame_end - sc.frame_start + 1
        dur = frames / fps
        settings = {"file": bpy.data.filepath, "scene": sc.name, "engine": engine, "grain": grain,
                    "fps": round(fps, 3), "res": [w, h], "aspect": round(w / h, 3),
                    "frames": [sc.frame_start, sc.frame_end], "duration_s": round(dur, 3),
                    "segment": frame_range is not None, "vivid": bool(vivid)}

        # ⑦⑧ 时长、fps、分辨率
        if not 2.0 <= dur <= 30.0:
            fail("⑦", f"总时长 {dur:.2f} s，要 2–30 s（一段 ≤30 s）")
        if not 24.0 <= fps <= 60.0:
            fail("⑧", f"fps {fps:g}，要 24–60")
        if min(w, h) < 480:
            fail("⑧", f"分辨率 {w}×{h}，短边 {min(w, h)} <480")
        if max(w, h) > 4096:
            fail("⑧", f"分辨率 {w}×{h}，长边超过 4K")
        if not 0.4 <= w / h <= 2.5:
            fail("⑧", f"宽高比 {w / h:.3f}，要在 0.4–2.5")
        if w % 2 or h % 2:
            warn("⑧", f"分辨率 {w}×{h} 有奇数边，h264 会被 encode.py 裁掉 1 像素")

        # ⑤ 会渲进画面的东西 + 显示开关
        if r.use_stamp:
            fail("⑤", "stamp 烧字开着（帧号等文字会渲进画面）")
        for ob in sc.objects:
            if not _visible(ob, vl):
                continue
            if ob.type in GP:
                fail("⑤", f"{ob.name} 是蜡笔物体，会渲进画面")
            elif ob.type in GEOM and GUIDE_RE.search(ob.name):
                fail("⑤", f"{ob.name} 看名字像辅助线 / 轨迹 / 坐标轴，而且会渲出来")
            if ob.show_name or ob.show_axis:
                warn("⑤", f"{ob.name} 显示名字或轴向（F12 不画；插件或视口渲染会带上）")
        cams = {m.camera for m in sc.timeline_markers if m.camera} | ({sc.camera} if sc.camera else set())
        for cam in sorted(cams, key=lambda c: c.name):
            on = [f for f in ("show_limits", "show_mist", "show_sensor", "show_name", "show_safe_areas")
                  if getattr(cam.data, f, False)]
            if on:
                warn("⑤", f"{cam.name} 的相机显示开着：{', '.join(on)}（F12 不画；插件或视口渲染会带上）")
        ov = sum(1 for s in bpy.data.screens for a in s.areas if a.type == 'VIEW_3D'
                 for sp in a.spaces if sp.type == 'VIEW_3D' and sp.overlay.show_overlays)
        if ov:
            warn("⑤", f"{ov} 个视口的 overlay 开着（F12 不画；桌面插件或视口渲染前跑 hide_overlays()）")
        settings["dof"] = _dof(sc)
        if engine == 'BLENDER_WORKBENCH':
            settings["dof_switch"] = bool(getattr(sh, "use_dof", False))

        # ⑥ 光
        suns = [o for o in sc.objects if o.type == 'LIGHT' and o.data.type == 'SUN']
        if engine == 'BLENDER_WORKBENCH':
            if not sh.show_shadows:
                fail("⑥", "Workbench 投影没开（shading.show_shadows）")
            lgt = bpy.data.objects.get("LGT_sun")
            if lgt is None or lgt.type != 'LIGHT':
                warn("⑥", "没有 LGT_sun：投影方向无法对照任务卡的光向（用 setup_workbench 设）")
            else:
                s = lgt.matrix_world.col[2].xyz.normalized()          # 灯的 +Z 指向太阳
                ang = math.degrees(Vector((s.x, s.z, -s.y)).angle(Vector(sc.display.light_direction)))
                if ang > 10.0:
                    warn("⑥", f"Workbench 投影方向和 LGT_sun 差 {ang:.0f}°")
            if sh.light == 'STUDIO' and not sh.use_world_space_lighting:
                if sc.get("previz_light_follow"):
                    note("⑥", "摄影棚光跟相机走（setup_workbench follow_camera），投影方向仍按 LGT_sun")
                else:
                    warn("⑥", "摄影棚光跟着相机转：切镜后亮面会换边（setup_workbench 会改成世界坐标）")
        else:
            warn("⑥", f"渲染器是 {engine}：颜色和光看材质与灯，脚本只数了太阳灯")
            if not any(o.data.use_shadow for o in suns):
                warn("⑥", "没有带投影的太阳灯")
        if len(suns) > 1:
            warn("⑥", f"有 {len(suns)} 盏太阳灯：{', '.join(o.name for o in suns)}，只留一盏主光")

        # ⑨ 切点
        shots = _shots(sc)
        if not sc.timeline_markers:
            warn("⑨", "没有时间轴标记：整段当一镜查")
        for m in sc.timeline_markers:
            if m.frame > sc.frame_end or m.frame < sc.frame_start:
                note("⑨", f"标记 {m.name} 在第 {m.frame} 帧，在帧范围 {sc.frame_start}–{sc.frame_end} 外"
                          f"（分段自查时正常）")
            elif m.camera is None:
                warn("⑨", f"标记 {m.name}（第 {m.frame} 帧）没绑相机")

        # ②③④ 角色
        roots = _chr_roots(sc, prefix, extra)
        missing = sorted(extra - {o.name for o in sc.objects})
        if missing:
            warn("④", f"--chr 指定的物体不在场景里：{', '.join(missing)}")
        if not roots:
            warn("④", f"场景里没有 {prefix} 角色（或 --chr 指定的物体），画高与四肢没法查")
        chars, hot = {}, {}
        for root in roots:
            objs, bones, rigs = _limbs(root, vl)
            sats = {}
            for o in [root] + list(root.children_recursive):   # 全部几何部件，不管隐藏；空物体根不算
                if o.type in GEOM:
                    cols = _colors(o, sh, engine)
                    if cols:
                        sats[o.name] = max(_sat(c) for c in cols)
            chars[root.name] = {"limb_objects": objs, "limb_bones": bones[:12], "armatures": rigs,
                                "sat_max": round(max(sats.values()), 3) if sats else None}
            hot[root.name] = sorted(n for n, s in sats.items() if s > SAT_MAX)
            if objs or bones:
                what = "、".join(objs[:6] + bones[:6])
                if grain == "coarse":
                    fail("②", f"{root.name} 带四肢：{what}（粗白模只留躯体；非留不可就在提示词写全四肢动作序列并在交接卡注明）")
                else:
                    chars[root.name]["note"] = "细颗粒度：完整模型带四肢属正常"
            elif rigs:
                warn("②", f"{root.name} 挂着骨骼 {', '.join(rigs)}，骨骼名没认出四肢，人工确认")

        obj_sat = {}
        shot_reports = []
        use_pixel = bool(pixel)
        for i, st in enumerate(shots, 1):
            s0, s1 = st["start"], st["end"]
            samples = sorted({s0, (s0 + s1) // 2, s1})
            per = {rt.name: {"ratios": [], "bbox": [], "areas": [], "boxes": [], "centers": [], "height": None,
                             "pixel": True} for rt in roots}
            cam_names = []
            for f in samples:
                sc.frame_set(f)
                cam = sc.camera
                cam_names.append(cam.name if cam else None)
                for ob in sc.objects:
                    if ob.type in GEOM and _visible(ob, vl):
                        cols = _colors(ob, sh, engine)
                        if cols:
                            obj_sat[ob.name] = max(obj_sat.get(ob.name, 0.0), max(_sat(c) for c in cols))
                px = None
                if use_pixel and cam is not None and roots:
                    try:
                        px = previz_lib.frame_stats(frame=f, chars=roots, res_pct=25)["chars"]
                    except Exception as e:  # 渲不了就退回包围盒，只报一次
                        use_pixel = False
                        warn("④", "掩码渲染失败，画高按包围盒算：" + str(e))
                dg = bpy.context.evaluated_depsgraph_get()
                for rt in roots:
                    parts = _parts(rt, vl)
                    if not parts:
                        continue
                    pts = []
                    for o in parts:
                        oe = o.evaluated_get(dg)
                        pts += [oe.matrix_world @ Vector(c) for c in oe.bound_box]
                    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
                    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
                    d = per[rt.name]
                    d["centers"].append((lo + hi) / 2.0)
                    d["height"] = max(d["height"] or 0.0, hi.z - lo.z)
                    rb = _frame_ratio(sc, cam, pts) if cam else None
                    d["bbox"].append(rb)
                    if px is not None:
                        s = px.get(rt.name) or {}
                        area = s.get("area", 0.0)
                        # 包围盒在画框里、像素为 0 = 被挡住，按 0 算；两样都没有 = 不在画里
                        d["ratios"].append(s.get("height", 0.0) if (area > 0 or rb is not None) else None)
                        d["areas"].append(area)
                        d["boxes"].append(s.get("bbox"))
                    else:
                        d["pixel"] = False
                        d["ratios"].append(rb)
            subj, big_still = [], []
            for rt in roots:
                d = per[rt.name]
                seen = [x for x in d["ratios"] if x is not None]
                if not seen:
                    continue
                c = d["centers"]
                move = max(((a - b).length for a in c for b in c), default=0.0)
                body = d["height"] or 1e-6
                hmax, mv = max(seen), round(move / body, 3)
                small, still = hmax < H_MIN, mv < MOVE_MIN
                how = "像素" if d["pixel"] else "包围盒"
                label = f"镜{i} {rt.name}：画高 {hmax * 100:.1f}%（{how}）、位移 {mv:.2f} 身高"
                if small and still:
                    verdict = "不通过"
                    fail("④", f"{label}——太小又不动，按 L121 会被整个丢掉")
                elif small:
                    verdict = "警告"
                    warn("④", f"{label}——偏小（<10%），靠在动撑着，交接卡写进风险")
                elif still:
                    verdict = "备注"
                    big_still.append(f"{rt.name}（{hmax * 100:.0f}%）")
                else:
                    verdict = "通过"
                item = {"name": rt.name, "height_ratio": [None if x is None else round(x, 4) for x in d["ratios"]],
                        "height_ratio_max": round(hmax, 4), "method": "pixel" if d["pixel"] else "bbox",
                        "height_ratio_bbox": [None if x is None else round(x, 4) for x in d["bbox"]],
                        "move_body": mv, "height_m": round(body, 3), "verdict": verdict}
                if d["pixel"]:
                    item["area"] = d["areas"]
                    item["bbox"] = d["boxes"]
                subj.append(item)
            if big_still:
                note("④", f"镜{i} 够大但位移不到半个身高：{'、'.join(big_still)}——近景对白、静止巨物可接受；"
                          f"要让模型读出走位的主体得动起来")
            if not any(cam_names):
                fail("⑨", f"镜{i}（第 {s0}–{s1} 帧）没有相机，渲不出来")
            if roots and not subj:
                warn("④", f"镜{i}（第 {s0}–{s1} 帧）没有角色入画（空镜可忽略）")
            shot_reports.append({"shot": i, "frames": [s0, s1],
                                 "seconds": [round((s0 - sc.frame_start) / fps, 3),
                                             round((s1 - sc.frame_start + 1) / fps, 3)],
                                 "marker": st["marker"], "cameras": sorted(set(n for n in cam_names if n)),
                                 "samples": samples, "subjects": subj})
        settings["height_method"] = "pixel" if (pixel and use_pixel) else "bbox"

        # ③ 颜色
        chr_parts = {}
        for rt in roots:
            for o in [rt] + list(rt.children_recursive):
                chr_parts[o.name] = rt.name
        if engine == 'BLENDER_WORKBENCH' and sh.color_type not in ('OBJECT', 'MATERIAL', 'SINGLE'):
            warn("③", f"Workbench 颜色来源是 {sh.color_type}，脚本查不了饱和度")
        for rt, names in sorted(hot.items()):
            if not names:
                continue
            msg = (f"{rt} 颜色饱和度最高 {chars[rt]['sat_max']:.2f} >0.3（{len(names)} 件：{'、'.join(names[:4])}"
                   f"{'…' if len(names) > 4 else ''}）")
            if vivid:
                warn("③", msg + "：用户指定鲜明色，交接卡加'服装颜色以参考图为准'")
            else:
                fail("③", msg + "：会渗进成片，改中性灰阶或压到 0.3 以下的近服装色")
        env = sorted(((s, n) for n, s in obj_sat.items() if s > SAT_MAX and n not in chr_parts), reverse=True)
        for s, name in env[:8]:
            warn("③", f"{name} 颜色饱和度 {s:.2f} >0.3：环境色也可能渗进成片")
        if len(env) > 8:
            warn("③", f"另有 {len(env) - 8} 件环境物体饱和度 >0.3，见 JSON")
        report_env = [{"name": n, "sat": round(s, 3)} for s, n in env]

        manual = ["① 粗 / 细选对了（本次按 %s 查）" % ("粗颗粒度" if grain == "coarse" else "细颗粒度"),
                  "③ 颜色 → 图N 映射已写进交接卡" + ("；鲜明色要加'服装颜色以参考图为准'" if vivid else ""),
                  "⑥ 光向和任务卡一致",
                  "⑨ 切点帧和镜头表一致：" + "、".join(f"镜{s['shot']} 第{s['frames'][0]}帧" for s in shot_reports),
                  "⑩ mp4 首 / 中 / 末帧已打开看过（encode.py 出 _首中末.png）"]
    finally:
        sc.frame_start, sc.frame_end = orig_range
        sc.frame_set(orig_frame, subframe=orig_sub)
        sc.camera = orig_cam

    verdict = "不通过" if fails else ("有警告" if warns else "通过")
    report = {"verdict": verdict, "settings": settings, "shots": shot_reports, "characters": chars,
              "saturated_env": report_env, "fail": fails, "warn": warns, "note": notes, "manual": manual}
    if out_json:
        os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        report["json"] = os.path.abspath(out_json)
    if not quiet:
        _print(report)
    return report


def _print(rep):
    st = rep["settings"]
    print(f"== Seedance 白模自查：{os.path.basename(st['file']) or '（未保存）'}"
          f"（{'粗' if st['grain'] == 'coarse' else '细'}颗粒度）==")
    print(f"设置：{st['res'][0]}×{st['res'][1]}，{st['fps']:g} fps，第 {st['frames'][0]}–{st['frames'][1]} 帧"
          f"（{st['duration_s']:.2f} s{'，分段' if st.get('segment') else ''}），{st['engine']}")
    dof = st.get("dof") or {}
    if dof:
        parts = []
        for name, d in dof.items():
            fo = d["focus"]
            fo = "移焦" if fo == "keyed" else (f"{fo:g} m" if isinstance(fo, (int, float)) else fo)
            parts.append(f"{name} f/{d['fstop']:g} → {fo}")
        off = "（Workbench 景深总开关关着，不生效）" if st.get("dof_switch") is False else ""
        print("景深：" + "、".join(parts) + off)
    else:
        print("景深：无")
    for s in rep["shots"]:
        print(f"镜{s['shot']} 第 {s['frames'][0]}–{s['frames'][1]} 帧（{s['seconds'][0]:.2f}–{s['seconds'][1]:.2f} s）"
              f" 相机 {'/'.join(s['cameras']) or '无'}")
        for c in s["subjects"]:
            how = "像素" if c.get("method") == "pixel" else "包围盒"
            print(f"   {c['name']}  画高 {c['height_ratio_max'] * 100:.1f}%（{how}）"
                  f"  位移 {c['move_body']:.2f} 身高  {c['verdict']}")
    print(f"结论：{rep['verdict']}（不通过 {len(rep['fail'])} 条，警告 {len(rep['warn'])} 条，"
          f"备注 {len(rep['note'])} 条）")
    for tag, items in (("不通过", rep["fail"]), ("警告", rep["warn"]), ("备注", rep["note"])):
        if items:
            print(tag + "：")
            for it in items:
                print(f"   {it['item']} {it['detail']}")
    print("人工：")
    for m in rep["manual"]:
        print("   " + m)
    if rep.get("json"):
        print("JSON：" + rep["json"])


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="check_export.py", description="Seedance 白模导出前自查")
    ap.add_argument("--out", help="JSON 报告路径")
    ap.add_argument("--grain", choices=("coarse", "fine"), default="coarse", help="粗 / 细颗粒度，默认 coarse")
    ap.add_argument("--chr", default="", help="额外当作角色的物体名，逗号分隔")
    ap.add_argument("--prefix", default="CHR_", help="角色名前缀，默认 CHR_")
    ap.add_argument("--range", nargs=2, type=int, metavar=("首帧", "末帧"),
                    help="分段自查：只查这段帧，查完恢复场景帧范围")
    ap.add_argument("--vivid", action="store_true", help="用户指定鲜明色：③ 角色超标只报警告")
    ap.add_argument("--no-pixel", action="store_true", help="画高按包围盒投影算，不做掩码渲染")
    a = ap.parse_args(argv)
    run(out_json=a.out, grain=a.grain, chr_names=[x for x in a.chr.split(",") if x], prefix=a.prefix,
        vivid=a.vivid, frame_range=a.range, pixel=not a.no_pixel)


if __name__ == "__main__":
    main()

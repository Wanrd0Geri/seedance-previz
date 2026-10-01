# 蛟龙绕柱白模的运镜脚本副本（2026-10-01，7 秒版 = 白模 261001-11 用的那份；原件在 Desktop\白模_蛟龙绕柱\jiao_rig.py）。
# 看法：V10_KEYS 节拍表 + cam_state_v10 + _catmull 是贴身追拍的做法（camera-moves.md 第 9 节）；
# speed / s_head / arc / path_pt 是龙头沿螺旋路径的位置；CAM_SCALE 是总幅度旋钮。文件头的「v3」是当天没改的旧注释。

# 蛟龙绕柱白模 v3：龙身游动 + 黑神话式运镜 + 结尾冲入云霄
# 路线：前段贴柱螺旋（1.5 秒一圈，带 S 形游动）；第 70 帧龙头处脱离螺旋，拐成近乎垂直往上，冲进漩涡云层。
import math
from mathutils import Vector

R_PATH = 34.0
LOOP_S = 1.5
PITCH = 70.0
ALPHA = math.atan(PITCH / (2 * math.pi * R_PATH))
S_H0 = 130.0
TH_HEAD0 = math.radians(-90.0)
TH_START = TH_HEAD0 + (S_H0 * math.cos(ALPHA)) / R_PATH
Z_START = -S_H0 * math.sin(ALPHA)
V0 = (2 * math.pi * R_PATH / LOOP_S) / math.cos(ALPHA)   # 平均速度，约 150 m/s
WAVE_L, WAVE_R, WAVE_Z = 75.0, 2.5, 3.0                  # 龙身 S 形：波长、径向摆幅、上下摆幅
F_BREAK = 136                                            # 龙头在这一帧离开螺旋（7 秒版）
F_CLOUD = 158                                            # 龙头在这一帧撞进云底（7 秒版，CLOUD_Z 由它反推）
TURN_L = 45.0                                            # 从螺旋拐到往上冲用多长
CLOUD_Z = 305.0                                          # 云层底面高度
STEP = 1.5                                               # 路线曲线的点距（参数 s）
S_MAX = 1800.0


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def speed(f):
    """每秒米数：平均 V0，一拱一拱地快慢起伏，第 36–48 帧一次冲刺，第 68 帧起越冲越快。"""
    base = 1.0 + 0.22 * math.sin(2 * math.pi * (f - 1) / 16.0) + 0.45 * math.exp(-((f - 72.0) / 8.0) ** 2)
    return V0 * base * (1.0 + 0.8 * smooth((f - 130.0) / 16.0))


_S = {}


def s_head(f):
    """龙颈（本地 x=0）的路线参数，按速度逐帧积分。"""
    f = float(f)
    if not _S:
        s = S_H0
        _S[1.0] = s
        for i in range(2, 200):
            s += speed(i - 0.5) / 24.0
            _S[float(i)] = s
    fi = math.floor(f)
    a = _S.get(float(max(1, fi)), S_H0)
    b = _S.get(float(max(1, fi + 1)), a)
    return a + (b - a) * (f - fi)


def theta(s):
    return TH_START - s * math.cos(ALPHA) / R_PATH


def _helix(s, r_off=0.0, h_off=0.0, wave=True):
    th = theta(s)
    k = smooth((S_B - s) / 30.0) if wave else 0.0          # 拐弯前 30 米把游动收掉
    w = 2 * math.pi * s / WAVE_L
    r = R_PATH + r_off + WAVE_R * math.sin(w) * k
    z = Z_START + s * math.sin(ALPHA) + h_off + WAVE_Z * math.sin(w + 1.3) * k
    return Vector((r * math.cos(th), r * math.sin(th), z))


S_B = s_head(F_BREAK)
_ASC = []   # 拐弯往上那段：每 0.5 米一个点


def _build_ascent():
    p = _helix(S_B)
    t0 = (_helix(S_B + 0.5) - _helix(S_B - 0.5)).normalized()
    out = Vector((p.x, p.y, 0.0)).normalized()
    t1 = (Vector((0.0, 0.0, 1.0)) + out * 0.45 + Vector((t0.x, t0.y, 0.0)) * 0.15).normalized()   # 往外甩开柱子再往上冲
    _ASC.append(p.copy())
    n = int((S_MAX - S_B) / 0.5) + 2
    for i in range(1, n):
        u = smooth(i * 0.5 / TURN_L)
        dvec = (t0 * (1 - u) + t1 * u).normalized()
        p = p + dvec * 0.5
        _ASC.append(p.copy())


def path_pt(s, r_off=0.0, h_off=0.0, wave=True):
    if s <= S_B:
        return _helix(s, r_off, h_off, wave)
    if not _ASC:
        _build_ascent()
    x = (s - S_B) / 0.5
    i = max(0, min(len(_ASC) - 2, int(math.floor(x))))
    q = _ASC[i] + (_ASC[i + 1] - _ASC[i]) * (x - i)
    if r_off or h_off:
        out = Vector((q.x, q.y, 0.0)).normalized()
        q = q + out * r_off + Vector((0, 0, h_off))
    return q


_ARC = []


def arc(s):
    """参数 s → 曲线上的实际弧长（曲线修改器按实际弧长摆龙身）。"""
    if not _ARC:
        acc, prev = 0.0, path_pt(0.0)
        _ARC.append(0.0)
        for i in range(1, int(S_MAX / STEP) + 1):
            p = path_pt(i * STEP)
            acc += (p - prev).length
            _ARC.append(acc)
            prev = p
    x = s / STEP
    i = max(0, min(len(_ARC) - 2, int(math.floor(x))))
    return _ARC[i] + (_ARC[i + 1] - _ARC[i]) * (x - i)


def frame_axes(s):
    s = min(s, S_B - 1.0)          # 只在螺旋段取镜头坐标系，往上冲那段不用
    p0, p1 = path_pt(s - 0.5), path_pt(s + 0.5)
    t = (p1 - p0).normalized()
    c = path_pt(s)
    out = Vector((c.x, c.y, 0.0)).normalized()
    side = (out - t * out.dot(t)).normalized()          # 外侧（离柱子）
    upv = t.cross(side).normalized()
    if upv.z < 0:
        upv = -upv
    return c, t, side, upv


# 运镜节拍：帧, 锚点离龙头的弧长 a（米，正数=在龙头后面）, 距离 d, 方位 az（0=正后方，90=外侧，180=正前方）,
# 仰角 el（正=在上方）, 侧倾 roll（度）, 瞄准点离龙头 aim（米，负=沿身体往后）, 滞后 lag（帧，瞄准龙头几帧前的位置）
KEYS = [
    (1,  28, 7.5,  85,  18, -18, -10, 0),   # 贴着龙身，龙身从镜头前扫过
    (8,  52, 7.5,  85,  18,  -8, -30, 0),   # 镜头慢，龙身一路刷过去
    (20, 10, 34,  105,   8,  14,   0, 5),   # 猛地拉开，侧面看它横穿画面，镜头慢半拍
    (34, 14, 18,  160, -22,  -6,   0, 3),   # 绕到它身后下方，看它扭身往上盘
    (43, 34, 30,  175, -12,  -2,   0, 6),   # 龙冲刺甩开镜头
    (50, 12, 14,  120,   6,  18,   0, 0),   # 甩镜追上，撞石
    (64, 22, 7.5,  70,  30, -12, -12, 0),   # 从外上方冲回贴身，龙身从头顶掠过
    (72, 40, 7.5,  60,  28,  -6, -35, 0),
]
CAM_SCALE = 0.7     # 运镜幅度：1 = 第 4/5 版原样；0.7 = 削弱 30%（距离、方位往均值收，仰角、侧倾、瞄准偏移、滞后按比例缩）


def _scale_keys(keys, center_cols, zero_cols):
    """center_cols：往该列均值收；zero_cols：往 0 缩。第 0 列是帧号不动。"""
    if CAM_SCALE == 1.0:
        return keys
    cols = list(zip(*keys))
    means = {c: sum(cols[c]) / len(cols[c]) for c in center_cols}
    out = []
    for k in keys:
        k = list(k)
        for c in center_cols:
            k[c] = means[c] + (k[c] - means[c]) * CAM_SCALE
        for c in zero_cols:
            k[c] = k[c] * CAM_SCALE
        out.append(tuple(k))
    return out


F_WATCH = 72        # 从这帧起镜头减速留在下面，仰看它冲进云层
WATCH_BLEND = 10


def _chase(f):
    ks = _scale_keys(KEYS, (1, 2, 3), (4, 5, 6, 7))
    if f <= ks[0][0]:
        k = ks[0][1:]
    elif f >= ks[-1][0]:
        k = ks[-1][1:]
    else:
        for (fa, *A), (fb, *B) in zip(ks[:-1], ks[1:]):
            if fa <= f <= fb:
                u = smooth((f - fa) / (fb - fa))
                k = [x + (y - x) * u for x, y in zip(A, B)]
                break
    a, d, az, el, roll, aim, lag = k
    sh = s_head(f)
    anchor, t, side, upv = frame_axes(sh - a)
    azr, elr = math.radians(az), math.radians(el)
    horiz = -math.cos(azr) * t + math.sin(azr) * side
    cam = anchor + (horiz * math.cos(elr) + upv * math.sin(elr)) * d
    tgt = path_pt(s_head(f - lag) + aim)
    return cam, tgt, roll


# 结尾跟着龙冲进云层：帧, 镜头落后龙头的路程 a（米）, 离龙身的距离 d, 绕龙的方位 phi（度，0=外侧）, 侧倾 roll, 瞄准滞后 lag（帧）
ASC_KEYS = [
    (72, 40, 7.5,   0,  -6, 0),
    (78, 20, 11,   50,  12, 3),   # 追上来，边追边绕
    (83, 34, 15,   95,  18, 5),   # 龙再一冲，把镜头甩开
    (88, 14, 8,   140,  -8, 2),   # 猛追上去，一起撞进云底
    (96, 8,  7,   170, -14, 1),   # 在云里贴着它
]


def _interp(keys, f):
    if f <= keys[0][0]:
        return list(keys[0][1:])
    if f >= keys[-1][0]:
        return list(keys[-1][1:])
    for (fa, *A), (fb, *B) in zip(keys[:-1], keys[1:]):
        if fa <= f <= fb:
            u = smooth((f - fa) / (fb - fa))
            return [x + (y - x) * u for x, y in zip(A, B)]


def _ascend(f):
    """跟着龙往上冲：落后的路程和距离一松一紧，镜头边追边绕着龙转，瞄准慢半拍。"""
    a, d, phi, roll, lag = _interp(_scale_keys(ASC_KEYS, (1, 2), (3, 4, 5)), f)
    s = s_head(f) - a
    p0, p1 = path_pt(s - 0.5), path_pt(s + 0.5)
    t = (p1 - p0).normalized()
    c = path_pt(s)
    out = Vector((c.x, c.y, 0.0)).normalized()
    u1 = (out - t * out.dot(t)).normalized()
    u2 = t.cross(u1).normalized()
    ph = math.radians(phi)
    cam = c + (u1 * math.cos(ph) + u2 * math.sin(ph)) * d
    tgt = path_pt(s_head(f - lag) + 6.0)
    return cam, tgt, roll


# 中段全景：镜头猛地拉远到看得见整根龙卷和龙绕柱，再高速冲回来赶上撞石
WIDE = dict(out0=10, out1=26, in0=34, in1=47, R=100.0, z_cam=-40.0, z_aim=20.0, drift_dps=-15.0, roll=8.0)   # 第 9 版实际值；全景段龙头标记换成粗 2.2 倍、长 1.4 倍的大标记（DRG_headmark_big，第 16–21 帧渐显、36–41 帧渐隐）
_W0 = {}


def wide_weight(f):
    w = WIDE
    if f <= w["out0"] or f >= w["in1"]:
        return 0.0
    if f < w["out1"]:
        return smooth((f - w["out0"]) / (w["out1"] - w["out0"]))
    if f <= w["in0"]:
        return 1.0
    return 1.0 - smooth((f - w["in0"]) / (w["in1"] - w["in0"]))


def wide_cam(f):
    """全景机位：在拉远开始那一刻镜头所在的方位上，退到离龙卷轴线 R 米，跟着龙的高度升，方位慢慢漂；看龙卷轴线上龙的高度。"""
    if "th0" not in _W0:
        c0, _, _ = cam_state(WIDE["out0"])
        _W0["th0"] = math.atan2(c0.y, c0.x)
    th = _W0["th0"] + math.radians(WIDE["drift_dps"]) * (f - WIDE["out0"]) / 24.0
    hz = path_pt(s_head(f)).z
    cam = Vector((WIDE["R"] * math.cos(th), WIDE["R"] * math.sin(th), hz + WIDE["z_cam"]))
    tgt = Vector((0.0, 0.0, hz + WIDE["z_aim"]))
    return cam, tgt, WIDE["roll"]


def cam_state(f):
    if f <= F_WATCH:
        c, t, r = _chase(f)
    else:
        u = smooth((f - F_WATCH) / 6.0)
        c0, t0, r0 = _chase(min(f, F_WATCH + 3))
        c1, t1, r1 = _ascend(f)
        c, t, r = c0.lerp(c1, u), t0.lerp(t1, u), r0 + (r1 - r0) * u
    return c, t, math.radians(r)


# ===== v10：以龙头为中心的相对机位（更多特写与剪影，中全景不拉太远）=====
# 帧, 离龙头距离 dist（米）, 方位 az（0=正后方，90=外侧，180=正前方）, 仰角 el（正=在上方）, 侧倾 roll（度）, 瞄准点沿路线偏移 aim（米，负=龙头偏向前方画边）
V10_KEYS = [   # 7 秒版（168 帧）：特效重的拍给足时间，转场保持快
    (1,   18,  25, -15, -10,  0),   # 开场贴在身后，龙身扫过、背刺电弧（文字）
    (12,  16,  50,  -8,  -8, -2),
    (20,  14,  95,   0,   4, -3),   # 龙头侧脸特写
    (32,  14, 102,   2,   6, -3),   # 侧脸特写停留，身后闪电 → 剪影
    (40,  26, 112,   8,   8,  0),
    (48,  50, 120,  15,  10,  0),   # 中全景：外侧偏前，龙卷风在画面一侧
    (66,  54, 108,  12,   8,  0),   # 中全景停留：四道细闪电、一道贴柱壁往下爬
    (76,  18,  55,   8,  -6,  0),   # 冲回去
    (82,  14,  40,   6, -10,  0),   # 撞石特写：闪电劈石、链式电弧
    (92,  14,  70,   4,  -8,  0),
    (100, 14, 130,   0,  -4,  2),   # 斜前方正脸特写
    (116, 15, 140,   2,  -2,  2),   # 正脸停留：角尖冷光、长须电弧、撞小石
    (124, 14, 160, -35,   6,  0),   # 落到它下方
    (130, 13,  90, -70,  10,  0),   # 从头顶飞过 → 剪影、肚皮电弧
    (136, 14,  20, -40,   4,  0),
    (142, 18,  30, -35,  -6,  0),   # 往上冲，在它下方追
    (152, 28,  40, -20, -10,  0),   # 被甩开，闪电齐劈、一道劈在背上 → 逆光剪影
    (160, 16,  20, -10,  -4,  0),   # 追上，一起冲进云层
    (169, 14,  10,   0,   0,  0),
]


def _catmull(keys, f):
    """各通道按 Catmull-Rom 插值：过节拍点速度连续，不会每个点先停一下。"""
    fs = [k[0] for k in keys]
    if f <= fs[0]:
        return list(keys[0][1:])
    if f >= fs[-1]:
        return list(keys[-1][1:])
    i = max(j for j in range(len(fs) - 1) if fs[j] <= f)
    p0 = keys[max(i - 1, 0)]; p1 = keys[i]; p2 = keys[i + 1]; p3 = keys[min(i + 2, len(keys) - 1)]
    u = (f - p1[0]) / (p2[0] - p1[0])
    out = []
    for c in range(1, len(p1)):
        # 非均匀节拍：切线按相邻段时长归一
        m1 = (p2[c] - p0[c]) / max(1e-6, (p2[0] - p0[0])) * (p2[0] - p1[0])
        m2 = (p3[c] - p1[c]) / max(1e-6, (p3[0] - p1[0])) * (p2[0] - p1[0])
        u2, u3 = u * u, u * u * u
        out.append((2 * u3 - 3 * u2 + 1) * p1[c] + (u3 - 2 * u2 + u) * m1 + (-2 * u3 + 3 * u2) * p2[c] + (u3 - u2) * m2)
    return out


_UPSIGN = {}


def local_axes(s):
    """龙在路线参数 s 处的局部坐标：t 前进方向、side 外侧（离柱子）、up 与两者垂直；up 的朝向在螺旋段定一次，拐弯往上后保持连续。"""
    p0, p1 = path_pt(s - 0.5), path_pt(s + 0.5)
    t = (p1 - p0).normalized()
    c = path_pt(s)
    out = Vector((c.x, c.y, 0.0)).normalized()
    side = (out - t * out.dot(t)).normalized()
    up = t.cross(side).normalized()
    if "sgn" not in _UPSIGN:
        _UPSIGN["sgn"] = 1.0 if up.z >= 0 else -1.0
    return c, t, side, up * _UPSIGN["sgn"]


def cam_state_v10(f):
    dist, az, el, roll, aim = _catmull(V10_KEYS, f)
    sh = s_head(f) + 4.0
    head, t, side, up = local_axes(sh)
    a, e = math.radians(az), math.radians(el)
    cam = head + (-math.cos(a) * math.cos(e) * t + math.sin(a) * math.cos(e) * side + math.sin(e) * up) * dist
    tgt = path_pt(sh + aim)
    return cam, tgt, math.radians(roll)

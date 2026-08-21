# open_mv2.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 16     (bumped every time the code changes - check this first)
#  Successor to chili_stopper_factory.py.
# ----------------------------------------------------------------------------------
#  v16 TIGHT ROI & ZERO-SHADOW GATES (FIXES FALSE STEM / SHADOW MERGE).
#      In v15, CHANNEL_ROI reached y=210 (onto the dark floral mat past the stopper)
#      and BLOB_MARGIN was 14. This caused the shadow and dark table below the
#      stopper to merge into the chilli blob, making the apex look fat/heavy and
#      forcing a false STEM decision.
#      Fixed by:
#      1. CHANNEL_ROI = (200, 50, 28, 138): Perfectly tight inside the white metal
#         chute, stopping exactly at the stopper bar (no floral table bleed).
#      2. BLOB_MARGIN = 2: Tight blob boundary, prevents merging with shadows.
#      3. DARK_L_MAX = 50: Ignores light shadows on aluminum.
#      4. Symmetric Mass Centroid + Body Width Profile.
# ----------------------------------------------------------------------------------
#  v15 FIXED APEX-ONLY BIAS VIA MASS CENTROID SHIFT & BALANCED ENSEMBLE.
# ----------------------------------------------------------------------------------
#  v14 Back to a FIXED narrow box: CHANNEL_ROI = (186, 50, 36, 160).
# ----------------------------------------------------------------------------------
#  v13 THE CAMERA NOW FINDS THE CHANNEL BY ITSELF (AUTO_CHANNEL).
# ----------------------------------------------------------------------------------
#  v12 CHANNEL_ROI moved to the MIDDLE of the picture.
# ----------------------------------------------------------------------------------
#  v11 FIXED A BIAS THAT PUSHED NEARLY EVERY ANSWER TO "STEM".
# ----------------------------------------------------------------------------------
#  v10 MANUAL / AUTOMATIC threshold switch - see MANUAL_L in the config.
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED


# ------------------------------- CONFIG -------------------------------
CALIBRATE     = False    # True = tuning mode: pins stay OFF, numbers printed
DEBUG         = True     # True = show detection boxes

# White chute ROI: (x, y, width, height)
# Must sit strictly inside the bright metal chute and stop AT the stopper bar.
# Must NOT include the dark table/mat outside the chute!
CHANNEL_ROI   = (200, 50, 28, 138)
#                x    y   w    h

AUTO_CHANNEL  = False
CH_MIN_PIX    = 600
CH_INSET      = 2

# Which edge of that box the stopper is on.
STOPPER_SIDE  = "bottom"

# Brightness threshold (0 = black, 100 = white)
MANUAL_L      = None     # None = AUTO; set to fixed int (e.g. 45) for production

DARK_K        = 0.50     # Dynamic sensitivity
DARK_L_MIN    = 8
DARK_L_MAX    = 50       # Caps threshold so shadows on aluminum (L > 50) are ignored
MIN_CHILI_STD = 6.0      # Empty bare metal channel has uniform brightness (std < 6)

# ---- shape filters (tuned for all sizes of dried chillies) ----
MIN_AREA      = 120      # Ignore tiny noise specks
MAX_AREA      = 35000
MIN_ASPECT    = 1.1
MAX_ASPECT    = 16.0
MAX_WIDTH_PX  = 65
MAX_TILT_DEG  = 85
EXTENT_MIN    = 0.10
MIN_LEN       = 14
MAX_LEN       = 320
BLOB_MARGIN   = 2        # Tight boundary: never merge with ambient shadows!

# ---- measuring boxes on both ends ----
END_INSET     = 0.22     # Sample at 22% along the body
END_BOX_MIN   = 8
END_BOX_MAX   = 36
MIN_BOX_OBJ   = 8
MIN_BOX_AREA  = 25

# ---- stalk check ----
STALK_REACH   = 18
STALK_BOX     = 20
STALK_MIN_DENS = 0.04
STALK_RATIO   = 1.5

# ---- decision weights ----
W_CENTROID    = 1.5      # Geometric mass center shift (primary)
W_WIDTH       = 1.2      # Body density / thickness difference
W_RED         = 0.6      # Pale stem end vs rich red apex
W_STALK       = 0.4      # Pale stalk extending past end
A_FULL        = 12.0
MIN_SCORE     = 0.05
DISAGREE_MULT = 0.6

# ---- rules ----
STOPPER_GAP_MAX_PX = 9999
DECIDE_MIN     = 0.15
STABLE_N       = 4               # 4-frame confirmation (~100ms)
CLEAR_FRAMES   = 5               # Empty frames before next chili
MAX_WAIT_MS    = 1500
VOTE_HISTORY_MAX = 7             # Smoothing window

# ---- outputs ----
OUTPUT_MODE    = "level"         # "level" = hold until chili leaves; "pulse"
PULSE_MS       = 300
ROTATE_ON      = "STEM"
BLINK_MS       = 250

USE_TRIGGER    = False
TRIGGER_PIN    = 'P3'
TRIGGER_ACTIVE_HIGH = True

# ------------------------------- OUTPUTS ------------------------------
stem_pin = Pin('P0', Pin.OUT_PP);  stem_pin.value(0)   # STEM arrived first (P0)
pod_pin  = Pin('P1', Pin.OUT_PP);  pod_pin.value(0)    # APEX arrived first (P1)
rot_pin  = Pin('P2', Pin.OUT_PP);  rot_pin.value(0)    # ROTATE 180 command (P2)
led_blue, led_green = LED(3), LED(2)

trig = None
if USE_TRIGGER:
    trig = Pin(TRIGGER_PIN, Pin.IN,
               Pin.PULL_DOWN if TRIGGER_ACTIVE_HIGH else Pin.PULL_UP)

def triggered():
    if not USE_TRIGGER:
        return True
    v = trig.value()
    return (v == 1) if TRIGGER_ACTIVE_HIGH else (v == 0)

def set_outputs(answer):
    """Drive the output pins (P0, P1, P2)."""
    stem_pin.value(1 if answer == "STEM" else 0)
    pod_pin.value(1 if answer == "POD" else 0)
    rot_pin.value(1 if (answer is not None and answer == ROTATE_ON) else 0)

def service_leds(answer):
    """Blue for STEM, green for APEX."""
    if CALIBRATE:
        on = (time.ticks_ms() // BLINK_MS) % 2 == 0
        led_blue.on()  if (answer == "STEM" and on) else led_blue.off()
        led_green.on() if (answer == "POD" and on)  else led_green.off()
    else:
        led_blue.on()  if answer == "STEM" else led_blue.off()
        led_green.on() if answer == "POD"  else led_green.off()

# ------------------------------- SENSOR -------------------------------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)          # 320x240
sensor.skip_frames(time=2000)
sensor.set_auto_gain(False)                # Lock exposure & colour
sensor.set_auto_whitebal(False)
clock = time.clock()

# ------------------------------- HELPERS ------------------------------
def _get(obj, name, *args):
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def _stat(st, name, default=0.0):
    try:
        return float(_get(st, name))
    except Exception:
        return default

def clamp_roi(x, y, w, h):
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(320, int(x + w)), min(240, int(y + h))
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))

def count_px(img, roi, thrs):
    if roi[2] < 2 or roi[3] < 2:
        return 0
    try:
        bs = img.find_blobs(thrs, roi=roi, pixels_threshold=4,
                            area_threshold=4, merge=True)
        return sum(_get(x, "pixels") for x in bs)
    except Exception:
        return 0

def density(img, roi, thrs):
    area = roi[2] * roi[3]
    if area < MIN_BOX_AREA:
        return None
    return count_px(img, roi, thrs) / float(area)

def region_redness(img, roi, obj_thrs):
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(thresholds=obj_thrs, roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        pass
    try:
        st = img.get_statistics(roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        return None

def object_threshold(img):
    if MANUAL_L is not None:
        lim = int(min(max(MANUAL_L, 0), 100))
        thrs = [(0, lim, -128, 127, -128, 127)]
        if count_px(img, CHANNEL_ROI, thrs) < MIN_AREA:
            return None, lim
        return thrs, lim

    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0

    if l_std < MIN_CHILI_STD:
        return None, 0

    lim = l_mean - DARK_K * l_std
    lim = min(max(lim, DARK_L_MIN), DARK_L_MAX)
    return [(0, int(lim), -128, 127, -128, 127)], int(lim)

def _dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

def axis_ends(b):
    try:
        c0, c1, c2, c3 = _get(b, "min_corners")
        e01, e12 = _dist(c0, c1), _dist(c1, c2)
        if e01 >= e12:
            return _mid(c1, c2), _mid(c3, c0), e12
        return _mid(c0, c1), _mid(c2, c3), e01
    except Exception:
        pass
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    if bw >= bh:
        return (bx, by + bh / 2.0), (bx + bw, by + bh / 2.0), bh
    return (bx + bw / 2.0, by), (bx + bw / 2.0, by + bh), bw

def tilt_deg(E0, E1):
    dx, dy = abs(E1[0] - E0[0]), abs(E1[1] - E0[1])
    if STOPPER_SIDE in ("top", "bottom"):
        return math.degrees(math.atan2(dx, dy + 0.001))
    return math.degrees(math.atan2(dy, dx + 0.001))

def pick_stopper_end(E0, E1):
    x, y, w, h = CHANNEL_ROI
    if STOPPER_SIDE == "left":
        near, far = (E0, E1) if E0[0] <= E1[0] else (E1, E0)
        return near, far, near[0] - x
    if STOPPER_SIDE == "right":
        near, far = (E0, E1) if E0[0] >= E1[0] else (E1, E0)
        return near, far, (x + w) - near[0]
    if STOPPER_SIDE == "top":
        near, far = (E0, E1) if E0[1] <= E1[1] else (E1, E0)
        return near, far, near[1] - y
    near, far = (E0, E1) if E0[1] >= E1[1] else (E1, E0)
    return near, far, (y + h) - near[1]

def shape_ok(b):
    bw, bh, px = _get(b, "w"), _get(b, "h"), _get(b, "pixels")
    if px > MAX_AREA:
        return False
    length, width = max(bw, bh), max(1, min(bw, bh))
    if width > MAX_WIDTH_PX:
        return False
    if not (MIN_ASPECT <= length / width <= MAX_ASPECT):
        return False
    if not (MIN_LEN <= length <= MAX_LEN):
        return False
    if px / float(bw * bh) < EXTENT_MIN:
        return False
    return True

scan = {"raw": 0, "shape": 0, "colour": 0, "tilt": 0, "best_tilt": -1}

def find_chili(img, obj_thrs):
    if obj_thrs is None:
        scan["raw"] = scan["shape"] = scan["colour"] = scan["tilt"] = 0
        scan["best_tilt"] = -1
        return None

    kw = {"roi": CHANNEL_ROI, "pixels_threshold": MIN_AREA,
          "area_threshold": MIN_AREA, "merge": True, "margin": BLOB_MARGIN}
    try:
        blobs = img.find_blobs(obj_thrs, **kw)
    except TypeError:
        kw.pop("margin")
        blobs = img.find_blobs(obj_thrs, **kw)

    scan["raw"] = len(blobs)
    scan["shape"] = scan["colour"] = scan["tilt"] = 0
    scan["best_tilt"] = -1

    best, best_cost = None, None
    for b in blobs:
        if not shape_ok(b):
            continue
        scan["shape"] += 1

        rect = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))
        red = region_redness(img, rect, obj_thrs)
        if red is None:
            red = 0.0
        scan["colour"] += 1

        E0, E1, width = axis_ends(b)
        tilt = tilt_deg(E0, E1)
        if scan["best_tilt"] < 0 or tilt < scan["best_tilt"]:
            scan["best_tilt"] = int(tilt)
        if tilt > MAX_TILT_DEG:
            continue
        scan["tilt"] += 1

        E_stop, E_far, dist = pick_stopper_end(E0, E1)
        cost = -red + 0.25 * tilt + 0.05 * max(0, dist)
        if best_cost is None or cost < best_cost:
            centroid = (_get(b, "cx"), _get(b, "cy"))
            best = (E_stop, E_far, width, dist, rect, tilt, red, centroid)
            best_cost = cost
    return best

def clip_to_channel(roi):
    cx, cy, cw, ch = CHANNEL_ROI
    x0 = max(roi[0], cx)
    y0 = max(roi[1], cy)
    x1 = min(roi[0] + roi[2], cx + cw)
    y1 = min(roi[1] + roi[3], cy + ch)
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))

def end_boxes(E_stop, E_far, width):
    side = min(max(width * 1.2, END_BOX_MIN), END_BOX_MAX)
    dx, dy = E_far[0] - E_stop[0], E_far[1] - E_stop[1]
    near = (E_stop[0] + END_INSET * dx, E_stop[1] + END_INSET * dy)
    far = (E_far[0] - END_INSET * dx, E_far[1] - END_INSET * dy)
    return (clip_to_channel(clamp_roi(near[0] - side/2.0, near[1] - side/2.0,
                                     side, side)),
            clip_to_channel(clamp_roi(far[0] - side/2.0, far[1] - side/2.0,
                                      side, side)))

def check_stalk(img, E_stop, E_far, lim):
    dx = E_far[0] - E_stop[0]
    dy = E_far[1] - E_stop[1]
    L = math.sqrt(dx*dx + dy*dy) or 1.0
    ux, uy = dx / L, dy / L
    half = STALK_BOX // 2

    nx = int(E_stop[0] - STALK_REACH * ux)
    ny = int(E_stop[1] - STALK_REACH * uy)
    roi_near = clip_to_channel(clamp_roi(nx - half, ny - half,
                                         STALK_BOX, STALK_BOX))

    fx = int(E_far[0] + STALK_REACH * ux)
    fy = int(E_far[1] + STALK_REACH * uy)
    roi_far = clip_to_channel(clamp_roi(fx - half, fy - half,
                                        STALK_BOX, STALK_BOX))

    thrs = [(int(lim), min(92, int(lim) + 16), -20, 20, -10, 40)]
    d_near = density(img, roi_near, thrs)
    d_far = density(img, roi_far, thrs)
    if d_near is None or d_far is None:
        return 0.0

    if d_near >= STALK_MIN_DENS and d_near > d_far * STALK_RATIO:
        return 1.0
    if d_far >= STALK_MIN_DENS and d_far > d_near * STALK_RATIO:
        return -1.0
    return 0.0

def look(img, obj_thrs, lim):
    out = {"reason": "empty", "score": 0.0, "a_near": None, "a_far": None,
           "spread": 0.0, "boxes": [], "rect": None, "E_stop": None,
           "E_far": None, "centroid": None, "dist": -1, "tilt": -1, "red": 0.0,
           "d_near": 0.0, "d_far": 0.0, "s_centroid": 0.0, "s_width": 0.0,
           "s_red": 0.0, "s_stalk": 0.0, "agree": True}

    found = find_chili(img, obj_thrs)
    if found is None:
        return out
    E_stop, E_far, width, dist, rect, tilt, red, centroid = found
    out["E_stop"], out["E_far"] = E_stop, E_far
    out["dist"], out["rect"], out["tilt"], out["red"] = dist, rect, tilt, red
    out["centroid"] = centroid

    boxes = end_boxes(E_stop, E_far, width)
    out["boxes"] = list(boxes)

    if dist > STOPPER_GAP_MAX_PX:
        out["reason"] = "not_at_stopper"
        return out

    # 1. CENTROID MASS SHIFT (Geometric clue - immune to glare/color)
    c_mid = ((E_stop[0] + E_far[0]) * 0.5, (E_stop[1] + E_far[1]) * 0.5)
    dx = E_far[0] - E_stop[0]
    dy = E_far[1] - E_stop[1]
    L = math.sqrt(dx*dx + dy*dy) or 1.0
    ux, uy = dx / L, dy / L
    proj = (centroid[0] - c_mid[0]) * ux + (centroid[1] - c_mid[1]) * uy
    # If shifted toward E_stop: proj < 0 -> s_centroid > 0 (STEM)
    # If shifted toward E_far: proj > 0 -> s_centroid < 0 (APEX)
    s_centroid = min(1.0, max(-1.0, -proj / (L * 0.15)))
    out["s_centroid"] = s_centroid

    # 2. THICKNESS by density in shoulder vs tapered end
    d_near = density(img, boxes[0], obj_thrs)
    d_far = density(img, boxes[1], obj_thrs)
    if d_near is None or d_far is None or (d_near + d_far) <= 0:
        out["reason"] = "no_read"
        return out
    out["d_near"], out["d_far"] = d_near, d_far
    s_width = (d_near - d_far) / (d_near + d_far)

    # 3. REDNESS: the stem end is the paler end
    a_near = region_redness(img, boxes[0], obj_thrs)
    a_far = region_redness(img, boxes[1], obj_thrs)
    if a_near is not None and a_far is not None:
        out["a_near"], out["a_far"] = a_near, a_far
        spread = a_far - a_near
        out["spread"] = spread
        s_red = min(1.0, max(-1.0, spread / A_FULL))
        rw = W_RED
    else:
        s_red, rw = 0.0, 0.0

    # 4. STALK sticking out past one end
    s_stalk = check_stalk(img, E_stop, E_far, lim)
    out["s_stalk"] = s_stalk

    # Balanced ensemble voting
    tot_w = W_CENTROID + W_WIDTH + rw
    weighted_sum = W_CENTROID * s_centroid + W_WIDTH * s_width + rw * s_red
    if s_stalk != 0.0:
        tot_w += W_STALK
        weighted_sum += W_STALK * s_stalk

    score = weighted_sum / tot_w

    if s_centroid != 0.0 and s_width != 0.0 and (s_centroid > 0) != (s_width > 0):
        score *= DISAGREE_MULT
        out["agree"] = False

    out["s_width"], out["s_red"] = s_width, s_red
    out["score"] = score

    if abs(score) < MIN_SCORE:
        out["reason"] = "no_contrast"
        return out
    out["reason"] = "ok"
    return out

# Labels
NAME = {"STEM": "STEM", "POD": "APEX"}
REASON_TEXT = {"empty": "EMPTY", "not_at_stopper": "NOT AT STOPPER",
               "no_read": "CANNOT SEE CHILI CLEARLY",
               "no_contrast": "CANNOT TELL - ENDS LOOK THE SAME"}

FONT_5x7 = {
    'A': (0x0e, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11),
    'B': (0x1e, 0x11, 0x11, 0x1e, 0x11, 0x11, 0x1e),
    'C': (0x0e, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0e),
    'D': (0x1e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1e),
    'E': (0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x1f),
    'F': (0x1f, 0x10, 0x10, 0x1e, 0x10, 0x10, 0x10),
    'G': (0x0e, 0x11, 0x10, 0x13, 0x11, 0x11, 0x0f),
    'H': (0x11, 0x11, 0x11, 0x1f, 0x11, 0x11, 0x11),
    'I': (0x0e, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0e),
    'J': (0x01, 0x01, 0x01, 0x01, 0x11, 0x11, 0x0e),
    'K': (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    'L': (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1f),
    'M': (0x11, 0x1b, 0x15, 0x15, 0x11, 0x11, 0x11),
    'N': (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    'O': (0x0e, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e),
    'P': (0x1e, 0x11, 0x11, 0x1e, 0x10, 0x10, 0x10),
    'Q': (0x0e, 0x11, 0x11, 0x11, 0x15, 0x09, 0x16),
    'R': (0x1e, 0x11, 0x11, 0x1e, 0x14, 0x12, 0x11),
    'S': (0x0f, 0x10, 0x10, 0x0e, 0x01, 0x01, 0x1e),
    'T': (0x1f, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    'U': (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0e),
    'V': (0x11, 0x11, 0x11, 0x11, 0x11, 0x0a, 0x04),
    'W': (0x11, 0x11, 0x11, 0x15, 0x15, 0x1b, 0x11),
    'X': (0x11, 0x11, 0x0a, 0x04, 0x0a, 0x11, 0x11),
    'Y': (0x11, 0x11, 0x0a, 0x04, 0x04, 0x04, 0x04),
    'Z': (0x1f, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1f),
    '0': (0x0e, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0e),
    '1': (0x04, 0x0c, 0x04, 0x04, 0x04, 0x04, 0x0e),
    '2': (0x0e, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1f),
    '3': (0x1e, 0x01, 0x01, 0x0e, 0x01, 0x01, 0x1e),
    '4': (0x02, 0x06, 0x0a, 0x12, 0x1f, 0x02, 0x02),
    '5': (0x1f, 0x10, 0x1e, 0x01, 0x01, 0x11, 0x0e),
    '6': (0x06, 0x08, 0x10, 0x1e, 0x11, 0x11, 0x0e),
    '7': (0x1f, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    '8': (0x0e, 0x11, 0x11, 0x0e, 0x11, 0x11, 0x0e),
    '9': (0x0e, 0x11, 0x11, 0x0f, 0x01, 0x02, 0x0c),
    '-': (0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00),
    '+': (0x00, 0x04, 0x04, 0x1f, 0x04, 0x04, 0x00),
    '>': (0x10, 0x08, 0x04, 0x02, 0x04, 0x08, 0x10),
    '<': (0x01, 0x02, 0x04, 0x08, 0x04, 0x02, 0x01),
    ':': (0x00, 0x0c, 0x0c, 0x00, 0x0c, 0x0c, 0x00),
    '.': (0x00, 0x00, 0x00, 0x00, 0x00, 0x0c, 0x0c),
    '|': (0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    '%': (0x19, 0x19, 0x02, 0x04, 0x08, 0x13, 0x13),
    '(': (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ')': (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}

def draw_str(img, x, y, text, color=(255, 255, 255), scale=2):
    s = str(text)
    ix, iy = int(x), int(y)
    sc = int(scale)

    try:
        img.draw_string((ix, iy), s, color=color, scale=sc)
        return
    except Exception:
        pass
    try:
        img.draw_string(ix, iy, s, color=color, scale=sc)
        return
    except Exception:
        pass

    char_w = 6 * sc
    cur_x = ix
    for ch in s:
        rows = FONT_5x7.get(ch.upper(), FONT_5x7[' '])
        for r_idx, row in enumerate(rows):
            for c_idx in range(5):
                if (row >> (4 - c_idx)) & 1:
                    px = cur_x + c_idx * sc
                    py = iy + r_idx * sc
                    if 0 <= px < 320 and 0 <= py < 240:
                        try:
                            img.draw_rectangle((px, py, sc, sc), color=color,
                                               fill=True)
                        except Exception:
                            try:
                                img.set_pixel((px, py), color)
                            except Exception:
                                pass
        cur_x += char_w

def draw_scene(img, r, label=None, col=(0, 255, 0), status=None,
               state_name="", total=0, fps=0.0, shown_score=None,
               shown_lim=0):
    if DEBUG:
        try:
            img.draw_rectangle(CHANNEL_ROI, color=(255, 0, 255), thickness=1)
        except Exception:
            pass
        for i, bx in enumerate(r["boxes"]):
            c = (0, 255, 255) if i == 0 else (150, 150, 150)
            try:
                img.draw_rectangle(bx, color=c, thickness=1)
            except Exception:
                pass

    if r["rect"]:
        try:
            img.draw_rectangle(r["rect"], color=(0, 255, 0), thickness=2)
        except Exception:
            pass

    if r.get("centroid"):
        cx, cy = int(r["centroid"][0]), int(r["centroid"][1])
        try:
            img.draw_circle(cx, cy, 3, color=(255, 255, 0), thickness=2)
        except Exception:
            try:
                img.draw_rectangle((cx-2, cy-2, 4, 4), color=(255, 255, 0), fill=True)
            except Exception:
                pass

    if r["E_stop"] and r["E_far"] and r["reason"] == "ok":
        sx, sy = int(r["E_stop"][0]), int(r["E_stop"][1])
        fx, fy = int(r["E_far"][0]), int(r["E_far"][1])
        arr_c = (0, 220, 255) if r["score"] > 0 else (0, 255, 100)
        try:
            img.draw_line((fx, fy, sx, sy), color=arr_c, thickness=3)
        except Exception:
            try:
                img.draw_line(fx, fy, sx, sy, color=arr_c, thickness=3)
            except Exception:
                pass
        dx, dy = sx - fx, sy - fy
        L = math.sqrt(dx*dx + dy*dy) or 1.0
        ux, uy = dx / L, dy / L
        px, py = -uy, ux
        for s in (1, -1):
            hx = int(sx - 14*ux + s*8*px)
            hy = int(sy - 14*uy + s*8*py)
            try:
                img.draw_line((hx, hy, sx, sy), color=arr_c, thickness=3)
            except Exception:
                try:
                    img.draw_line(hx, hy, sx, sy, color=arr_c, thickness=3)
                except Exception:
                    pass

    text_to_show = label if label else (status if status else state_name)
    text_color = col if label else ((255, 255, 0) if status else (200, 200, 200))

    try:
        img.draw_rectangle((6, 6, 260, 50), color=(0, 0, 0), fill=True)
        img.draw_rectangle((6, 6, 260, 50), color=text_color, thickness=2)
    except Exception:
        pass

    draw_str(img, 12, 10, text_to_show, color=text_color, scale=2)

    mode = "SET" if MANUAL_L is not None else "AUTO"
    tail = "L<=%d %s | %d FPS" % (shown_lim, mode, int(fps))

    if shown_score is not None:
        draw_str(img, 12, 32, "SCORE %+.2f | %s" % (shown_score, tail),
                 color=(255, 255, 255), scale=1)
    elif r["reason"] == "ok":
        flag = "" if r["agree"] else " ?"
        draw_str(img, 12, 32, "SCORE %+.2f%s | %s" % (r["score"], flag, tail),
                 color=(255, 255, 255), scale=1)
    else:
        draw_str(img, 12, 32, "WAITING | %s" % tail,
                 color=(180, 180, 180), scale=1)

# ============================ STATE MACHINE ===========================
WAIT, CHECK, LOCKED, CLEARING = 0, 1, 2, 3
STATE_NAME = {WAIT: "WAITING", CHECK: "CHECKING", LOCKED: "DECIDED",
              CLEARING: "COOLDOWN"}
state = WAIT
t_state = time.ticks_ms()
hold_answer, hold_n = None, 0
final = None
final_score = 0.0
empty = 0
pulse_until = 0
total = 0

vote_history = []

def smooth_score(s):
    global vote_history
    if s is None:
        if len(vote_history) > 0:
            vote_history.pop(0)
        return None
    vote_history.append(s)
    if len(vote_history) > VOTE_HISTORY_MAX:
        vote_history.pop(0)
    return sum(vote_history) / float(len(vote_history))

def reset_votes():
    global vote_history
    vote_history = []

while True:
    clock.tick()
    now = time.ticks_ms()
    img = sensor.snapshot()

    obj_thrs, lim = object_threshold(img)
    r = look(img, obj_thrs, lim)
    present = (r["reason"] == "ok")
    if not triggered():
        present = False
    score = r["score"]

    avg = smooth_score(score if present else None)
    if avg is None:
        live = None
    else:
        live = "STEM" if avg > 0 else "POD"
        score = avg

    # ---------------------------- CALIBRATE ---------------------------
    if CALIBRATE:
        set_outputs(None)
        service_leds(live)
        if live:
            col = (0, 150, 255) if live == "STEM" else (0, 255, 0)
            lbl = "STOPPER: %s (%s)" % (NAME[live],
                                        "P0" if live == "STEM" else "P1")
            draw_scene(img, r, lbl, col, None, "CALIBRATE", total, clock.fps(),
                       shown_lim=lim)
        else:
            status = "STOPPER: %s" % REASON_TEXT.get(r["reason"], "EMPTY")
            draw_scene(img, r, None, (255, 255, 255), status, "CALIBRATE",
                       total, clock.fps(), shown_lim=lim)
        if r["reason"] == "empty":
            print("CALIB EMPTY  blobs=%d shape=%d colour=%d tilt=%d "
                  "best_tilt=%d L<=%d fps=%.0f"
                  % (scan["raw"], scan["shape"], scan["colour"], scan["tilt"],
                     scan["best_tilt"], lim, clock.fps()))
        else:
            print("CALIB %-24s score=%+.2f | cent %+.2f | dens %.3f vs %.3f (%+.2f) | "
                  "red %+.2f | stalk %+.0f%s | fps=%.0f"
                  % (REASON_TEXT.get(r["reason"], "OK"), score,
                     r["s_centroid"], r["d_near"], r["d_far"], r["s_width"],
                     r["s_red"], r["s_stalk"], "" if r["agree"] else " DISAGREE",
                     clock.fps()))
        continue

    # ------------------------------ WAIT ------------------------------
    if state == WAIT:
        set_outputs(None)
        hold_answer, hold_n = None, 0
        if present and live:
            state, t_state = CHECK, now

    # ------------------------------ CHECK -----------------------------
    elif state == CHECK:
        if not present:
            state, t_state = WAIT, now
        else:
            answer = live
            if abs(score) >= DECIDE_MIN:
                if answer == hold_answer:
                    hold_n += 1
                else:
                    hold_answer, hold_n = answer, 1
            elapsed = time.ticks_diff(now, t_state)
            if hold_n >= STABLE_N or (elapsed >= MAX_WAIT_MS and hold_answer):
                final = hold_answer
                final_score = score
                set_outputs(final)
                total += 1
                pulse_until = time.ticks_add(now, PULSE_MS)
                state, t_state = LOCKED, now
                print(">>> %s ARRIVED FIRST -> %s HIGH (3.3V)  ==> %s   "
                      "(score=%+.2f cent=%+.2f stalk=%+.0f%s)"
                      % (NAME[final], "P0" if final == "STEM" else "P1",
                         "ROTATE 180 (P2 HIGH)" if final == ROTATE_ON
                         else "NO ROTATE", score, r["s_centroid"], r["s_stalk"],
                         "" if r["agree"] else " DISAGREE"))

    # ----------------------------- LOCKED -----------------------------
    elif state == LOCKED:
        if OUTPUT_MODE == "pulse" and time.ticks_diff(now, pulse_until) >= 0:
            set_outputs(None)
        if r["reason"] == "empty":
            empty = 1
            state, t_state = CLEARING, now

    # ---------------------------- CLEARING ----------------------------
    elif state == CLEARING:
        if r["reason"] != "empty":
            empty = 0
            state = LOCKED
        else:
            empty += 1
            if empty >= CLEAR_FRAMES:
                set_outputs(None)
                final = None
                reset_votes()
                print("--- chili gone: ready for next ---")
                state, t_state = WAIT, now

    # ---------------------------- overlay -----------------------------
    sname = STATE_NAME.get(state, "")
    if state in (LOCKED, CLEARING) and final:
        col = (0, 150, 255) if final == "STEM" else (0, 255, 0)
        lbl = "STOPPER: %s (%s)" % (NAME[final],
                                    "P0" if final == "STEM" else "P1")
        draw_scene(img, r, lbl, col, None, sname, total, clock.fps(),
                   shown_score=final_score, shown_lim=lim)
        service_leds(final)
    elif state == CHECK:
        draw_scene(img, r, None, (255, 255, 0), "STOPPER: CHECKING...", sname,
                   total, clock.fps(), shown_lim=lim)
        service_leds(None)
    else:
        status = "STOPPER: %s" % REASON_TEXT.get(r["reason"], "WAITING")
        draw_scene(img, r, None, (255, 255, 255), status, sname,
                   total, clock.fps(), shown_lim=lim)
        service_leds(None)

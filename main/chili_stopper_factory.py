# chili_stopper_factory.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 6 (Direct Screen Overlay)
# ----------------------------------------------------------------------------------
#  v6  Fixed on-screen HUD text: Removed dark filled background boxes so text
#      renders cleanly directly on the live camera view.
#      Calibrated Channel ROI: (205, 90, 42, 120) with STOPPER_SIDE = "bottom".
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED

# ------------------------------- CONFIG -------------------------------
CALIBRATE     = False    # False = factory production mode (latch decision & hold power until next chili)
DEBUG         = True     # True = show detection boxes & tags

# White channel region (calibrated to the metal chute in the camera view)
CHANNEL_ROI   = (245, 50, 42, 145)
STOPPER_SIDE  = "bottom"         # Stopper is at the bottom of the screen

# ---- finding the chili (darkness & shape) ----
DARK_K        = 0.45             # Dynamic threshold sensitivity against white channel
DARK_L_MIN    = 10
DARK_L_MAX    = 75
MIN_CHILI_STD = 5.5              # Empty bare metal channel has uniform brightness (std < 5.0)

# ---- shape filters (tuned for all sizes of dried chillies) ----
MIN_AREA      = 100
MAX_AREA      = 35000
MIN_ASPECT    = 1.1
MAX_ASPECT    = 16.0
MAX_WIDTH_PX  = 65
MAX_TILT_DEG  = 85
EXTENT_MIN    = 0.10
MIN_LEN       = 14
MAX_LEN       = 320
BLOB_MARGIN   = 2                # Keep tight to chili body (do NOT merge with far shadows)

# ---- measuring boxes on both ends ----
END_INSET     = 0.20
END_BOX_MIN   = 8
END_BOX_MAX   = 36
MIN_BOX_OBJ   = 8

# ---- decision weights ----
W_WIDTH       = 1.6
W_RED         = 1.0
A_FULL        = 12.0
MIN_SCORE     = 0.05

# ---- rules ----
STOPPER_GAP_MAX_PX = 9999
DECIDE_MIN     = 0.15
STABLE_N       = 3               # Fast 3-frame confirmation (~75ms)
CLEAR_FRAMES   = 8               # Solid latch: require 8 empty frames before clearing
MAX_WAIT_MS    = 1500

# ---- outputs ----
OUTPUT_MODE    = "level"         # "level" = hold 3.3V until chili leaves; "pulse" = 300ms pulse
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
    """Blue for STEM, Green for APEX."""
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
sensor.set_auto_gain(False)                # Lock exposure & color
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

def region_redness(img, roi, obj_thrs):
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        return None

def object_threshold(img):
    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0

    # If the channel has almost no brightness contrast, it's empty bare metal
    if l_std < MIN_CHILI_STD:
        return [(0, 0, 0, 0, 0, 0)], 0

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

scan = {"raw": 0, "shape": 0, "best_tilt": -1}

def find_chili(img, obj_thrs):
    if obj_thrs[0][1] == 0:
        scan["raw"], scan["shape"], scan["best_tilt"] = 0, 0, -1
        return None

    kw = {"roi": CHANNEL_ROI, "pixels_threshold": MIN_AREA,
          "area_threshold": MIN_AREA, "merge": True, "margin": BLOB_MARGIN}
    try:
        blobs = img.find_blobs(obj_thrs, **kw)
    except TypeError:
        kw.pop("margin")
        blobs = img.find_blobs(obj_thrs, **kw)

    scan["raw"], scan["shape"], scan["best_tilt"] = len(blobs), 0, -1
    best, best_cost = None, None
    for b in blobs:
        if not shape_ok(b):
            continue
        rect = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))
        red = region_redness(img, rect, obj_thrs) or 0.0

        scan["shape"] += 1
        E0, E1, width = axis_ends(b)
        tilt = tilt_deg(E0, E1)
        if scan["best_tilt"] < 0 or tilt < scan["best_tilt"]:
            scan["best_tilt"] = int(tilt)
        if tilt > MAX_TILT_DEG:
            continue
        E_stop, E_far, dist = pick_stopper_end(E0, E1)

        cost = -_get(b, "pixels") + 0.25 * tilt
        if best_cost is None or cost < best_cost:
            best = (E_stop, E_far, width, dist, rect, tilt, red)
            best_cost = cost
    return best

def end_boxes(E_stop, E_far, width):
    side = min(max(width * 1.0, END_BOX_MIN), END_BOX_MAX)
    dx, dy = E_far[0] - E_stop[0], E_far[1] - E_stop[1]
    near = (E_stop[0] + END_INSET * dx, E_stop[1] + END_INSET * dy)
    far = (E_far[0] - END_INSET * dx, E_far[1] - END_INSET * dy)
    return (clamp_roi(near[0] - side/2.0, near[1] - side/2.0, side, side),
            clamp_roi(far[0] - side/2.0, far[1] - side/2.0, side, side))

def check_stalk(img, E_stop, E_far, width, rect):
    """Detect if a pale organic stalk (tan/green/yellow) extends beyond the chili body."""
    if not rect:
        return 0.0
    bx, by, bw, bh = rect
    cx, cy, cw, ch = CHANNEL_ROI

    # Region below body towards stopper (exclude the bottom steel bracket lip)
    max_y_near = min(cy + ch - 12, by + bh + 45)
    h_near = max(0, max_y_near - (by + bh))
    roi_near = clamp_roi(cx, by + bh, cw, h_near)

    # Region above body away from stopper
    h_far = min(45, max(0, by - cy))
    roi_far = clamp_roi(cx, max(cy, by - h_far), cw, h_far)

    # Organic stalk threshold: Warm/colored plant material (tan/yellow/green/brown)
    # Rejects cold neutral steel shadows & black brackets
    stalk_thrs = [(35, 88, -25, 45, 4, 60), (30, 85, 3, 50, -20, 50)]
    px_near = count_px(img, roi_near, stalk_thrs)
    px_far = count_px(img, roi_far, stalk_thrs)

    if px_near >= 10 and px_near > px_far * 1.5:
        return 1.0   # Stalk extends towards stopper -> STEM at stopper!
    elif px_far >= 10 and px_far > px_near * 1.5:
        return -1.0  # Stalk extends away from stopper -> APEX at stopper!
    return 0.0

def look(img, obj_thrs):
    out = {"reason": "empty", "score": 0.0, "a_near": None, "a_far": None,
           "spread": 0.0, "boxes": [], "rect": None, "E_stop": None,
           "E_far": None, "dist": -1, "tilt": -1, "red": 0.0,
           "o_near": 0, "o_far": 0, "s_width": 0.0, "s_red": 0.0, "s_stalk": 0.0}

    found = find_chili(img, obj_thrs)
    if found is None:
        return out
    E_stop, E_far, width, dist, rect, tilt, red = found
    out["E_stop"], out["E_far"] = E_stop, E_far
    out["dist"], out["rect"], out["tilt"], out["red"] = dist, rect, tilt, red

    boxes = end_boxes(E_stop, E_far, width)
    out["boxes"] = list(boxes)

    if dist > STOPPER_GAP_MAX_PX:
        out["reason"] = "not_at_stopper"
        return out

    o_near = count_px(img, boxes[0], obj_thrs)
    o_far = count_px(img, boxes[1], obj_thrs)
    out["o_near"], out["o_far"] = o_near, o_far
    if o_near + o_far < MIN_BOX_OBJ:
        out["reason"] = "no_read"
        return out

    # 1. Thickness comparison (wide calyx shoulder vs pointed tip)
    s_width = (o_near - o_far) / float(o_near + o_far)

    # 2. Redness comparison
    a_near = region_redness(img, boxes[0], obj_thrs)
    a_far = region_redness(img, boxes[1], obj_thrs)
    if a_near is not None and a_far is not None:
        out["a_near"], out["a_far"] = a_near, a_far
        spread = a_far - a_near
        out["spread"] = spread
        s_red = min(1.0, max(-1.0, spread / A_FULL))
    else:
        s_red = 0.0

    # 3. Organic stalk presence beyond body
    s_stalk = check_stalk(img, E_stop, E_far, width, rect)
    out["s_stalk"] = s_stalk

    # Combined decision: Balanced between shape taper & organic stalk
    if s_stalk != 0.0:
        score = 0.60 * s_stalk + 0.40 * s_width
    else:
        score = 0.70 * s_width + 0.30 * s_red

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

# 5x7 bitmap font for bulletproof text display across all OpenMV firmware versions
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
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}

def draw_str(img, x, y, text, color=(255, 255, 255), scale=2):
    """Draw text cleanly with guaranteed tuple-safe rendering."""
    s = str(text)
    ix, iy = int(x), int(y)
    sc = int(scale)

    # 1. Try native OpenMV v5.0.0 draw_string with tuple (x, y)
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

    # 2. Bulletproof pixel-level font rendering
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
                            img.draw_rectangle((px, py, sc, sc), color=color, fill=True)
                        except Exception:
                            try:
                                img.set_pixel((px, py), color)
                            except Exception:
                                pass
        cur_x += char_w

def draw_scene(img, r, label=None, col=(0, 255, 0), status=None,
               state_name="", total=0, fps=0.0):
    """Direct, clean on-screen HUD showing only the stopper classification."""
    # 1. Channel ROI (Magenta)
    if DEBUG:
        try:
            img.draw_rectangle(CHANNEL_ROI, color=(255, 0, 255), thickness=1)
        except Exception:
            pass

    # 2. Chilli Bounding Box (Green)
    if r["rect"]:
        try:
            img.draw_rectangle(r["rect"], color=(0, 255, 0), thickness=2)
        except Exception:
            pass

    # 3. Arrow pointing to the stopper
    if r["E_stop"] and r["E_far"]:
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

    # 4. Top-Left Main Result Card (Stopper Classification Only)
    text_to_show = label if label else (status if status else state_name)
    text_color = col if label else ((255, 255, 0) if status else (200, 200, 200))

    try:
        img.draw_rectangle((6, 6, 260, 50), color=(0, 0, 0), fill=True)
        img.draw_rectangle((6, 6, 260, 50), color=text_color, thickness=2)
    except Exception:
        pass

    draw_str(img, 12, 10, text_to_show, color=text_color, scale=2)

    # 5. Score & FPS Subtitle
    if label:
        info_line = "OUTPUT LATCHED (3.3V) | %d FPS" % int(fps)
        draw_str(img, 12, 32, info_line, color=(255, 255, 255), scale=1)
    elif r["reason"] == "ok":
        info_line = "SCORE: %+.2f | %d FPS" % (r["score"], int(fps))
        draw_str(img, 12, 32, info_line, color=(255, 255, 255), scale=1)
    else:
        draw_str(img, 12, 32, "WAITING FOR CHILI | %d FPS" % int(fps), color=(180, 180, 180), scale=1)

# ============================ STATE MACHINE ===========================
WAIT, CHECK, LOCKED, CLEARING = 0, 1, 2, 3
STATE_NAME = {WAIT: "WAITING", CHECK: "CHECKING", LOCKED: "DECIDED",
              CLEARING: "COOLDOWN"}
state = WAIT
t_state = time.ticks_ms()
hold_answer, hold_n = None, 0
final = None
empty = 0
pulse_until = 0
total = 0

vote_history = []
VOTE_HISTORY_MAX = 5

def smooth_vote(current_vote):
    global vote_history
    if current_vote is None:
        if len(vote_history) > 0:
            vote_history.pop(0)
        return None
    vote_history.append(current_vote)
    if len(vote_history) > VOTE_HISTORY_MAX:
        vote_history.pop(0)
    stem_c = vote_history.count("STEM")
    pod_c = vote_history.count("POD")
    if stem_c > pod_c:
        return "STEM"
    elif pod_c > stem_c:
        return "POD"
    return current_vote

while True:
    clock.tick()
    now = time.ticks_ms()
    img = sensor.snapshot()

    obj_thrs, lim = object_threshold(img)
    r = look(img, obj_thrs)
    present = (r["reason"] == "ok")
    if not triggered():
        present = False
    score = r["score"]

    # ---------------------------- CALIBRATE ---------------------------
    if CALIBRATE:
        raw_live = ("STEM" if score > 0 else "POD") if present else None
        live = smooth_vote(raw_live)
        set_outputs(live)
        service_leds(live)
        if live:
            col = (0, 150, 255) if live == "STEM" else (0, 255, 0)
            lbl = "STOPPER: %s (%s)" % (NAME[live], "P0" if live == "STEM" else "P1")
            draw_scene(img, r, lbl, col, None, "CALIBRATE", total, clock.fps())
        else:
            status = "STOPPER: %s" % REASON_TEXT.get(r["reason"], "EMPTY")
            draw_scene(img, r, None, (255, 255, 255), status, "CALIBRATE", total, clock.fps())
        if r["reason"] == "empty":
            print("CALIB EMPTY  blobs=%d shape_ok=%d best_tilt=%d (limit %d) L<=%d fps=%.0f"
                  % (scan["raw"], scan["shape"], scan["best_tilt"],
                     MAX_TILT_DEG, lim, clock.fps()))
        else:
            print("CALIB %-24s score=%+.2f | thick %d vs %d (%+.2f) | red %+.2f | tilt=%d fps=%.0f"
                  % (REASON_TEXT.get(r["reason"], "OK"), score,
                     r["o_near"], r["o_far"], r["s_width"], r["s_red"],
                     r["tilt"], clock.fps()))
        continue

    # ------------------------------ WAIT ------------------------------
    if state == WAIT:
        set_outputs(None)
        hold_answer, hold_n = None, 0
        if present:
            state, t_state = CHECK, now

    # ------------------------------ CHECK -----------------------------
    elif state == CHECK:
        if not present:
            state, t_state = WAIT, now
        else:
            answer = "STEM" if score > 0 else "POD"
            if abs(score) >= DECIDE_MIN:
                if answer == hold_answer:
                    hold_n += 1
                else:
                    hold_answer, hold_n = answer, 1
            elapsed = time.ticks_diff(now, t_state)
            if hold_n >= STABLE_N or (elapsed >= MAX_WAIT_MS and hold_answer):
                final = hold_answer
                set_outputs(final)
                total += 1
                pulse_until = time.ticks_add(now, PULSE_MS)
                state, t_state = LOCKED, now
                print(">>> %s ARRIVED FIRST -> %s HIGH (3.3V)  ==> %s   (score=%+.2f spread=%+.1f)"
                      % (NAME[final], "P0" if final == "STEM" else "P1",
                         "ROTATE 180 (P2 HIGH)" if final == ROTATE_ON
                         else "NO ROTATE", score, r["spread"]))

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
                print("--- chili gone: ready for next ---")
                state, t_state = WAIT, now

    # ---------------------------- overlay -----------------------------
    sname = STATE_NAME.get(state, "")
    if state in (LOCKED, CLEARING) and final:
        col = (0, 150, 255) if final == "STEM" else (0, 255, 0)
        lbl = "STOPPER: %s (%s)" % (NAME[final], "P0" if final == "STEM" else "P1")
        draw_scene(img, r, lbl, col, None, sname, total, clock.fps())
        service_leds(final)
    elif state == CHECK:
        draw_scene(img, r, None, (255, 255, 0), "STOPPER: CHECKING...", sname,
                   total, clock.fps())
        service_leds(None)
    else:
        status = "STOPPER: %s" % REASON_TEXT.get(r["reason"], "WAITING")
        draw_scene(img, r, None, (255, 255, 255), status, sname,
                   total, clock.fps())
        service_leds(None)

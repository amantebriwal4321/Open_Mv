# main.py  —  OpenMV Cam H7 Plus  —  FACTORY chili stem-orientation
# Deploy: save this file onto the camera as  main.py  (it auto-runs on power-up).
#
# Job: a chili arrives on the tray under the camera. Decide which END is the
#      STEM so the plate can be rotated to present the body to the cutter.
#      Output on GPIO:  P0 = stem LEFT, P1 = stem RIGHT.
#
# Why this is robust (addresses "different colours / near-black / not 100%"):
#   SEGMENTATION  = background subtraction (empty tray reference).  Detects the
#                   chili by CHANGE, so colour/darkness of the chili does NOT
#                   matter — a black chili silhouettes just as well as a red one.
#   STEM DECISION = vote of independent cues, so no single flaky measure decides:
#                     * COLOUR : stem end (tan calyx / seeds) is LESS red than
#                                the deep-red body  (skipped automatically for a
#                                non-red chili where it gives no signal).
#                     * SHAPE  : the wide "shoulder" and the body mass sit toward
#                                the stem end; the tip tapers to a point.
#   STABILITY     = must agree for N frames + a present/clear state machine, so
#                   it fires ONCE per chili and never on a half-arrived one.
#
# Calibrate TRAY_ROI once (see the vendor's adjustrayrect.py), keep the tray
# EMPTY for the startup countdown, then feed chilies.

import sensor, image, time
from pyb import LED
# from pyb import Pin      # <-- uncomment for real GPIO output (see bottom)

# =============================== CONFIG ===============================
W, H              = 320, 240
TRAY_ROI          = (10, 75, 300, 90)   # (x,y,w,h) band the chili passes through
DESIRED_STEM_SIDE = "LEFT"              # informational; both sides are output

# --- segmentation (background subtraction) ---
DIFF_THRESH       = 30      # foreground if |frame-background| brightness > this
BG_WARMUP_MS      = 3000    # keep tray EMPTY this long at startup to learn it
MORPH             = 1       # erode/dilate passes to clean speckle

# --- presence gating (blob must look like a chili) ---
MIN_AREA          = 500     # ignore small noise / debris
MAX_AREA          = 40000   # ignore giant blobs (glare, hand, two chilies)
MIN_ASPECT        = 1.4     # chili is elongated; rounder -> ambiguous

# --- decision stability ---
STABLE_N          = 4       # this many agreeing frames before we commit
CLEAR_FRAMES      = 3       # empty frames before we accept the next chili

# --- cue weights ---
W_COLOR, W_CENTROID, W_MASS, W_SHOULDER = 1.4, 0.8, 1.0, 1.0

# --- GPIO ---
RELAY_ACTIVE_LOW  = True    # most relay boards are active-LOW
USE_GPIO          = False   # set True once wired (P0=left, P1=right)

# =============================== SENSOR ==============================
sensor.reset()
sensor.set_pixformat(sensor.RGB565)     # colour needed for the calyx cue
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)
sensor.set_auto_gain(False)             # LOCK so background subtraction is valid
sensor.set_auto_whitebal(False)
sensor.set_auto_exposure(False)
clock = time.clock()

red_led, green_led = LED(1), LED(2)

# background + pristine-colour frame buffers (kept in SDRAM, no SD card needed)
BG  = sensor.alloc_extra_fb(W, H, sensor.RGB565)
CUR = sensor.alloc_extra_fb(W, H, sensor.RGB565)

# ============================== HELPERS =============================
def _get(obj, name, *args):
    """Method-or-property safe accessor (OpenMV firmware varies)."""
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def learn_background():
    red_led.on()
    print("Learning EMPTY tray -- keep it clear...")
    t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t) < BG_WARMUP_MS:
        sensor.snapshot()
    BG.replace(sensor.snapshot())
    red_led.off()
    print("Background learned. Ready.")

def foreground_blob(img):
    """Background-subtract -> binary mask -> largest chili-sized blob.
    Leaves CUR holding the pristine colour frame for the colour cue."""
    CUR.replace(img)                     # keep colour copy BEFORE we destroy img
    img.difference(BG)
    img.to_grayscale()
    img.binary([(DIFF_THRESH, 255)])
    if MORPH:
        img.erode(MORPH); img.dilate(MORPH + 1)
    try:
        blobs = img.find_blobs([(128, 255)], roi=TRAY_ROI, merge=True,
                               pixels_threshold=MIN_AREA, area_threshold=MIN_AREA,
                               x_hist_bins_max=40, y_hist_bins_max=40)
    except TypeError:
        blobs = img.find_blobs([(128, 255)], roi=TRAY_ROI, merge=True,
                               pixels_threshold=MIN_AREA, area_threshold=MIN_AREA)
    if not blobs:
        return None
    b = max(blobs, key=lambda x: _get(x, "pixels"))
    if _get(b, "pixels") > MAX_AREA:
        return None
    return b

def redness(roi):
    """(a-b) mean over CUR in roi. High = deep-red body, low = tan calyx."""
    try:
        s = CUR.get_statistics(roi=roi)
        return _get(s, "a_mean") - _get(s, "b_mean")
    except Exception:
        return None

def profile_shape(b, horizontal):
    """Return (s_mass, s_shoulder) in [-1,1]; + => stem toward the P1 end."""
    try:
        w = [float(v) for v in _get(b, "x_histogram" if horizontal else "y_histogram")]
    except Exception:
        return 0.0, 0.0
    n = len(w); tot = sum(w)
    if n < 3 or tot <= 0:
        return 0.0, 0.0
    c = (n - 1) / 2.0
    ci = sum(i * wi for i, wi in enumerate(w)) / tot
    s_mass = (ci - c) / c
    lo = sum(w[int(0.10*n):int(0.40*n)]); hi = sum(w[int(0.60*n):int(0.90*n)])
    s_sh = (hi - lo) / (hi + lo) if (hi + lo) else 0.0
    return s_mass, s_sh

def decide(b):
    """Return (side, confidence, debug) for the chili blob b."""
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    cx, cy = _get(b, "cx"), _get(b, "cy")
    if max(bw, bh) / max(1, min(bw, bh)) < MIN_ASPECT:
        return None, 0.0, None

    horizontal = bw >= bh
    if horizontal:
        P0, P1 = (bx, cy), (bx + bw, cy)
        s_c = (cx - (bx + bw / 2.0)) / (bw / 2.0)
        q = max(6, bw // 5)
        roiA, roiB = (bx, by, q, bh), (bx + bw - q, by, q, bh)
    else:
        P0, P1 = (cx, by), (cx, by + bh)
        s_c = (cy - (by + bh / 2.0)) / (bh / 2.0)
        q = max(6, bh // 5)
        roiA, roiB = (bx, by, bw, q), (bx, by + bh - q, bw, q)

    S = W_CENTROID * s_c
    Wt = W_CENTROID
    s_mass, s_sh = profile_shape(b, horizontal)
    S += W_MASS * s_mass + W_SHOULDER * s_sh
    Wt += W_MASS + W_SHOULDER

    rA, rB = redness(roiA), redness(roiB)
    if rA is not None and rB is not None:
        s_color = (rA - rB) / (abs(rA) + abs(rB) + 1.0)  # +=> B less red => stem@P1
        S += W_COLOR * s_color
        Wt += W_COLOR

    stem_pt = P1 if S > 0 else P0
    body_pt = P0 if S > 0 else P1
    conf = min(1.0, abs(S) / Wt) if Wt else 0.0
    side = "LEFT" if stem_pt[0] < body_pt[0] else "RIGHT"
    dbg = {"rect": (bx, by, bw, bh), "stem": stem_pt, "body": body_pt,
           "rA": rA, "rB": rB}
    return side, conf, dbg

def output(side):
    if not USE_GPIO:
        return
    # left_pin / right_pin created once at import (see bottom of file)
    on, off = (0, 1) if RELAY_ACTIVE_LOW else (1, 0)
    left_pin.value(on if side == "LEFT" else off)
    right_pin.value(on if side == "RIGHT" else off)

# ============================== STARTUP =============================
# if USE_GPIO:
#     left_pin  = Pin('P0', Pin.OUT_PP)
#     right_pin = Pin('P1', Pin.OUT_PP)
#     left_pin.value(1 if RELAY_ACTIVE_LOW else 0)
#     right_pin.value(1 if RELAY_ACTIVE_LOW else 0)

learn_background()

# ============================ STATE MACHINE ==========================
IDLE, CLEARING = 0, 1
state = IDLE
run_side, run_count = None, 0
empty_count = 0

while True:
    clock.tick()
    img = sensor.snapshot()
    b = foreground_blob(img)             # img now holds the binary mask

    if b is None:
        empty_count += 1
        run_side, run_count = None, 0
        green_led.off()
        if state == CLEARING and empty_count >= CLEAR_FRAMES:
            state = IDLE                 # previous chili has left; ready for next
            output("NONE") if False else None
        # print("empty")
        continue
    empty_count = 0

    side, conf, dbg = decide(b)
    if side is None:
        continue

    # ---- debug overlay on the mask (view in IDE; harmless on the device) ----
    try:
        img.draw_rectangle(TRAY_ROI, color=255, thickness=1)
        img.draw_rectangle(dbg["rect"], color=255, thickness=2)
        sp = (int(dbg["stem"][0]), int(dbg["stem"][1]))
        bp = (int(dbg["body"][0]), int(dbg["body"][1]))
        img.draw_line((sp[0], sp[1], bp[0], bp[1]), color=200, thickness=2)
        img.draw_circle((sp[0], sp[1], 9), color=255, thickness=2)   # STEM marker
        img.draw_string(4, 4, "STEM %s" % side, color=255, scale=2)
    except Exception:
        pass

    # ---- stability: require STABLE_N agreeing frames, fire once ----
    if state == IDLE:
        if side == run_side:
            run_count += 1
        else:
            run_side, run_count = side, 1
        if run_count >= STABLE_N:
            output(side)
            green_led.on()
            ra = dbg["rA"] if dbg["rA"] is not None else 0
            rb = dbg["rB"] if dbg["rB"] is not None else 0
            print(">>> STEM=%s conf=%.2f (redA=%.0f redB=%.0f)  ACTUATE" %
                  (side, conf, ra, rb))
            state = CLEARING
            run_side, run_count = None, 0

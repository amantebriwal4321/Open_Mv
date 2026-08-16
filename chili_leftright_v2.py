# chili_leftright_v2.py  —  OpenMV Cam H7 Plus
# Stem-side detection with SMOOTHING + stronger cues.
#     STEM on LEFT  -> P0 HIGH (3.3V, PULSE_MS)
#     STEM on RIGHT -> P1 HIGH (3.3V, PULSE_MS)
# P0/P1 are SIGNALS: wire them to a relay module / PLC input, never a solenoid.
#
# v2 changes:
#  - end-mass cue measured directly with sub-ROI blob counts (no histograms)
#  - EMA smoothing + deadband: the stem marker cannot flip on one noisy frame
#  - auto re-arm timeout so bench testing doesn't stay stuck at armed=False
#  - prints per-cue numbers so we can tune from serial output

import sensor, image, time
from pyb import Pin, LED

# =============================== CONFIG ===============================
# WIDENED: catches dark/dim chili parts too. If the yellow box still misses
# part of the chili, tune with Tools > Machine Vision > Threshold Editor.
RED_THR      = (5, 100, 8, 127, -30, 127)   # LAB range for the red body
VIEW_MASK    = True       # True = show WHAT the camera segments (white=chili).
                          # Verify the mask covers the WHOLE chili, then set
                          # False to see the normal colour view again.
TRAY_ROI     = None       # None = whole frame; factory: e.g. (10, 75, 300, 90)
MIN_AREA     = 300
MIN_ASPECT   = 1.3

EMA_ALPHA    = 0.30       # smoothing: higher = reacts faster, lower = smoother
DECIDE_MIN   = 0.06       # |smoothed score| needed before a decision counts
STABLE_N     = 5          # frames the smoothed side must hold before firing
CLEAR_FRAMES = 3          # empty frames -> chili gone -> re-arm
REARM_MS     = 4000       # bench aid: re-arm anyway after this long
PULSE_MS     = 500        # output pulse length

W_COLOR, W_MASS, W_CENTROID = 1.2, 1.2, 0.6

# =============================== OUTPUTS ==============================
left_pin  = Pin('P0', Pin.OUT_PP);  left_pin.value(0)    # stem LEFT
right_pin = Pin('P1', Pin.OUT_PP);  right_pin.value(0)   # stem RIGHT
red_led, green_led, blue_led = LED(1), LED(2), LED(3)

def fire(side):
    pin = left_pin if side == "LEFT" else right_pin
    pin.value(1); green_led.on()
    time.sleep_ms(PULSE_MS)
    pin.value(0); green_led.off()

# =============================== SENSOR ===============================
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2500)          # let auto exposure settle on the scene
sensor.set_auto_gain(False)            # ...then LOCK it
sensor.set_auto_whitebal(False)
clock = time.clock()

# ============================== HELPERS ===============================
def _get(obj, name, *args):
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def draw_safe(fn, tuple_args, flat_args, **kw):
    try:
        fn(*tuple_args, **kw)
    except TypeError:
        try:
            fn(*flat_args, **kw)
        except Exception:
            pass
    except Exception:
        pass

def count_red(img, roi):
    """Red-pixel mass inside roi (sub-ROI blob count — no histograms needed)."""
    try:
        bs = img.find_blobs([RED_THR], roi=roi, pixels_threshold=10,
                            area_threshold=10, merge=True)
        return sum(_get(x, "pixels") for x in bs)
    except Exception:
        return 0

def redness(img, roi):
    try:
        s = img.get_statistics(roi=roi)
        return _get(s, "a_mean") - _get(s, "b_mean")
    except Exception:
        return None

def measure(img):
    """One frame -> (s_plus, blob-info) where s_plus>0 means stem toward the
    'positive' end (right for horizontal, bottom for vertical)."""
    kw = {"pixels_threshold": MIN_AREA, "area_threshold": MIN_AREA, "merge": True}
    if TRAY_ROI:
        kw["roi"] = TRAY_ROI
    blobs = img.find_blobs([RED_THR], **kw)
    if not blobs:
        return None
    b = max(blobs, key=lambda x: _get(x, "pixels"))
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    cx, cy = _get(b, "cx"), _get(b, "cy")
    if max(bw, bh) / max(1, min(bw, bh)) < MIN_ASPECT:
        return None

    horizontal = bw >= bh
    if horizontal:
        e = max(6, int(bw * 0.35))
        roiA = (bx, by, e, bh)                    # negative end (left)
        roiB = (bx + bw - e, by, e, bh)           # positive end (right)
        s_c = (cx - (bx + bw / 2.0)) / (bw / 2.0)
        P0, P1 = (bx, cy), (bx + bw, cy)
    else:
        e = max(6, int(bh * 0.35))
        roiA = (bx, by, bw, e)                    # negative end (top)
        roiB = (bx, by + bh - e, bw, e)           # positive end (bottom)
        s_c = (cy - (by + bh / 2.0)) / (bh / 2.0)
        P0, P1 = (cx, by), (cx, by + bh)

    # cue 1: end mass — the shoulder (stem end) is the heavier end
    pA, pB = count_red(img, roiA), count_red(img, roiB)
    s_mass = (pB - pA) / float(pB + pA) if (pB + pA) else 0.0

    # cue 2: colour — the stem end (tan calyx) is LESS red
    rA, rB = redness(img, roiA), redness(img, roiB)
    if rA is not None and rB is not None:
        s_color = (rA - rB) / (abs(rA) + abs(rB) + 1.0)
        cw = W_COLOR
    else:
        s_color, cw = 0.0, 0.0

    s_plus = (W_MASS * s_mass + cw * s_color + W_CENTROID * s_c) \
             / (W_MASS + cw + W_CENTROID)
    return {"s": s_plus, "rect": (bx, by, bw, bh), "P0": P0, "P1": P1,
            "pA": pA, "pB": pB, "rA": rA, "rB": rB}

# ============================ STATE MACHINE ===========================
ema = 0.0
seen = 0
empty_count = 0
hold_count = 0
hold_side = None
armed = True
disarm_t = 0

while True:
    clock.tick()
    img = sensor.snapshot()
    m = measure(img)

    if m is None:
        empty_count += 1
        if empty_count >= CLEAR_FRAMES:
            ema, seen, hold_count, hold_side = 0.0, 0, 0, None
            if not armed:
                armed = True
                blue_led.off()
        continue
    empty_count = 0
    seen += 1

    # ---- smoothing: EMA of the signed score ----
    ema = (1.0 - EMA_ALPHA) * ema + EMA_ALPHA * m["s"]

    stem_pt = m["P1"] if ema >= 0 else m["P0"]
    body_pt = m["P0"] if ema >= 0 else m["P1"]
    side = "LEFT" if stem_pt[0] < body_pt[0] else "RIGHT"
    strength = abs(ema)

    # ---- optional: show the segmentation mask (white = counted as chili) ----
    if VIEW_MASK:
        try:
            img.binary([RED_THR])
        except Exception:
            pass

    # ---- overlay (dual-API safe) ----
    r = m["rect"]
    sp = (int(stem_pt[0]), int(stem_pt[1]))
    bp = (int(body_pt[0]), int(body_pt[1]))
    draw_safe(img.draw_rectangle, (r,), r, color=(255, 255, 0), thickness=2)
    draw_safe(img.draw_line, ((sp[0], sp[1], bp[0], bp[1]),),
              (sp[0], sp[1], bp[0], bp[1]), color=(0, 255, 0), thickness=2)
    draw_safe(img.draw_circle, ((sp[0], sp[1], 10),),
              (sp[0], sp[1], 10), color=(255, 0, 0), thickness=2)
    label = "STEM %s %s" % (side, "OK" if strength >= DECIDE_MIN else "?")
    draw_safe(img.draw_string, ((4, 4, label),), (4, 4, label),
              color=(255, 255, 255), scale=2)

    # ---- decide once per chili ----
    if armed and seen >= 3 and strength >= DECIDE_MIN:
        if side == hold_side:
            hold_count += 1
        else:
            hold_side, hold_count = side, 1
        if hold_count >= STABLE_N:
            print(">>> STEM=%s ema=%.2f -> POWER %s for %dms" %
                  (side, ema, "P0 (LEFT)" if side == "LEFT" else "P1 (RIGHT)",
                   PULSE_MS))
            fire(side)
            armed = False
            blue_led.on()
            disarm_t = time.ticks_ms()
            hold_side, hold_count = None, 0
    elif not armed and time.ticks_diff(time.ticks_ms(), disarm_t) > REARM_MS:
        armed = True                      # bench aid: re-arm after timeout
        blue_led.off()

    print("side=%s ema=%+.2f s=%+.2f massA/B=%d/%d redA/B=%s/%s armed=%s fps=%.0f"
          % (side, ema, m["s"], m["pA"], m["pB"],
             "%.0f" % m["rA"] if m["rA"] is not None else "?",
             "%.0f" % m["rB"] if m["rB"] is not None else "?",
             armed, clock.fps()))

# chili_factory_multi.py  —  OpenMV Cam H7 Plus  —  FACTORY  (v9)
#
# =========================== HOW IT WORKS (simple words) ===========================
# THE BIG CHANGE IN v9: THE CHILI IS FOUND BY *DARKNESS*, NOT BY COLOUR.
#   A chili is always DARKER than the tray it lies on. Red, dark red, maroon or
#   almost black - all of them are dark. So the camera finds the chili as a dark
#   object, and the brightness limit ADAPTS to the light automatically every
#   frame. This is why it now finds the chili in every frame instead of one in
#   thirty. (Colour is still used, but only to tell the two ENDS apart.)
#
# ONE CHILI -> ONE DECISION -> ONE BLINK -> WAIT FOR IT TO LEAVE -> NEXT CHILI
#       STEM LEFT  -> "STEM LEFT"  on screen, BLUE LED one blink,  P0 high
#       STEM RIGHT -> "STEM RIGHT" on screen, GREEN LED one blink, P1 high
#   States printed in the log: WAIT -> WATCH -> DECIDE -> CLEAR.
#
# HOW IT TELLS STEM FROM BODY (3 clues, all pointing the same way)
#   1) STALK   : at the stem end there are DARK pixels that are NOT red - that
#                is the stalk/calyx sticking out. The body has none of these.
#   2) RED MASS: the stem end contains FEWER red pixels than the body end.
#   3) REDNESS : the stem end is LESS RED on average than the deep-red body.
#   Every frame casts one vote. The answer is taken only when a big majority of
#   frames agree, so a single bad frame can never decide anything.
#
# IF A CHILI IS GENUINELY AMBIGUOUS (no stem at all)
#   It still gets LEFT or RIGHT after MAX_WATCH_MS - the machine never stalls.
#
# IF IT IS NOT FINDING THE CHILI
#   The log prints a "no chili" line with the reason and the current brightness
#   limit, e.g.  raw=2 rejected: len=1 solid=1  L<=42
#   - raw = dark blobs found, rejected = why they failed the shape test.
#   Adjust MIN_LEN/MAX_LEN (chili length in pixels) or DARK_K (how dark).
#
# CALIBRATE AT THE MACHINE: 1) fixed diffused light  2) run and check the log
#   finds the chili every frame  3) set TRAY_ROI + MIN_LEN/MAX_LEN to your real
#   chilies  4) save to the camera as main.py.
# P0/P1 are 3.3V signals -> relay / PLC input only, never a solenoid.
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED

# ------------------------------- CONFIG -------------------------------
# How the chili is separated from the background:
#   "dark"  = chili is DARKER than the tray  (normal: steel/white tray)
#   "light" = chili is LIGHTER than the tray (dark conveyor belt)
DETECT_MODE  = "dark"
DARK_K       = 0.60      # how far below average brightness counts as "chili"
                         # bigger = stricter (less background picked up)
DARK_L_MIN   = 8         # brightness limit is kept inside these bounds
DARK_L_MAX   = 70

# Red ranges - now used ONLY to tell the two ends apart, not to find the chili.
RED_THRS     = [
    (0, 100, 12, 127, -20, 127),
]

VIEW_MASK    = False     # True shows exactly what the camera calls "chili"
TRAY_ROI     = None      # e.g. (10, 60, 300, 120); None = whole frame

# ---- chili-shape filters ----
MIN_AREA     = 250
MAX_AREA     = 25000
MIN_ASPECT   = 1.5
MAX_ASPECT   = 12.0
EXTENT_MIN   = 0.18
MIN_LEN      = 40        # px  <-- measure YOUR chilies on screen and tighten
MAX_LEN      = 300       # px
BLOB_MARGIN  = 14        # glue broken pieces of the SAME chili together

# ---- decision timing ----
MIN_WATCH_MS = 500       # watch at least this long
MAX_WATCH_MS = 3000      # then commit to the majority whatever happens
MIN_SAMPLES  = 8         # minimum frames collected
AGREE_MIN    = 0.70      # this share of frames must agree
LOST_FRAMES  = 10        # chili missing this many frames -> abort observation
CLEAR_FRAMES = 6         # empty frames before the next chili is accepted

# ---- output ----
OUTPUT_MODE  = "level"   # "level" = hold port HOLD_MS; "pulse" = short trigger
HOLD_MS      = 1000
PULSE_MS     = 300
BLINK_ON_MS  = 500       # ONE blink at the moment of decision

POS_ALPHA    = 0.30      # arrow smoothing
END_FRAC     = 0.30      # how much of each end is measured

# ---- clue weights ----
W_STALK, W_REDMASS, W_REDNESS = 1.6, 1.2, 1.0

# ------------------------------- OUTPUTS ------------------------------
left_pin  = Pin('P0', Pin.OUT_PP);  left_pin.value(0)    # STEM LEFT
right_pin = Pin('P1', Pin.OUT_PP);  right_pin.value(0)   # STEM RIGHT
led_blue, led_green = LED(3), LED(2)

def set_ports(side):
    """Mutually exclusive: at most ONE port high at any moment."""
    left_pin.value(1 if side == "LEFT" else 0)
    right_pin.value(1 if side == "RIGHT" else 0)

def leds_off():
    led_blue.off()
    led_green.off()

# ------------------------------- SENSOR -------------------------------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)
sensor.set_auto_gain(False)
sensor.set_auto_whitebal(False)
clock = time.clock()

# ------------------------------- HELPERS ------------------------------
def _get(obj, name, *args):
    """Method-or-property safe accessor (firmware APIs vary)."""
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def _stat(st, name, default=0.0):
    try:
        v = _get(st, name)
        return float(v)
    except Exception:
        return default

def draw_safe(fn, tuple_args, flat_args, **kw):
    """This firmware wants tuples for some draw calls, flat ints for others."""
    try:
        fn(*tuple_args, **kw)
    except TypeError:
        try:
            fn(*flat_args, **kw)
        except Exception:
            pass
    except Exception:
        pass

def draw_stem_arrow(img, bx, by, sx, sy):
    dx, dy = sx - bx, sy - by
    L = math.sqrt(dx*dx + dy*dy)
    if L < 5:
        return
    ux, uy = dx / L, dy / L
    px, py = -uy, ux
    h1 = (int(sx - 12*ux + 7*px), int(sy - 12*uy + 7*py))
    h2 = (int(sx - 12*ux - 7*px), int(sy - 12*uy - 7*py))
    draw_safe(img.draw_line, ((bx, by, sx, sy),), (bx, by, sx, sy),
              color=(0, 255, 0), thickness=2)
    draw_safe(img.draw_line, ((h1[0], h1[1], sx, sy),), (h1[0], h1[1], sx, sy),
              color=(0, 255, 0), thickness=2)
    draw_safe(img.draw_line, ((h2[0], h2[1], sx, sy),), (h2[0], h2[1], sx, sy),
              color=(0, 255, 0), thickness=2)
    draw_safe(img.draw_circle, ((sx, sy, 8),), (sx, sy, 8),
              color=(255, 0, 0), thickness=2)

def clamp_roi(x, y, w, h):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(320, x + w), min(240, y + h)
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))

def count_thr(img, roi, thrs):
    """Pixels inside roi matching any threshold in thrs."""
    if roi[2] < 2 or roi[3] < 2:
        return 0
    try:
        bs = img.find_blobs(thrs, roi=roi, pixels_threshold=5,
                            area_threshold=5, merge=True)
        return sum(_get(x, "pixels") for x in bs)
    except Exception:
        return 0

def redness(img, roi):
    """Mean (a - b): high = deep-red body, low = stalk / calyx / seeds."""
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(roi=roi)
        return _stat(st, "a_mean") - _stat(st, "b_mean")
    except Exception:
        return None

def object_threshold(img):
    """Brightness range that separates the chili from the tray, adapted to
    the current light every frame (works for red, maroon or near-black)."""
    try:
        st = img.get_statistics(roi=TRAY_ROI) if TRAY_ROI else img.get_statistics()
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0
    if DETECT_MODE == "light":
        lim = l_mean + DARK_K * l_std
        lim = min(max(lim, 100 - DARK_L_MAX), 100 - DARK_L_MIN)
        return [(int(lim), 100, -128, 127, -128, 127)], int(lim)
    lim = l_mean - DARK_K * l_std
    lim = min(max(lim, DARK_L_MIN), DARK_L_MAX)
    return [(0, int(lim), -128, 127, -128, 127)], int(lim)

reject = {"len": 0, "solid": 0, "aspect": 0, "area": 0}

def looks_like_chili(b):
    bw, bh, px = _get(b, "w"), _get(b, "h"), _get(b, "pixels")
    if px > MAX_AREA:
        reject["area"] += 1
        return False
    length, width = max(bw, bh), max(1, min(bw, bh))
    if not (MIN_ASPECT <= length / width <= MAX_ASPECT):
        reject["aspect"] += 1
        return False
    if not (MIN_LEN <= length <= MAX_LEN):
        reject["len"] += 1
        return False
    if px / float(bw * bh) < EXTENT_MIN:
        reject["solid"] += 1
        return False
    return True

def find_chilies(img, obj_thrs):
    """Dark (or light) chili-shaped blobs; BLOB_MARGIN glues fragments."""
    kw = {"pixels_threshold": MIN_AREA, "area_threshold": MIN_AREA,
          "merge": True, "margin": BLOB_MARGIN}
    if TRAY_ROI:
        kw["roi"] = TRAY_ROI
    try:
        blobs = img.find_blobs(obj_thrs, **kw)
    except TypeError:                       # firmware without 'margin'
        kw.pop("margin")
        blobs = img.find_blobs(obj_thrs, **kw)
    return blobs, [b for b in blobs if looks_like_chili(b)]

def measure(img, b, obj_thrs):
    """One frame, one chili -> signed score.
    score > 0  =>  stem is toward the RIGHT (or BOTTOM) end."""
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    cx, cy = _get(b, "cx"), _get(b, "cy")
    horizontal = bw >= bh
    if horizontal:
        e = max(6, int(bw * END_FRAC))
        roiA = clamp_roi(bx, by, e, bh)                 # left end
        roiB = clamp_roi(bx + bw - e, by, e, bh)        # right end
        P0, P1 = (bx, cy), (bx + bw, cy)
    else:
        e = max(6, int(bh * END_FRAC))
        roiA = clamp_roi(bx, by, bw, e)                 # top end
        roiB = clamp_roi(bx, by + bh - e, bw, e)        # bottom end
        P0, P1 = (cx, by), (cx, by + bh)

    objA, objB = count_thr(img, roiA, obj_thrs), count_thr(img, roiB, obj_thrs)
    redA, redB = count_thr(img, roiA, RED_THRS), count_thr(img, roiB, RED_THRS)

    # clue 1: STALK = chili pixels that are NOT red (stalk / calyx / seeds)
    nrA, nrB = max(0, objA - redA), max(0, objB - redB)
    s_stalk = (nrB - nrA) / float(nrB + nrA + 1)

    # clue 2: RED MASS - the stem end holds less red body
    s_redmass = (redA - redB) / float(redA + redB + 1)

    # clue 3: REDNESS - the stem end is less red on average
    rA, rB = redness(img, roiA), redness(img, roiB)
    if rA is not None and rB is not None:
        s_redness = (rA - rB) / (abs(rA) + abs(rB) + 1.0)
        rw = W_REDNESS
    else:
        s_redness, rw = 0.0, 0.0

    s = (W_STALK*s_stalk + W_REDMASS*s_redmass + rw*s_redness) \
        / (W_STALK + W_REDMASS + rw)
    return {"s": s, "cx": cx, "cy": cy, "rect": (bx, by, bw, bh),
            "P0": P0, "P1": P1, "nrA": nrA, "nrB": nrB}

def pick_nearest(blobs, cx, cy):
    """Keep following the SAME chili while observing it."""
    best, bestd = None, 1e9
    for b in blobs:
        d = abs(_get(b, "cx") - cx) + abs(_get(b, "cy") - cy)
        if d < bestd:
            best, bestd = b, d
    return best

# ============================ STATE MACHINE ===========================
WAIT, WATCH, DECIDE, CLEAR = 0, 1, 2, 3
state = WAIT
t_state = time.ticks_ms()

votes_l = votes_r = samples = 0
score_sum = 0.0
lost = empty = 0
sub_cx = sub_cy = 0
final = None
blink_t = 0
draw_s = None
quiet = 0

while True:
    clock.tick()
    now = time.ticks_ms()
    img = sensor.snapshot()

    obj_thrs, lim = object_threshold(img)
    for k in reject:
        reject[k] = 0
    raw, blobs = find_chilies(img, obj_thrs)

    if VIEW_MASK:
        try:
            img.binary(obj_thrs)
        except Exception:
            pass

    # ------------------------------ WAIT ------------------------------
    if state == WAIT:
        set_ports(None)
        leds_off()
        if blobs:
            b = max(blobs, key=lambda x: _get(x, "pixels"))
            sub_cx, sub_cy = _get(b, "cx"), _get(b, "cy")
            votes_l = votes_r = samples = 0
            score_sum = 0.0
            lost = 0
            draw_s = None
            state, t_state = WATCH, now
            print("--- chili arrived: watching ---")
        else:
            quiet += 1
            if quiet % 20 == 0:            # ~ once per second
                print("no chili: raw=%d rejected len=%d solid=%d aspect=%d "
                      "area=%d  L<=%d  fps=%.0f"
                      % (len(raw), reject["len"], reject["solid"],
                         reject["aspect"], reject["area"], lim, clock.fps()))

    # ----------------------------- WATCH ------------------------------
    elif state == WATCH:
        b = pick_nearest(blobs, sub_cx, sub_cy) if blobs else None
        if b is None:
            lost += 1
            if lost >= LOST_FRAMES:
                print("--- chili left before deciding: reset ---")
                state, t_state = WAIT, now
        else:
            lost = 0
            m = measure(img, b, obj_thrs)
            sub_cx, sub_cy = m["cx"], m["cy"]
            samples += 1
            score_sum += m["s"]
            if m["s"] >= 0:
                if m["P1"][0] < m["P0"][0]:
                    votes_l += 1
                else:
                    votes_r += 1
            else:
                if m["P0"][0] < m["P1"][0]:
                    votes_l += 1
                else:
                    votes_r += 1

            avg = score_sum / samples
            a_stem = m["P1"] if avg >= 0 else m["P0"]
            a_body = m["P0"] if avg >= 0 else m["P1"]
            if draw_s is None:
                draw_s = [float(a_stem[0]), float(a_stem[1]),
                          float(a_body[0]), float(a_body[1])]
            else:
                a = POS_ALPHA
                draw_s[0] = (1-a)*draw_s[0] + a*a_stem[0]
                draw_s[1] = (1-a)*draw_s[1] + a*a_stem[1]
                draw_s[2] = (1-a)*draw_s[2] + a*a_body[0]
                draw_s[3] = (1-a)*draw_s[3] + a*a_body[1]

            lead = max(votes_l, votes_r)
            agree = lead / float(samples)
            elapsed = time.ticks_diff(now, t_state)
            ready = (elapsed >= MIN_WATCH_MS and samples >= MIN_SAMPLES
                     and agree >= AGREE_MIN)
            timeout = elapsed >= MAX_WATCH_MS and samples >= 3

            r = m["rect"]
            draw_safe(img.draw_rectangle, (r,), r, color=(255, 255, 0), thickness=2)
            draw_stem_arrow(img, int(draw_s[2]), int(draw_s[3]),
                            int(draw_s[0]), int(draw_s[1]))
            msg = "CHECKING %d%%" % int(agree * 100)
            draw_safe(img.draw_string, ((r[0], max(0, r[1]-18), msg),),
                      (r[0], max(0, r[1]-18), msg),
                      color=(255, 255, 255), scale=2)

            if ready or timeout:
                final = "LEFT" if votes_l >= votes_r else "RIGHT"
                set_ports(final)
                (led_blue if final == "LEFT" else led_green).on()
                blink_t = now
                state, t_state = DECIDE, now
                print(">>> DECISION: STEM %s (agree=%d%% avg=%+.2f frames=%d %s) -> %s"
                      % (final, int(agree*100), avg, samples,
                         "clear" if ready else "timeout",
                         "P0" if final == "LEFT" else "P1"))
            else:
                print("WATCH %dms n=%d agree=%d%% avg=%+.2f stalkA/B=%d/%d fps=%.0f"
                      % (elapsed, samples, int(agree*100), avg,
                         m["nrA"], m["nrB"], clock.fps()))

    # ----------------------------- DECIDE -----------------------------
    elif state == DECIDE:
        if time.ticks_diff(now, blink_t) >= BLINK_ON_MS:
            leds_off()                       # ONE blink, then dark
        hold = PULSE_MS if OUTPUT_MODE == "pulse" else HOLD_MS
        if time.ticks_diff(now, t_state) >= hold:
            set_ports(None)
            leds_off()
            state, t_state = CLEAR, now
            empty = 0
        b = pick_nearest(blobs, sub_cx, sub_cy) if blobs else None
        if b is not None:
            r = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))
            draw_safe(img.draw_rectangle, (r,), r, color=(0, 255, 0), thickness=2)
            if draw_s:
                draw_stem_arrow(img, int(draw_s[2]), int(draw_s[3]),
                                int(draw_s[0]), int(draw_s[1]))
            lbl = "STEM %s" % final
            draw_safe(img.draw_string, ((r[0], max(0, r[1]-18), lbl),),
                      (r[0], max(0, r[1]-18), lbl),
                      color=(255, 255, 255), scale=2)

    # ------------------------------ CLEAR -----------------------------
    elif state == CLEAR:
        set_ports(None)
        leds_off()
        b = pick_nearest(blobs, sub_cx, sub_cy) if blobs else None
        if b is None:
            empty += 1
            if empty >= CLEAR_FRAMES:
                print("--- ready for next chili ---")
                quiet = 0
                state, t_state = WAIT, now
        else:
            empty = 0
            r = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))
            draw_safe(img.draw_rectangle, (r,), r, color=(0, 255, 0), thickness=2)
            lbl = "STEM %s (done)" % final
            draw_safe(img.draw_string, ((r[0], max(0, r[1]-18), lbl),),
                      (r[0], max(0, r[1]-18), lbl),
                      color=(255, 255, 255), scale=2)

    if TRAY_ROI:
        draw_safe(img.draw_rectangle, (TRAY_ROI,), TRAY_ROI,
                  color=(255, 0, 255), thickness=1)

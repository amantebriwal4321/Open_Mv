# chili_stem_detect.py  —  OpenMV Cam H7 Plus
# Which end of a dried red chili is the STEM (tan calyx) vs the BODY (deep-red tip)?
# -> outputs LEFT / RIGHT so the plate can be rotated for the cutter.
#
# Strategy (fully transparent, no black-box .mpy):
#   1. Segment the chili by REDNESS (LAB 'a'), not brightness -> ignores the
#      shiny-steel glare and works for dark or bright red bodies.
#   2. Decide stem end by voting several cues:
#        - COLOR: the stem end (tan calyx / orange seeds) is LESS red than the
#          deep-red body end.  <-- strongest signal for these dried chilies.
#        - GEOMETRY: mass/shoulder sits toward the wide stem end (centroid +
#          optional projection-profile cues).
#   3. Vote across a few frames for a stable answer.

import sensor, image, time, math

# ----------------------------- CONFIG -----------------------------
# LAB threshold that selects the chili (red body + tan calyx), rejects gray
# steel and white glare.  (L_lo,L_hi, A_lo,A_hi, B_lo,B_hi).  A>~10 = reddish.
RED_THRESHOLD     = (0, 100, 12, 127, -20, 127)

TRAY_ROI          = (10, 75, 310, 85)   # from the vendor files; RE-CALIBRATE for
                                        # your mount (see adjustrayrect.py)
DESIRED_STEM_SIDE = "LEFT"              # stem should end up on this side
MIN_PIXELS        = 250                 # ignore blobs smaller than this
MIN_ASPECT        = 1.4                 # box long/short below this -> ambiguous
HIST_BINS         = 40                  # projection-profile resolution
END_FRAC          = 0.15
FRAMES_TO_VOTE    = 5
CONF_ACCEPT       = 0.15

# cue weights
W_COLOR, W_CENTROID, W_MASS, W_ARGMAX, W_SHOULDER, W_STALK = 1.4, 0.8, 1.0, 0.5, 1.0, 0.6

# ----------------------------- SENSOR -----------------------------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)      # colour: we NEED the tan-calyx cue
sensor.set_framesize(sensor.QVGA)        # 320x240
sensor.skip_frames(time=2000)
sensor.set_auto_gain(False)              # LOCK exposure/colour -> stable reads
sensor.set_auto_whitebal(False)
clock = time.clock()

# ----------------------------- HELPERS ----------------------------
def _get(obj, name, *args):
    """Call if it's a method, read if it's a property (firmware varies)."""
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def _redness(img, roi):
    """Mean 'redness' (a - b) of chili pixels inside roi. High = deep red body,
    low = tan/yellow calyx.  Returns None if no chili pixels there."""
    try:
        s = img.get_statistics(thresholds=[RED_THRESHOLD], roi=roi)
        a = _get(s, "a_mean")
        b = _get(s, "b_mean")
        return a - b
    except Exception:
        return None

def _profile_cues(w):
    """Geometry cues on a width profile w (index 0 = P0 end .. last = P1 end).
    Returns (S, Wtot); S>0 => stem toward the P1 end."""
    n = len(w)
    total = sum(w)
    if n < 3 or total <= 0:
        return 0.0, 0.0
    center = (n - 1) / 2.0
    ci = sum(i * wi for i, wi in enumerate(w)) / total          # mass centroid
    s_mass = (ci - center) / center
    ai = max(range(n), key=lambda i: w[i])                       # widest slice
    s_arg = (ai - center) / center
    lo = sum(w[int(0.10 * n):int(0.40 * n)])                     # shoulder region
    hi = sum(w[int(0.60 * n):int(0.90 * n)])
    s_sh = (hi - lo) / (hi + lo) if (hi + lo) else 0.0
    e = max(2, int(END_FRAC * n))                               # stalk signature
    def stalk(seg):
        tip = sum(seg[:2]) / 2.0
        sh = max(seg)
        return (sh - tip) / (sh + tip) if (sh + tip) else 0.0
    s_stalk = stalk(w[n - e:][::-1]) - stalk(w[:e])
    S = W_MASS*s_mass + W_ARGMAX*s_arg + W_SHOULDER*s_sh + W_STALK*s_stalk
    Wt = W_MASS + W_ARGMAX + W_SHOULDER + W_STALK
    return S, Wt

def _profile(b, horizontal):
    try:
        p = _get(b, "x_histogram" if horizontal else "y_histogram")
        return [float(v) for v in p]
    except Exception:
        return []

def detect_once(img):
    try:
        blobs = img.find_blobs([RED_THRESHOLD], roi=TRAY_ROI,
                               pixels_threshold=MIN_PIXELS, area_threshold=MIN_PIXELS,
                               merge=True, x_hist_bins_max=HIST_BINS,
                               y_hist_bins_max=HIST_BINS)
    except TypeError:
        blobs = img.find_blobs([RED_THRESHOLD], roi=TRAY_ROI,
                               pixels_threshold=MIN_PIXELS, area_threshold=MIN_PIXELS,
                               merge=True)
    if not blobs:
        return None
    b = max(blobs, key=lambda x: _get(x, "pixels"))
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    cx, cy = _get(b, "cx"), _get(b, "cy")
    if max(bw, bh) / max(1, min(bw, bh)) < MIN_ASPECT:
        return {"found": True, "ambiguous": True}

    horizontal = bw >= bh
    if horizontal:
        P0, P1 = (bx, cy), (bx + bw, cy)                 # left -> right
        s_c = (cx - (bx + bw / 2.0)) / (bw / 2.0)
        q = max(6, bw // 5)
        roiA, roiB = (bx, by, q, bh), (bx + bw - q, by, q, bh)
    else:
        P0, P1 = (cx, by), (cx, by + bh)                 # top -> bottom
        s_c = (cy - (by + bh / 2.0)) / (bh / 2.0)
        q = max(6, bh // 5)
        roiA, roiB = (bx, by, bw, q), (bx, by + bh - q, bw, q)

    # --- geometry vote ---
    S, Wt = _profile_cues(_profile(b, horizontal))
    S += W_CENTROID * s_c
    Wt += W_CENTROID

    # --- colour vote (tan calyx is LESS red than the body) ---
    rA, rB = _redness(img, roiA), _redness(img, roiB)
    if rA is not None and rB is not None:
        denom = abs(rA) + abs(rB) + 1.0
        s_color = (rA - rB) / denom      # + => end B less red => stem toward P1
        S += W_COLOR * s_color
        Wt += W_COLOR

    if Wt <= 0:
        return {"found": True, "ambiguous": True}

    stem_pt = P1 if S > 0 else P0
    body_pt = P0 if S > 0 else P1
    conf = min(1.0, abs(S) / Wt)
    side = "LEFT" if stem_pt[0] < body_pt[0] else "RIGHT"
    return {"found": True, "ambiguous": False, "stem_pt": stem_pt, "body_pt": body_pt,
            "stem_side": side, "confidence": conf, "rect": (bx, by, bw, bh),
            "rA": rA, "rB": rB}

# ----------------------------- MAIN LOOP --------------------------
while True:
    clock.tick()
    votes = {"LEFT": 0.0, "RIGHT": 0.0}
    last = None
    for _ in range(FRAMES_TO_VOTE):
        img = sensor.snapshot()
        r = detect_once(img)
        if r and r.get("found") and not r.get("ambiguous"):
            if r["confidence"] >= CONF_ACCEPT:
                votes[r["stem_side"]] += r["confidence"]
            last = r

    total = votes["LEFT"] + votes["RIGHT"]
    if total <= 0 or last is None:
        print("No confident chili detection.")
        continue

    stem_side = "LEFT" if votes["LEFT"] >= votes["RIGHT"] else "RIGHT"
    agreement = max(votes.values()) / total
    rotate = (stem_side != DESIRED_STEM_SIDE)

    # ---- debug overlay (tuple API: this firmware needs tuples) ----
    try:
        sp = (int(last["stem_pt"][0]), int(last["stem_pt"][1]))
        bp = (int(last["body_pt"][0]), int(last["body_pt"][1]))
        img.draw_rectangle(TRAY_ROI, color=(80, 80, 80), thickness=1)
        img.draw_rectangle(last["rect"], color=(255, 255, 0), thickness=2)
        img.draw_line((sp[0], sp[1], bp[0], bp[1]), color=(0, 255, 0), thickness=2)
        img.draw_circle((sp[0], sp[1], 9), color=(255, 0, 0), thickness=2)  # STEM
        img.draw_string(4, 4, "STEM:%s %.0f%%" % (stem_side, agreement * 100),
                        color=(255, 255, 255), scale=2)
        img.draw_string(4, 26, "ROTATE" if rotate else "OK",
                        color=(255, 255, 255), scale=2)
    except Exception as e:
        print("draw err:", e)

    ra = last["rA"] if last["rA"] is not None else 0
    rb = last["rB"] if last["rB"] is not None else 0
    print("STEM=%s conf=%.2f ROTATE=%s redL/T=%.0f redR/B=%.0f fps=%.1f"
          % (stem_side, agreement, rotate, ra, rb, clock.fps()))

    # ---- actuate the piston (uncomment + set your pin) ----
    # from pyb import Pin
    # rotate_pin = Pin('P7', Pin.OUT_PP)
    # rotate_pin.value(1 if rotate else 0)

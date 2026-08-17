# chili_stopper_factory.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 6      (bumped every time the code changes - check this first)
# ----------------------------------------------------------------------------------
#  v6  size gates loosened: only the chili's dark BODY is detected (the pale
#      stalk is not dark), so it is shorter and stubbier than a whole chili and
#      was being thrown out.  Tilt is now a tie-breaker, not a hard gate.
#  v5  tilt limit opened to 60 deg (a chili lying at an angle was being thrown
#      away before anything else ran); EMPTY now explains WHY nothing was found
#  v4  thickness became the main clue (fat end = stem), redness only a helper;
#      stopper-distance gate switched off; big answer drawn across the top
#  v3  picks the REDDEST object so it stops locking onto background and wood;
#      channel ROI narrowed to the bright metal only
#  v2  follows the chili's own axis, so any angle works; finds it by darkness
#  v1  fixed upright slices at the stopper, fixed red colour range
# ==================================================================================
# ============================ WHAT THIS DOES (simple words) ========================
# Every chili must leave the machine facing the SAME way, so the ones that come
# in the wrong way round have to be turned.  The camera looks at the chili in
# the channel and answers ONE question:
#
#            Did this chili arrive STEM first, or BODY first?
#
#   STEM arrived first   -> P0 high (3.3V), BLUE LED blinks,  screen says STEM
#   CHILLI arrived first -> P1 high (3.3V), GREEN LED blinks, screen says CHILLI
#   P2 = "rotate 180" command, high for whichever case is set in ROTATE_ON.
#   The PLC reads these and turns the pod (or leaves it) before the cutter.
#
# HOW IT DECIDES  (no colour range to set - it tunes itself to each chili)
#   It never asks "is this pixel red?".  A fixed colour range breaks the moment
#   the light changes or the chili looks brown instead of red.
#   Instead it finds the chili, works out which way it is lying, and measures
#   the REDNESS of the chili's own pixels at its TWO ENDS:
#       the stopper end is the LESS red end  -> the STEM arrived first
#       the stopper end is the REDDER end    -> the BODY arrived first
#   The stalk and calyx are always paler than the body, whatever the light is
#   doing, so this comparison holds up where fixed ranges do not.
#
# HOW IT IGNORES EVERYTHING ELSE
#   A candidate is only accepted if it really looks like a chili in the channel:
#     - inside CHANNEL_ROI            - long, not round      (MIN/MAX_ASPECT)
#     - thin, not a big dark patch    (MAX_WIDTH_PX)
#     - lying ALONG the channel       (MAX_TILT_DEG)  <- this is what stops it
#       locking onto keyboards, table edges, cables and shadows
#     - a sensible length and solid   (MIN/MAX_LEN, EXTENT_MIN)
#   If several things qualify, the most chili-like one nearest the stopper wins
#   (not simply the biggest).
#
# WHEN IT REFUSES TO ANSWER  (it never guesses)
#   EMPTY           - no chili in view
#   NOT AT STOPPER  - the chili has not reached the stopper yet
#   CANNOT TELL     - the two ends look the same, so there is nothing to judge
#
# ================================ SETTING IT UP ===================================
# STEP 1  CALIBRATE = True and DEBUG = True.  Run.  Put a chili in the channel.
#         - the magenta box must cover the channel
#         - the two small boxes must sit on the chili's two ENDS
#         - the CYAN box must be on the end touching the stopper
#         If the cyan box is on the wrong end, change STOPPER_SIDE.
# STEP 2  Two-orientation test.  Stem arriving first should print a clearly
#         POSITIVE score, body first a clearly NEGATIVE one.  If it keeps
#         saying CANNOT TELL, the ends really do look alike to the camera -
#         improve the light (less glare, more even).
# STEP 3  CALIBRATE = False and DEBUG = False, check the pins, then
#         Tools > Save open script to OpenMV Cam (as main.py), eject, reset.
#
# P0/P1/P2 give 3.3V ~25mA -> PLC input or relay module only, never a cylinder.
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED

# ------------------------------- CONFIG -------------------------------
CALIBRATE     = True     # True = numbers only, pins stay off
DEBUG         = True     # True = show the boxes; False = show only STEM/CHILLI

# The part of the picture holding the channel (x, y, width, height).
# IMPORTANT: keep this to the BRIGHT METAL CHANNEL ONLY.  Anything dark just
# outside it (wood, table, shadows) would otherwise be mistaken for a chili,
# because the chili is found by being darker than what surrounds it.
# Watch the magenta box and nudge these numbers until it hugs the channel.
CHANNEL_ROI   = (90, 0, 130, 240)
# Which edge of that box the STOPPER is on, as seen on the screen.
# CHECK ON SCREEN: the cyan box must sit on the end of the chili touching the
# stopper.  Wrong side = every answer inverted, with no error shown.
STOPPER_SIDE  = "bottom"         # "left" | "right" | "top" | "bottom"

# ---- finding the chili (darkness, adapts to the light every frame) ----
DARK_K        = 0.60     # how far below average brightness counts as chili
DARK_L_MIN    = 8        # the brightness limit is kept between these
DARK_L_MAX    = 70

# ---- what counts as a chili (these are what stop it seeing other things) ----
MIN_AREA      = 250      # smallest blob accepted, in pixels
MAX_AREA      = 30000    # largest blob accepted
MIN_ASPECT    = 1.5      # must be longish, not round.  Kept low because the
                         # pale stalk is not dark, so only the shorter, stubbier
                         # BODY of the chili is what actually gets detected.
MAX_ASPECT    = 14.0     # but not a hair-thin line
MAX_WIDTH_PX  = 60       # a chili is THIN: reject fat dark patches
MAX_TILT_DEG  = 80       # must not lie flat ACROSS the channel.  Very loose on
                         # purpose: redness is what rejects non-chili things
                         # now, and tilt only breaks ties (see the cost below).
EXTENT_MIN    = 0.18     # blob pixels / box area: rejects sparse noise
MIN_LEN       = 22       # px  <-- only the dark BODY is seen, not the pale
                         # stalk, so this must be well under the whole chili
MAX_LEN       = 320      # px
BLOB_MARGIN   = 14       # glue broken pieces of the SAME chili together

# ---- the two measuring boxes, one on each end of the chili ----
END_INSET     = 0.18     # how far in from each tip the box sits (of length)
END_BOX_MIN   = 10       # smallest / largest measuring box side, in pixels
END_BOX_MAX   = 46
MIN_BOX_OBJ   = 15       # chili pixels a box needs before it can be trusted

# ---- telling the ends apart: two clues, both RELATIVE to this chili ----
# 1) THICKNESS (main clue).  The stem end of the body is FAT and blunt; the
#    other end tapers to a narrow point.  This is shape, so glare, shadows and
#    odd lighting cannot break it.  It is why this works when colour does not.
# 2) REDNESS (helper).  The stem end is the paler end.  Used when it can be
#    read; quietly ignored when the light has washed the colour out.
W_WIDTH       = 1.6      # weight of the thickness clue
W_RED         = 1.0      # weight of the redness clue
A_FULL        = 12.0     # redness difference that counts as "totally clear"
MIN_SCORE     = 0.06     # below this the two ends really do look the same

# ---- rules ----
# The chili always stops in the same place, so there is no need to demand it
# be near the frame edge.  Set this to e.g. 60 only if you want the camera to
# ignore chilies that have not reached the stopper yet.
STOPPER_GAP_MAX_PX = 9999   # 9999 = gate switched off
DECIDE_MIN     = 0.20    # |score| needed to accept an answer
STABLE_N       = 4       # frames the same answer must repeat before locking
CLEAR_FRAMES   = 5       # empty frames before the next chili is accepted
MAX_WAIT_MS    = 2000    # if never clear by then, use the leaning answer

# ---- outputs ----
OUTPUT_MODE    = "level"  # "level" = hold while chili is there; "pulse" = trigger
PULSE_MS       = 300
ROTATE_ON      = "STEM"   # which case needs the 180 deg rotation
BLINK_MS       = 250      # LED blink speed while a result is showing

# ---- optional hardware trigger from the PLC / laser sensor ----
USE_TRIGGER    = False    # True = only look when the trigger input is high
TRIGGER_PIN    = 'P3'
TRIGGER_ACTIVE_HIGH = True

# ------------------------------- OUTPUTS ------------------------------
stem_pin = Pin('P0', Pin.OUT_PP);  stem_pin.value(0)   # STEM arrived first
pod_pin  = Pin('P1', Pin.OUT_PP);  pod_pin.value(0)    # CHILLI arrived first
rot_pin  = Pin('P2', Pin.OUT_PP);  rot_pin.value(0)    # ROTATE 180 command
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
    """Drive the pins. answer = 'STEM', 'POD' or None. Only one at a time."""
    stem_pin.value(1 if answer == "STEM" else 0)
    pod_pin.value(1 if answer == "POD" else 0)
    rot_pin.value(1 if (answer is not None and answer == ROTATE_ON) else 0)

def service_leds(answer):
    """BLUE blinks for STEM, GREEN blinks for CHILLI, both dark when idle."""
    on = (time.ticks_ms() // BLINK_MS) % 2 == 0
    led_blue.on()  if (answer == "STEM" and on) else led_blue.off()
    led_green.on() if (answer == "POD" and on)  else led_green.off()

# ------------------------------- SENSOR -------------------------------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)          # 320x240
sensor.skip_frames(time=2000)
sensor.set_auto_gain(False)                # LOCK: colour must not drift
sensor.set_auto_whitebal(False)
clock = time.clock()

# ------------------------------- HELPERS ------------------------------
def _get(obj, name, *args):
    """Method-or-property safe accessor (firmware APIs vary)."""
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def _stat(st, name, default=0.0):
    try:
        return float(_get(st, name))
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

def clamp_roi(x, y, w, h):
    """Clip a window to the 320x240 frame."""
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(320, int(x + w)), min(240, int(y + h))
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))

def count_px(img, roi, thrs):
    """How many pixels in roi match any of the given colour ranges."""
    if roi[2] < 2 or roi[3] < 2:
        return 0
    try:
        bs = img.find_blobs(thrs, roi=roi, pixels_threshold=4,
                            area_threshold=4, merge=True)
        return sum(_get(x, "pixels") for x in bs)
    except Exception:
        return 0

def region_redness(img, roi, obj_thrs):
    """Average redness of the CHILI PIXELS inside one measuring box.
    Passing the chili threshold leaves the bright background out, so the
    number describes the chili and not the channel.  None if unreadable."""
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(thresholds=obj_thrs, roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        pass
    try:                                   # firmware without 'thresholds'
        st = img.get_statistics(roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        return None

def object_threshold(img):
    """Brightness range that separates the chili from the channel, worked out
    fresh from this frame so it copes with the light changing."""
    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0
    lim = l_mean - DARK_K * l_std
    lim = min(max(lim, DARK_L_MIN), DARK_L_MAX)
    return [(0, int(lim), -128, 127, -128, 127)], int(lim)

def _dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)

def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

def axis_ends(b):
    """The two ENDS of the chili's long axis, plus its width.
    Uses the rotated bounding box, so a tilted chili is handled properly."""
    try:
        c0, c1, c2, c3 = _get(b, "min_corners")
        e01, e12 = _dist(c0, c1), _dist(c1, c2)
        if e01 >= e12:                     # c0-c1 is a long edge
            return _mid(c1, c2), _mid(c3, c0), e12
        return _mid(c0, c1), _mid(c2, c3), e01
    except Exception:
        pass
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    if bw >= bh:
        return (bx, by + bh / 2.0), (bx + bw, by + bh / 2.0), bh
    return (bx + bw / 2.0, by), (bx + bw / 2.0, by + bh), bw

def tilt_deg(E0, E1):
    """How far the chili is from lying along the channel, in degrees."""
    dx, dy = abs(E1[0] - E0[0]), abs(E1[1] - E0[1])
    if STOPPER_SIDE in ("top", "bottom"):      # channel runs up-and-down
        return math.degrees(math.atan2(dx, dy + 0.001))
    return math.degrees(math.atan2(dy, dx + 0.001))   # channel runs across

def pick_stopper_end(E0, E1):
    """Whichever end is nearer the stopper edge, plus its distance to it."""
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
    near, far = (E0, E1) if E0[1] >= E1[1] else (E1, E0)   # "bottom"
    return near, far, (y + h) - near[1]

def shape_ok(b):
    """Cheap checks first: size, how long, how thin, how solid."""
    bw, bh, px = _get(b, "w"), _get(b, "h"), _get(b, "pixels")
    if px > MAX_AREA:
        return False
    length, width = max(bw, bh), max(1, min(bw, bh))
    if width > MAX_WIDTH_PX:               # fat dark patch, not a chili
        return False
    if not (MIN_ASPECT <= length / width <= MAX_ASPECT):
        return False
    if not (MIN_LEN <= length <= MAX_LEN):
        return False
    if px / float(bw * bh) < EXTENT_MIN:
        return False
    return True

# why nothing was found - filled in every scan so "EMPTY" can explain itself
scan = {"raw": 0, "shape": 0, "best_tilt": -1}

def find_chili(img, obj_thrs):
    """The most chili-like object lying in the channel, nearest the stopper.
    Returns (E_stop, E_far, width, dist, rect, tilt, red) or None."""
    kw = {"roi": CHANNEL_ROI, "pixels_threshold": MIN_AREA,
          "area_threshold": MIN_AREA, "merge": True, "margin": BLOB_MARGIN}
    try:
        blobs = img.find_blobs(obj_thrs, **kw)
    except TypeError:                      # firmware without 'margin'
        kw.pop("margin")
        blobs = img.find_blobs(obj_thrs, **kw)

    scan["raw"], scan["shape"], scan["best_tilt"] = len(blobs), 0, -1
    best, best_cost = None, None
    for b in blobs:
        if not shape_ok(b):
            continue
        scan["shape"] += 1
        E0, E1, width = axis_ends(b)
        tilt = tilt_deg(E0, E1)
        if scan["best_tilt"] < 0 or tilt < scan["best_tilt"]:
            scan["best_tilt"] = int(tilt)
        if tilt > MAX_TILT_DEG:            # lying across the channel
            continue
        E_stop, E_far, dist = pick_stopper_end(E0, E1)
        rect = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))

        # A CHILI IS THE REDDEST THING IN THE CHANNEL.  Grey background
        # streaks, shadows and table edges have almost no redness, so this is
        # what stops the camera locking onto them.  It is still relative - we
        # simply take the reddest candidate, with no fixed colour range.
        red = region_redness(img, rect, obj_thrs)
        if red is None:
            red = -50.0
        # lower cost wins: mostly redness, then straightness, then nearness
        cost = -red + 0.25 * tilt + 0.05 * max(0, dist)
        if best_cost is None or cost < best_cost:
            best = (E_stop, E_far, width, dist, rect, tilt, red)
            best_cost = cost
    return best

def end_boxes(E_stop, E_far, width):
    """One measuring box on each END of the chili, set in a little from the
    very tips so background does not bleed into the reading."""
    side = min(max(width * 1.3, END_BOX_MIN), END_BOX_MAX)
    dx, dy = E_far[0] - E_stop[0], E_far[1] - E_stop[1]
    near = (E_stop[0] + END_INSET * dx, E_stop[1] + END_INSET * dy)
    far = (E_far[0] - END_INSET * dx, E_far[1] - END_INSET * dy)
    return (clamp_roi(near[0] - side/2.0, near[1] - side/2.0, side, side),
            clamp_roi(far[0] - side/2.0, far[1] - side/2.0, side, side))

def look(img, obj_thrs):
    """Read the scene once.  Returns a dict:
        reason : 'ok' | 'empty' | 'not_at_stopper' | 'no_read' | 'no_contrast'
        score  : > 0 STEM arrived first, < 0 CHILLI (body) arrived first
    """
    out = {"reason": "empty", "score": 0.0, "a_near": None, "a_far": None,
           "spread": 0.0, "boxes": [], "rect": None, "E_stop": None,
           "E_far": None, "dist": -1, "tilt": -1, "red": 0.0,
           "o_near": 0, "o_far": 0, "s_width": 0.0, "s_red": 0.0}

    found = find_chili(img, obj_thrs)
    if found is None:
        return out
    E_stop, E_far, width, dist, rect, tilt, red = found
    out["E_stop"], out["E_far"] = E_stop, E_far
    out["dist"], out["rect"], out["tilt"], out["red"] = dist, rect, tilt, red

    boxes = end_boxes(E_stop, E_far, width)
    out["boxes"] = list(boxes)

    # the chili has to actually be AT the stopper
    if dist > STOPPER_GAP_MAX_PX:
        out["reason"] = "not_at_stopper"
        return out

    # how much chili is in each end box = how THICK the chili is there
    o_near = count_px(img, boxes[0], obj_thrs)
    o_far = count_px(img, boxes[1], obj_thrs)
    out["o_near"], out["o_far"] = o_near, o_far
    if o_near + o_far < MIN_BOX_OBJ:
        out["reason"] = "no_read"          # boxes are not on the chili at all
        return out

    # clue 1: THICKNESS.  Fat blunt end = stem, narrow pointed end = tip.
    s_width = (o_near - o_far) / float(o_near + o_far)

    # clue 2: REDNESS.  The stem end is the paler one.  Skipped if unreadable.
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

    # both clues point the same way: positive = STEM arrived first
    score = (W_WIDTH * s_width + rw * s_red) / (W_WIDTH + rw)
    out["s_width"], out["s_red"] = s_width, s_red
    out["score"] = score

    if abs(score) < MIN_SCORE:
        out["reason"] = "no_contrast"      # ends alike: say so, don't guess
        return out
    out["reason"] = "ok"
    return out

# what the two answers are called on screen / in the log
NAME = {"STEM": "STEM", "POD": "CHILLI"}
REASON_TEXT = {"empty": "EMPTY", "not_at_stopper": "NOT AT STOPPER",
               "no_read": "CANNOT SEE CHILI CLEARLY",
               "no_contrast": "CANNOT TELL - ENDS LOOK THE SAME"}

def draw_scene(img, r, label=None, col=(255, 255, 255), status=None,
               state_name="", total=0, fps=0.0):
    """Screen layout:
         line 1  STATE: <what it is doing>
         line 2  BIG WORD  -  STEM -> P0   or   CHILLI -> P1
         a box around the chili it locked onto, and an arrow along it
         bottom  FPS and how many chilies have been decided
       DEBUG adds the channel box and the two measuring boxes."""
    # --- the chili it is actually looking at ---
    if r["rect"]:
        draw_safe(img.draw_rectangle, (r["rect"],), r["rect"],
                  color=col if label else (160, 160, 160), thickness=2)

    if DEBUG:
        draw_safe(img.draw_rectangle, (CHANNEL_ROI,), CHANNEL_ROI,
                  color=(255, 0, 255), thickness=1)
        for i, bx in enumerate(r["boxes"]):
            c = (0, 255, 255) if i == 0 else (140, 140, 140)   # cyan = stopper
            draw_safe(img.draw_rectangle, (bx,), bx, color=c, thickness=2)

    # --- arrow along the chili, pointing at the end that arrived first ---
    if label and r["E_stop"] and r["E_far"]:
        sx, sy = int(r["E_stop"][0]), int(r["E_stop"][1])
        fx, fy = int(r["E_far"][0]), int(r["E_far"][1])
        draw_safe(img.draw_line, ((fx, fy, sx, sy),), (fx, fy, sx, sy),
                  color=col, thickness=2)
        dx, dy = sx - fx, sy - fy
        L = math.sqrt(dx*dx + dy*dy) or 1.0
        ux, uy = dx / L, dy / L
        px, py = -uy, ux
        for s in (1, -1):
            hx = int(sx - 14*ux + s*8*px)
            hy = int(sy - 14*uy + s*8*py)
            draw_safe(img.draw_line, ((hx, hy, sx, sy),), (hx, hy, sx, sy),
                      color=col, thickness=2)

    # --- text: state, then the big answer ---
    if state_name:
        draw_safe(img.draw_string, ((4, 2, "STATE: " + state_name),),
                  (4, 2, "STATE: " + state_name), color=(200, 200, 200),
                  scale=1)
    if label:
        # BIG answer across the top of the picture, roughly centred
        tw = 24 * len(label)               # scale-4 text is about 24px a letter
        tx = max(2, (320 - tw) // 2)
        draw_safe(img.draw_string, ((tx, 14, label),), (tx, 14, label),
                  color=col, scale=4)
    elif status:
        draw_safe(img.draw_string, ((4, 16, status),), (4, 16, status),
                  color=(255, 255, 0), scale=1)

    # --- counters along the bottom ---
    draw_safe(img.draw_string, ((4, 224, "FPS %d  |  TOTAL %d" % (fps, total)),),
              (4, 224, "FPS %d  |  TOTAL %d" % (fps, total)),
              color=(200, 200, 200), scale=1)

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
total = 0                                  # how many chilies decided so far

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
        set_outputs(None)
        live = ("STEM" if score > 0 else "POD") if present else None
        service_leds(live)
        if live:
            col = (0, 150, 255) if live == "STEM" else (0, 255, 0)
            lbl = "%s -> %s" % (NAME[live], "P0" if live == "STEM" else "P1")
            draw_scene(img, r, lbl, col, None, "CALIBRATE", total, clock.fps())
        else:
            draw_scene(img, r, None, (255, 255, 255),
                       REASON_TEXT.get(r["reason"], "EMPTY"),
                       "CALIBRATE", total, clock.fps())
        if r["reason"] == "empty":
            # explain WHY nothing was found instead of just saying EMPTY
            print("CALIB EMPTY  blobs=%d shape_ok=%d best_tilt=%d "
                  "(limit %d) L<=%d fps=%.0f"
                  % (scan["raw"], scan["shape"], scan["best_tilt"],
                     MAX_TILT_DEG, lim, clock.fps()))
        else:
            print("CALIB %-24s score=%+.2f | thick %d vs %d (%+.2f) | "
                  "red %+.2f | tilt=%d fps=%.0f"
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
                print(">>> %s ARRIVED FIRST -> %s HIGH (3.3V)  ==> %s   "
                      "(score=%+.2f spread=%+.1f)"
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
            state = LOCKED                 # it was only a dropped frame
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
        lbl = "%s -> %s" % (NAME[final], "P0" if final == "STEM" else "P1")
        draw_scene(img, r, lbl, col, None, sname, total, clock.fps())
        service_leds(final)
    elif state == CHECK:
        draw_scene(img, r, None, (255, 255, 0), "CHECKING...", sname,
                   total, clock.fps())
        service_leds(None)
    else:
        draw_scene(img, r, None, (255, 255, 255),
                   REASON_TEXT.get(r["reason"], "WAITING"), sname,
                   total, clock.fps())
        service_leds(None)

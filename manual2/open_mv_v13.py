# open_mv2.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 13     (bumped every time the code changes - check this first)
#  Successor to chili_stopper_factory.py.
# ----------------------------------------------------------------------------------
#  v13 THE CAMERA NOW FINDS THE CHANNEL BY ITSELF (AUTO_CHANNEL).
#      Hand-measuring the box has caused most of the wrong answers.  If it is
#      not exactly on the metal channel it takes in the mat or the table, and
#      those are DARKER than the bright channel - so the camera locked onto
#      the mat and ignored the chili sitting right next to it.
#      The channel is simply the brightest large thing in view, and the chili
#      is the dark thing lying in it.  So the camera looks for the bright
#      strip first, then searches for the chili only inside it.  No box to
#      measure, and it follows the channel if the camera is nudged.
#      Set AUTO_CHANNEL = False to go back to the fixed CHANNEL_ROI.
# ----------------------------------------------------------------------------------
#  v12 CHANNEL_ROI moved to the MIDDLE of the picture, (90, 60, 140, 120).
#      It was a narrow strip at the right-hand edge, and the chili was being
#      placed in the middle - outside it.  Everything outside the box is
#      ignored, so the camera was reading an empty strip and the answers were
#      meaningless.  If the chili lies LEFT-TO-RIGHT rather than up-and-down,
#      STOPPER_SIDE must also change to "left" or "right".
# ----------------------------------------------------------------------------------
#  v11 FIXED A BIAS THAT PUSHED NEARLY EVERY ANSWER TO "STEM".
#      The stalk check looked 22 pixels BEYOND the stopper end for pale
#      material.  But just beyond that end sits the physical stopper bar, and
#      that hardware is dark - so the check found "stalk" there on EVERY chili,
#      whichever way round it was, and reported stalk=+1 -> STEM.
#      Three chillies fed in different orientations all came out STEM
#      (+0.25, +0.84, +0.44) because of this.
#      Every measuring box is now clipped to CHANNEL_ROI, so nothing outside
#      the channel can be mistaken for part of the chili.  Where the stopper
#      end leaves no room to look, the stalk clue says nothing instead of
#      inventing evidence.
# ----------------------------------------------------------------------------------
#  v10 MANUAL / AUTOMATIC threshold switch - see MANUAL_L in the config.
#      AUTO   : the dividing line between "dark = chili" and "bright = channel"
#               is measured from every frame, so it follows the lighting.  Good
#               while the lighting is still being set up.
#      MANUAL : the line is a fixed number you type in.  The same picture always
#               gives the same answer, which is what a production machine needs
#               and what can actually be tested and signed off.
#      The line in use is now shown on screen as "L<=NN AUTO" or "L<=NN SET",
#      so you can read the number AUTO settles on and copy it into MANUAL_L.
# ----------------------------------------------------------------------------------
#  v9  THE ANSWER AND THE NUMBER CAN NO LONGER DISAGREE.
#      The log was printing "STEM ARRIVED FIRST ... (score=-0.37)" - a negative
#      score with a STEM answer.  Smoothing was applied to the LABEL over 5
#      frames while the number shown was this frame's raw value, so the two
#      drifted apart and the readout could not be trusted.
#      Now the SCORE itself is averaged over those frames and the answer is
#      simply its sign, so what you read is what was decided.
# ----------------------------------------------------------------------------------
#  v8  COLOUR NO LONGER DECIDES WHETHER SOMETHING IS A CHILI.
#      A pink cloth reads redness 20-40; a dark dried chili reads 4-8.  The
#      cloth is REDDER than the chili, so no redness threshold can separate
#      them - which is why raising it made a towel score +0.80 while a real
#      chili in the chute read EMPTY.
#      Presence is now judged by BRIGHTNESS SPREAD: an empty metal chute is
#      uniformly bright, anything lying in it breaks that up.  Colour is still
#      read, but only to break ties between candidates - never to reject one.
#
#  ####  LIGHTING - THIS MATTERS MORE THAN ANY SETTING BELOW  ####
#      Aim a DIFFUSED white light at the chute, OFF TO ONE SIDE so its
#      reflection does not bounce straight back into the lens.  Bounce it off
#      white card or tape baking paper over it.  You want: chute evenly bright,
#      chili clearly dark, NO bright glare stripe, NO hard shadow beside the
#      chili.  A shadow merges into the chili and makes it look fat at the
#      wrong end - which corrupts the main clue.
# ----------------------------------------------------------------------------------
#  v7  ACCURACY FIXES
#      - measuring boxes were being CLIPPED at the frame edge.  The stopper end
#        is always at the edge, so its box was smaller and always counted fewer
#        pixels: every decision was quietly biased toward APEX.  All comparisons
#        now use DENSITY (pixels per area), so box size cannot skew the answer.
#      - the stalk check had the same clipping bias, and used a FIXED brightness
#        range that breaks when the light changes.  It now uses density and a
#        limit derived from the frame, like the main detector.
#      - CALIBRATE no longer drives the output pins (it was firing the cylinders
#        while you were still tuning)
#      - vote smoothing now runs in PRODUCTION too, not only in calibrate
#      - when the stalk and thickness clues DISAGREE the score is halved, so a
#        confused chili needs more evidence before it can lock
#      - "empty channel" is judged by counting red pixels, not by the single
#        brightest pixel (one speck of noise used to defeat it)
#  v6  on-screen HUD, calibrated channel ROI, colour check to reject bare metal
#  v5  tilt limit opened; EMPTY explains why nothing was found
#  v4  thickness became the main clue; stopper-distance gate off
#  v3  picks the reddest object so it stops locking onto background
#  v2  follows the chili's own axis, so any angle works; finds it by darkness
#  v1  fixed upright slices at the stopper, fixed red colour range
# ==================================================================================
#
#  WHAT THIS DOES
#    Chillies slide down the chute and stop against the stopper.  The camera
#    answers one question - did this chili arrive STEM first or APEX (tip)
#    first? - and signals the PLC, which rotates the pod 180 degrees or leaves
#    it, so every chili reaches the cutter facing the same way.
#
#      STEM at stopper -> P0 high (3.3V), BLUE LED,  screen says STEM
#      APEX at stopper -> P1 high (3.3V), GREEN LED, screen says APEX
#      P2 = rotate 180 command, for whichever case is set in ROTATE_ON
#
#  HOW IT DECIDES - three clues, all RELATIVE, none using a fixed colour range
#    1) STALK   pale stalk sticking out beyond one end = that end is the stem.
#               Strongest clue when the stalk is visible.
#    2) WIDTH   the stem end of the body is fat and blunt; the apex tapers.
#    3) REDNESS the stem end is the paler end.
#    They must agree; if the stalk and width clues contradict each other the
#    score is halved so the answer needs more frames before it locks.
#
#  P0/P1/P2 give 3.3V ~25mA -> PLC input or relay module only, never a cylinder.
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED


# ------------------------------- CONFIG -------------------------------
CALIBRATE     = False    # True = tuning mode: pins stay OFF, numbers printed
DEBUG         = True     # True = show detection boxes

# The part of the picture the camera examines.  Everything outside it is
# ignored completely, so THE CHILI MUST LIE INSIDE THIS BOX or nothing works.
# It is drawn on screen in MAGENTA.
#   (x, y, width, height)   picture is 320 wide, 240 tall
# Now set to the MIDDLE of the view: x 90-230, y 60-180.
CHANNEL_ROI   = (90, 60, 140, 120)

# AUTO_CHANNEL: find the bright metal channel by itself, every frame.
# The channel is the brightest thing in view; the chili is the dark thing
# lying in it.  So the camera looks for the bright strip first and searches
# for the chili only inside it.  This removes the hand-measured box that has
# been the cause of most wrong answers - if the box is not exactly on the
# channel it locks onto the mat or the table instead, which are also darker
# than the channel.
# Set to False to go back to the fixed CHANNEL_ROI above.
AUTO_CHANNEL  = True
CH_MIN_PIX    = 600      # a bright strip smaller than this is not the channel
CH_INSET      = 2        # trim this many pixels off the found strip, so the
                         # bright edge of the channel is not counted

# Which edge of that box the stopper is on.
#   chili lies UP-AND-DOWN in the picture -> "top" or "bottom"
#   chili lies LEFT-TO-RIGHT             -> "left" or "right"
# Get this wrong and every answer comes out backwards, with no error shown.
# CHECK ON SCREEN: the CYAN box must sit on the end touching the stopper.
STOPPER_SIDE  = "bottom"

# ---- finding the chili: DARKNESS ONLY, never colour ----
# Colour cannot answer "is this a chili".  A pink cloth reads A = 20-40 while a
# dark dried chili reads A = 4-8, so ANY redness threshold that accepts real
# chilies also accepts brighter-coloured things, and any threshold that rejects
# them also rejects half the crop.  What is reliable: an EMPTY metal channel is
# uniformly bright, and a chili is a DARK region in it.  That holds for red,
# brown and almost-black chilies equally.
# ===================== THE ONE NUMBER TO ADJUST =======================
# Brightness runs 0 (black) to 100 (white).  The channel metal is bright,
# a chili is dark.  This is the dividing line between them:
#     anything DARKER than the line = chili;  brighter = channel.
#
#   MANUAL_L = None   -> AUTOMATIC.  The camera measures the line itself from
#                        every frame, so it follows the lighting on its own.
#                        Use this while the lighting is still being set up.
#
#   MANUAL_L = 45     -> MANUAL.  The line is fixed at 45 and never moves.
#                        Same picture always gives the same answer.  Use this
#                        in production, once the light is fixed and enclosed.
#
# HOW TO FIND YOUR NUMBER: run in AUTO with a chili in the channel and read
# "L<=NN" on the screen.  That NN is what automatic is choosing.  Put that
# number here, switch to manual, and check it still works.
#   Chili not being seen  -> RAISE the number (more counts as dark)
#   Shadows being counted -> LOWER the number (less counts as dark)
MANUAL_L      = None

DARK_K        = 0.60     # AUTO only: how far below average counts as dark
DARK_L_MIN    = 8        # AUTO only: guard rails - the automatic line is
DARK_L_MAX    = 70       # never allowed outside these
MIN_CHILI_STD = 6.0      # brightness spread inside the channel.  Bare metal is
                         # uniform (std < 6); anything lying in it breaks that
                         # up.  This is the presence test - no colour involved.

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
BLOB_MARGIN   = 14

# ---- measuring boxes on both ends ----
END_INSET     = 0.18
END_BOX_MIN   = 8
END_BOX_MAX   = 46
MIN_BOX_OBJ   = 10
MIN_BOX_AREA  = 40       # a box smaller than this (clipped by the frame edge)
                         # is not trustworthy and is reported instead of used

# ---- stalk check ----
STALK_REACH   = 22       # how far beyond each end to look, in pixels
STALK_BOX     = 24       # size of the box it looks in
STALK_L_MARGIN = 22      # stalk is darker than metal but paler than the body:
                         # allowed up to (body limit + this), worked out per frame
STALK_MIN_DENS = 0.035   # least stalk density that counts as "something there"
STALK_RATIO   = 1.5      # one side must beat the other by this much

# ---- decision weights ----
W_STALK       = 0.70     # share of the score given to the stalk clue when seen
W_WIDTH       = 1.6
W_RED         = 1.0
A_FULL        = 12.0
MIN_SCORE     = 0.05
DISAGREE_MULT = 0.5      # stalk and width clues contradict -> halve confidence

# ---- rules ----
STOPPER_GAP_MAX_PX = 9999
DECIDE_MIN     = 0.15
STABLE_N       = 3               # frames the answer must repeat (~75ms)
CLEAR_FRAMES   = 4               # empty frames before the next chili
MAX_WAIT_MS    = 1500
VOTE_HISTORY_MAX = 5             # frames in the smoothing window

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
    """Drive the output pins (P0, P1, P2).  Only ever one of P0/P1 at a time."""
    stem_pin.value(1 if answer == "STEM" else 0)
    pod_pin.value(1 if answer == "POD" else 0)
    rot_pin.value(1 if (answer is not None and answer == ROTATE_ON) else 0)

def service_leds(answer):
    """Blue for STEM, green for APEX.  Blinks while tuning, steady in production."""
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
sensor.set_auto_gain(False)                # lock exposure & colour
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
    """Matching pixels per unit area.
    Boxes at the frame edge get CLIPPED, so a raw count from a small box loses
    against a full-size one.  The stopper end sits at the edge by definition,
    so raw counts biased every decision.  Density removes that completely."""
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

def find_channel(img):
    """Locate the bright metal channel in the picture.

    The channel is the brightest large object in view.  Finding it each frame
    means the camera does not depend on someone measuring a box by hand and
    typing coordinates in - and it follows the channel if the camera is
    nudged.  Returns a box, or None if no convincing bright strip is found."""
    try:
        st = img.get_statistics()
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0

    # "bright" = clearly above the average of the whole picture
    lim = min(95, max(45, l_mean + 0.7 * l_std))
    thrs = [(int(lim), 100, -128, 127, -128, 127)]
    try:
        blobs = img.find_blobs(thrs, pixels_threshold=CH_MIN_PIX,
                               area_threshold=CH_MIN_PIX, merge=True)
    except Exception:
        return None

    best, best_px = None, 0
    for b in blobs:
        bw, bh, px = _get(b, "w"), _get(b, "h"), _get(b, "pixels")
        if bw < 10 or bh < 10:
            continue
        if px > best_px:                   # the biggest bright region wins
            best_px = px
            best = (_get(b, "x"), _get(b, "y"), bw, bh)
    if best is None:
        return None
    x, y, w, h = best
    return clamp_roi(x + CH_INSET, y + CH_INSET,
                     w - 2 * CH_INSET, h - 2 * CH_INSET)

def object_threshold(img):
    """Work out the dividing line between 'chili' (dark) and 'channel' (bright),
    and say whether anything is in the channel at all.

    MANUAL mode : the line is the fixed number you typed in.  Same picture
                  always gives the same answer - what a production machine wants.
    AUTO mode   : the line is measured from this frame, so it follows the light.
                  Good while the lighting is still being sorted out."""
    # ---------------- MANUAL: fixed line, fully predictable ----------------
    if MANUAL_L is not None:
        lim = int(min(max(MANUAL_L, 0), 100))
        thrs = [(0, lim, -128, 127, -128, 127)]
        # "is a chili here?" = enough dots darker than the line.  Deterministic,
        # unlike the automatic test, which depends on how the frame looks.
        if count_px(img, CHANNEL_ROI, thrs) < MIN_AREA:
            return None, lim               # nothing dark enough: channel empty
        return thrs, lim

    # ---------------- AUTO: line measured from this frame ------------------
    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0

    # Is anything lying in the channel?  An empty metal chute is uniformly
    # bright, so its brightness spread is small.  Anything in it breaks that up.
    # No colour is used, so a dark or brown chili is found just as well as a
    # bright red one - which a redness test could never do.
    if l_std < MIN_CHILI_STD:
        return None, 0                     # empty bare channel

    lim = l_mean - DARK_K * l_std
    lim = min(max(lim, DARK_L_MIN), DARK_L_MAX)
    return [(0, int(lim), -128, 127, -128, 127)], int(lim)

def stalk_thresholds(lim):
    """The stalk is darker than the bright metal but paler than the red body.
    Derived from the same frame statistics as the body limit, so it follows the
    light instead of being a fixed number that drifts out of range."""
    hi = min(100, int(lim) + STALK_L_MARGIN)
    return [(0, hi, -128, 127, -128, 127), (0, 95, 8, 127, 8, 127)]

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

# why nothing was found - each counter is a separate reason, so the log says
# exactly which test threw the chili away
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
        scan["shape"] += 1                 # passed the shape tests

        rect = (_get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h"))
        # Redness is READ but never used to reject: it only breaks ties between
        # candidates.  Rejecting on colour is what made a pink cloth pass while
        # a dark chili was thrown away.
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
            best = (E_stop, E_far, width, dist, rect, tilt, red)
            best_cost = cost
    return best

def clip_to_channel(roi):
    """Trim a measuring box so it cannot reach outside the channel.

    This matters most at the STOPPER end, because just beyond it sits the
    physical stopper bar.  That hardware is dark, so a box allowed to reach
    past the end found "chili-like" material there on EVERY chili, whichever
    way round it was - which pushed every answer toward STEM."""
    cx, cy, cw, ch = CHANNEL_ROI
    x0 = max(roi[0], cx)
    y0 = max(roi[1], cy)
    x1 = min(roi[0] + roi[2], cx + cw)
    y1 = min(roi[1] + roi[3], cy + ch)
    return (x0, y0, max(0, x1 - x0), max(0, y1 - y0))

def end_boxes(E_stop, E_far, width):
    side = min(max(width * 1.3, END_BOX_MIN), END_BOX_MAX)
    dx, dy = E_far[0] - E_stop[0], E_far[1] - E_stop[1]
    near = (E_stop[0] + END_INSET * dx, E_stop[1] + END_INSET * dy)
    far = (E_far[0] - END_INSET * dx, E_far[1] - END_INSET * dy)
    return (clip_to_channel(clamp_roi(near[0] - side/2.0, near[1] - side/2.0,
                                     side, side)),
            clip_to_channel(clamp_roi(far[0] - side/2.0, far[1] - side/2.0,
                                      side, side)))

def check_stalk(img, E_stop, E_far, lim):
    """Is a pale stalk sticking out beyond one end of the body?
    Compares DENSITY, not raw counts: the box beyond the stopper end is often
    clipped by the frame edge, and comparing raw counts made the clipped side
    lose every time."""
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

    thrs = stalk_thresholds(lim)
    d_near = density(img, roi_near, thrs)
    d_far = density(img, roi_far, thrs)
    if d_near is None or d_far is None:
        # One side has no room left inside the channel - usually the stopper
        # end, hard against the bar.  With only one side readable there is
        # nothing to compare, so the stalk clue says nothing rather than
        # inventing a "stalk" out of the stopper hardware.
        return 0.0

    if d_near >= STALK_MIN_DENS and d_near > d_far * STALK_RATIO:
        return 1.0                         # stalk toward the stopper -> STEM
    if d_far >= STALK_MIN_DENS and d_far > d_near * STALK_RATIO:
        return -1.0                        # stalk at the far end -> APEX
    return 0.0

def look(img, obj_thrs, lim):
    out = {"reason": "empty", "score": 0.0, "a_near": None, "a_far": None,
           "spread": 0.0, "boxes": [], "rect": None, "E_stop": None,
           "E_far": None, "dist": -1, "tilt": -1, "red": 0.0,
           "d_near": 0.0, "d_far": 0.0, "s_width": 0.0, "s_red": 0.0,
           "s_stalk": 0.0, "agree": True}

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

    # THICKNESS by density, so a box clipped at the frame edge cannot skew it
    d_near = density(img, boxes[0], obj_thrs)
    d_far = density(img, boxes[1], obj_thrs)
    if d_near is None or d_far is None or (d_near + d_far) <= 0:
        out["reason"] = "no_read"
        return out
    out["d_near"], out["d_far"] = d_near, d_far
    s_width = (d_near - d_far) / (d_near + d_far)

    # REDNESS: the stem end is the paler end
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

    # STALK sticking out past one end - the strongest clue when it is visible
    s_stalk = check_stalk(img, E_stop, E_far, lim)
    out["s_stalk"] = s_stalk

    body = (W_WIDTH * s_width + rw * s_red) / (W_WIDTH + rw)
    if s_stalk != 0.0:
        score = W_STALK * s_stalk + (1.0 - W_STALK) * body
        # if the stalk says one end and the body shape says the other, this
        # chili is confusing - halve the score so it needs more frames to lock
        if s_width != 0.0 and (s_stalk > 0) != (s_width > 0):
            score *= DISAGREE_MULT
            out["agree"] = False
    else:
        score = body

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
    '(': (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02),
    ')': (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    ' ': (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
}

def draw_str(img, x, y, text, color=(255, 255, 255), scale=2):
    """Draw text, trying the firmware's own call first and falling back to a
    hand-drawn font if this build refuses both signatures."""
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
    """On-screen HUD: what is at the stopper, and which pin is being driven.
    shown_score: once an answer is LOCKED, pass the score it was locked on.
    Showing the live score there made the HUD contradict itself - the label
    said STEM while the number underneath had already drifted negative."""
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

    # arrow along the chili, pointing at the end that arrived first
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

    # The dividing line is always shown.  In AUTO this is the number to write
    # down and copy into MANUAL_L; in MANUAL it confirms your number is in use.
    mode = "SET" if MANUAL_L is not None else "AUTO"
    tail = "L<=%d %s | %d FPS" % (shown_lim, mode, int(fps))

    if shown_score is not None:            # a locked answer: show ITS score
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
final_score = 0.0                # the score the locked answer was decided on
empty = 0
pulse_until = 0
total = 0

vote_history = []

def smooth_score(s):
    """Average of the last few frames' SCORES.

    Earlier this smoothed the LABEL instead, which let the shown number and the
    shown answer contradict each other - the log printed
    'STEM ... (score=-0.37)', because the 5-frame majority still said STEM
    while this frame's number had gone negative.  Averaging the score itself
    means the answer is always the sign of the number you are looking at."""
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

    # Find the bright channel first, and look for the chili only inside it.
    # Assigning CHANNEL_ROI here updates it for every function below.
    if AUTO_CHANNEL:
        found_ch = find_channel(img)
        if found_ch is not None and found_ch[2] > 8 and found_ch[3] > 8:
            CHANNEL_ROI = found_ch

    obj_thrs, lim = object_threshold(img)
    r = look(img, obj_thrs, lim)
    present = (r["reason"] == "ok")
    if not triggered():
        present = False
    score = r["score"]

    # smoothed answer, used by BOTH modes
    # ONE number drives everything: the smoothed score.  The answer is simply
    # its sign, so the label on screen can never disagree with the number.
    avg = smooth_score(score if present else None)
    if avg is None:
        live = None
    else:
        live = "STEM" if avg > 0 else "POD"
        score = avg                        # show and decide on the same value

    # ---------------------------- CALIBRATE ---------------------------
    if CALIBRATE:
        set_outputs(None)                  # pins stay OFF while tuning
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
            print("CALIB %-24s score=%+.2f | dens %.3f vs %.3f (%+.2f) | "
                  "red %+.2f | stalk %+.0f%s | fps=%.0f"
                  % (REASON_TEXT.get(r["reason"], "OK"), score,
                     r["d_near"], r["d_far"], r["s_width"], r["s_red"],
                     r["s_stalk"], "" if r["agree"] else " DISAGREE",
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
            answer = live            # sign of the same score shown on screen
            if abs(score) >= DECIDE_MIN:
                if answer == hold_answer:
                    hold_n += 1
                else:
                    hold_answer, hold_n = answer, 1
            elapsed = time.ticks_diff(now, t_state)
            if hold_n >= STABLE_N or (elapsed >= MAX_WAIT_MS and hold_answer):
                final = hold_answer
                final_score = score        # remember what we decided on
                set_outputs(final)
                total += 1
                pulse_until = time.ticks_add(now, PULSE_MS)
                state, t_state = LOCKED, now
                print(">>> %s ARRIVED FIRST -> %s HIGH (3.3V)  ==> %s   "
                      "(score=%+.2f stalk=%+.0f%s)"
                      % (NAME[final], "P0" if final == "STEM" else "P1",
                         "ROTATE 180 (P2 HIGH)" if final == ROTATE_ON
                         else "NO ROTATE", score, r["s_stalk"],
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
                reset_votes()              # next chili starts with a clean slate
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

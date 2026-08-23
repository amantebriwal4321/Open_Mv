# open_mv2.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 19     (bumped every time the code changes - check this first)
# ----------------------------------------------------------------------------------
#  v19  REMOVE THE EMPTY-CHANNEL FLOOR, AND SAY WHEN THE STOPPER SIDE IS WRONG.
#
#  Seen on the machine: a stem-first chilli locked APEX five times running, with
#  taper stuck negative (-0.26, -0.70, -0.64, -0.57) and the green body box
#  covering the WHOLE channel even though the pod filled only the top third.
#
#  Both symptoms have one cause. CHANNEL_ROI is a little wider than the bright
#  chute, so it catches the dark rails down each side. Those rails sit in EVERY
#  band, so every band looks partly full: the pod appears to fill the channel,
#  `lo` is always 0 so the "has it reached the stopper" check can never fire,
#  and taper ends up comparing two lengths of rail with some chilli in one of
#  them. Confident answers, almost unrelated to the chilli.
#
#  1. Every band now has the empty-channel floor (the smallest band in the
#     channel) subtracted, at both brightness limits. The rails contribute
#     equally to every band, so this removes them exactly. A high floor is
#     warned about on screen - it means the ROI wants narrowing.
#  2. NEW "CHECK STOPPER SIDE": a chilli sitting still against the OPPOSITE end
#     of the channel is not a chilli that is still sliding. It now says so
#     instead of waiting forever, because that is what a wrong STOPPER_SIDE
#     looks like from the inside.
# ----------------------------------------------------------------------------------
#  v18  REWRITTEN MEASUREMENT: WIDTH PROFILE ALONG THE CHANNEL.
#
#  WHY: v10-v17 all measured the two ends with a pair of small square boxes and
#  then argued about the weights. Seventeen versions of weight-tuning never fixed
#  the real complaint - the answer was either inverted, or the same every time.
#  That is not a weighting problem, it is a MEASUREMENT problem: two little boxes
#  at 22% inset are a very noisy way to ask "which end is fatter", and the box on
#  the stopper end is clipped by the channel edge, which biases it every frame.
#
#  WHAT CHANGED:
#  1. The chilli is no longer found with find_blobs + min_corners + tilt gates.
#     The channel is a narrow strip, so a chilli in it is ALWAYS lined up with it.
#     We slice the channel into bands across its short side and measure how dark
#     each band is. That gives a WIDTH PROFILE from one end of the chilli to the
#     other - the actual shape of the pod, not two samples of it.
#  2. Taper is read from the profile (mean of the first third vs the last third),
#     so it uses the whole body and is far steadier frame to frame.
#  3. The stalk is now measured properly with a SECOND, looser brightness limit.
#     The body is dark; a dried stalk is PALE but still darker than the metal.
#     A band counts as stalk only if it shows up at the loose limit and is all
#     but empty at the body limit - testing for pale rather than merely for thin
#     is what stops the tapering apex being read as a stalk, which it was.
#     Note this check is ONE-SIDED in practice (the ROI stops at the stopper bar,
#     so there is no room to see a stalk on the near side), so it is weighted
#     BELOW taper. A cue that can only ever vote one way must not lead.
#  4. NEW: the chilli must be TOUCHING the stopper end before any decision is
#     made. Deciding on a chilli that is still sliding was a real source of
#     random answers. Note "touching" is judged from a LOW darkness threshold,
#     because an apex-first pod presents a fine point: measured at the old body
#     threshold its tip did not register at all, so apex-first chillies looked
#     like they had never arrived and were judged from the wrong place.
#  4b. Redness is now read from the CHILLI PIXELS only, not from the whole
#     sample box. Averaged over the box it was really measuring how much bare
#     metal was in frame - which is the taper again, inverted - so the colour
#     cue was silently fighting the main cue on every chilli.
#  5. NEW: INVERT_ANSWER. If every chilli reads backwards, this one switch fixes
#     it. CALIBRATE mode now prints exactly what to set it to. This is the fix
#     for "stem shows apex and apex shows stem".
#  6. The clear/empty behaviour is explicit: decide once, HOLD the answer until
#     the chilli physically leaves, report EMPTY, then arm for the next one.
# ----------------------------------------------------------------------------------
#  v17 colour presence gate (kept, as a presence test only)
#  v16 tight ROI stopping at the stopper bar
#  v15 centroid shift  |  v14 fixed narrow CHANNEL_ROI
# ==================================================================================

import sensor, image, time, math
from pyb import Pin, LED


# ------------------------------- CONFIG -------------------------------
CALIBRATE     = False    # True = tuning mode: pins stay OFF, numbers printed
DEBUG         = True     # True = draw the channel, the bands and the ends

# The metal chute, as a box: (x, y, width, height).
# Must sit ON THE METAL ONLY and must stop at the stopper bar.
CHANNEL_ROI   = (200, 50, 28, 138)
#                x    y   w    h

# Which edge of that box the stopper is on: "bottom" "top" "left" "right".
STOPPER_SIDE  = "bottom"

# If EVERY chilli reads backwards, set this True. Nothing else needs changing.
# CALIBRATE mode tells you which way it should be.
INVERT_ANSWER = False

# ---- brightness limits (L runs 0 = black .. 100 = white) ----
MANUAL_L      = None     # None = AUTO (measured each frame); int = fixed, for production
DARK_K        = 0.50
DARK_L_MIN    = 8
DARK_L_MAX    = 50
MIN_CHILI_STD = 6.0      # an empty chute is smooth; anything lying in it breaks that up

# The stalk is paler than the body but still darker than the metal.
# This is how much brighter than the body limit we still call "chilli-ish".
STALK_L_EXTRA = 20
STALK_L_CAP   = 78

# Redness, used ONLY to tell a chilli from a shadow on bare metal.
# It can never say which END is the stem - a pink cloth is redder than a dark
# dried chilli, so any limit that lets real chillies through lets cloth through
# too. Presence only.
MIN_CHILI_RED = 5.0

# ---- the width profile ----
BANDS         = 24       # slices along the channel
# BAND_ON decides where the chilli STARTS AND ENDS. It has to be low, because
# the apex is a fine point: the last band or two of an apex-first chilli fill
# only a few percent of the band. Setting this too high was a real bug - the
# pointed end never counted as "chilli", so an apex-first pod looked like it had
# not reached the stopper yet and was never judged at all.
BAND_ON       = 0.06
BAND_THIN     = 0.10     # something is here, at the loose brightness limit
# The empty-channel floor removed from every band (dark rails just inside the
# ROI edges). Above this the channel is taken to be genuinely full, so nothing
# is subtracted. See the note in look().
BASELINE_MAX  = 0.35
# A floor bigger than this means CHANNEL_ROI is catching a lot that is not
# chilli. It still works, but it is worth narrowing - warned about on screen.
FLOOR_WARN    = 0.15
BAND_TIP      = 0.05     # a stalk is PALE: near-nothing at the body limit
MIN_BODY_BANDS = 3       # shorter than this is noise, not a chilli
MIN_STALK_BANDS = 2      # a 1-band overhang is just the tapering tip, not a stalk
MAX_STALK_BANDS = 7      # longer than this is not a stalk (probably the next chilli)

# ---- must be at the stopper before we answer ----
STOPPER_TOUCH_BANDS = 2  # body must reach within this many bands of the stopper end

# ---- decision weights ----
# TAPER leads. It is the only cue that is measured the same way at both ends,
# is available on every chilli, and comes from the whole body rather than a
# sample of it. The stalk check is strong but ONE-SIDED (see check 6), so it
# must not outweigh taper or it drags every answer the same way - which is the
# exact "always says the same thing" fault this version exists to fix.
W_TAPER       = 1.6      # the stem end is the fat end
W_STALK       = 1.0      # stalk poking out past an end   (only counted when seen)
W_CENTROID    = 0.5      # the mass sits toward the fat end (same data as taper)
# Redness as an END comparison is OFF, and should stay off unless something
# actually demonstrates it helping. It has never once been shown to, and it is
# actively harmful whenever CHANNEL_ROI is a little wide: the dark rails inside
# the ROI pass the dark threshold and carry no redness, so the reading becomes
# "how much rail is in this band" - the taper again, inverted. In the rail test
# case it votes -0.63 against a true taper of +0.52. Still measured and printed
# in CALIBRATE, just not voted with. Colour stays a PRESENCE test only.
W_RED         = 0.0
A_FULL        = 12.0

# ---- rules ----
DECIDE_MIN    = 0.12     # below this the ends look the same
STABLE_N      = 4        # frames that must agree before locking
SMOOTH_N      = 7        # score averaging window
CLEAR_FRAMES  = 4        # empty frames before arming for the next chilli
STUCK_MS      = 2500     # a pod that sits still this long, short of the stopper,
                         # is not sliding - most likely STOPPER_SIDE is wrong
MAX_WAIT_MS   = 1500     # after this long, answer anyway (never stall the line)
MIN_LOCK_MS   = 200      # hold an answer at least this long
DEFAULT_ANSWER = "POD"   # used when the chilli genuinely cannot be told apart
                         # ("POD" = apex = no rotate, the safe default)

# ---- outputs ----
OUTPUT_MODE   = "level"  # "level" = hold until the chilli leaves; "pulse"
PULSE_MS      = 300
ROTATE_ON     = "STEM"
BLINK_MS      = 250

USE_TRIGGER   = False
TRIGGER_PIN   = 'P3'
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
    """Drive P0 / P1 / P2. Only ever called from here, so they cannot disagree."""
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
sensor.set_auto_gain(False)                # lock exposure and colour
sensor.set_auto_whitebal(False)
clock = time.clock()

# ------------------------------- HELPERS ------------------------------
def _get(obj, name, *args):
    """This firmware exposes some accessors as methods and some as properties."""
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
        bs = img.find_blobs(thrs, roi=roi, pixels_threshold=1,
                            area_threshold=1, merge=True)
        return sum(_get(x, "pixels") for x in bs)
    except Exception:
        return 0

def dark_fraction(img, roi, lim):
    """How much of this little box is darker than lim, as 0.0 .. 1.0.

    Read from the brightness histogram in one call, which is both faster and
    steadier than counting blobs 24 times a frame. Falls back to blob counting
    if this firmware's histogram does not behave.
    """
    if roi[2] < 1 or roi[3] < 1:
        return 0.0
    try:
        h = img.get_histogram(roi=roi)
        bins = _get(h, "bins")
        n = len(bins)
        if n > 0:
            k = int(round(lim * n / 100.0))
            if k < 0:
                k = 0
            if k > n:
                k = n
            if k == 0:
                return 0.0
            return float(sum(bins[0:k]))
    except Exception:
        pass
    area = roi[2] * roi[3]
    if area <= 0:
        return 0.0
    return count_px(img, roi, [(0, int(lim), -128, 127, -128, 127)]) / float(area)

def region_redness(img, roi, thrs):
    """Average redness of the CHILLI PIXELS inside roi - not of the whole box.

    This distinction is not cosmetic. A band near the fat end is mostly chilli;
    a band near the pointed end is mostly bare metal. Averaging the whole box
    therefore measures how much metal is in it, which is just the taper again,
    read backwards - it fought the taper cue on every single chilli. Restricting
    to pixels that pass the dark threshold is what makes this an honest colour
    reading. If this firmware will not filter by threshold we return None and
    the colour cue is dropped from the vote rather than guessed at.
    """
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(thresholds=thrs, roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        return None

def region_redness_any(img, roi):
    """Redness of a whole box, threshold or not. Presence checks only."""
    if roi[2] < 2 or roi[3] < 2:
        return None
    try:
        st = img.get_statistics(roi=roi)
        return _stat(st, "a_mean")
    except Exception:
        return None

# The channel is a narrow strip, so a chilli lying in it runs along the strip.
# VERTICAL means the strip is tall and the profile runs down the picture.
VERTICAL   = STOPPER_SIDE in ("top", "bottom")
# After profiling we always want index 0 to be the STOPPER end, so reverse the
# list when the stopper is at the far (high x / high y) side of the box.
REVERSE    = STOPPER_SIDE in ("bottom", "right")

def band_roi(i):
    """Band i of the channel, counted from the stopper end."""
    x, y, w, h = CHANNEL_ROI
    j = (BANDS - 1 - i) if REVERSE else i
    if VERTICAL:
        b0 = y + (h * j) // BANDS
        b1 = y + (h * (j + 1)) // BANDS
        if b1 <= b0:
            b1 = b0 + 1
        return clamp_roi(x, b0, w, b1 - b0)
    b0 = x + (w * j) // BANDS
    b1 = x + (w * (j + 1)) // BANDS
    if b1 <= b0:
        b1 = b0 + 1
    return clamp_roi(b0, y, b1 - b0, h)

def span_rect(lo, hi):
    """A box covering bands lo..hi (inclusive), for drawing and for redness."""
    r0, r1 = band_roi(lo), band_roi(hi)
    x0 = min(r0[0], r1[0])
    y0 = min(r0[1], r1[1])
    x1 = max(r0[0] + r0[2], r1[0] + r1[2])
    y1 = max(r0[1] + r0[3], r1[1] + r1[3])
    return (x0, y0, x1 - x0, y1 - y0)

def object_threshold(img):
    """The brightness line between chilli and metal, for this frame."""
    if MANUAL_L is not None:
        return int(min(max(MANUAL_L, 0), 100))
    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0
    if l_std < MIN_CHILI_STD:
        return 0                       # smooth = empty chute
    lim = l_mean - DARK_K * l_std
    return int(min(max(lim, DARK_L_MIN), DARK_L_MAX))

def mean(seq):
    return sum(seq) / float(len(seq)) if len(seq) else 0.0

def loose_floor(img, lo, hi, lim2):
    """The same empty-channel floor, measured at the looser brightness limit."""
    cand = []
    if lo - 2 >= 0:
        cand.append(0)
    if hi + 2 < BANDS:
        cand.append(BANDS - 1)
    if not cand:
        return 0.0
    return min(dark_fraction(img, band_roi(c), lim2) for c in cand)

def stalk_run(img, prof, start, step, lim2, floor2):
    """How many pale bands run on past the end of the body, from start outward.

    Only the few bands just beyond each end are ever measured, so this costs a
    handful of extra reads rather than a second full profile.
    """
    n, i = 0, start
    while 0 <= i < BANDS and n <= MAX_STALK_BANDS:
        if prof[i] > BAND_TIP:
            break                      # dark flesh, not a pale stalk
        if dark_fraction(img, band_roi(i), lim2) - floor2 < BAND_THIN:
            break                      # nothing here at all
        n += 1
        i += step
    return n

# ------------------------------ THE LOOK ------------------------------
BLANK = {"reason": "empty", "score": 0.0, "lim": 0, "lo": -1, "hi": -1,
         "prof": None, "rect": None, "s_taper": 0.0, "s_stalk": 0.0,
         "s_centroid": 0.0, "s_red": 0.0, "w_near": 0.0, "w_far": 0.0,
         "stalk_near": 0, "stalk_far": 0, "red": 0.0, "agree": True,
         "floor": 0.0, "wrong_end": False}

def look(img):
    out = dict(BLANK)

    lim = object_threshold(img)
    out["lim"] = lim
    if lim <= 0:
        return out

    lim2 = min(STALK_L_CAP, lim + STALK_L_EXTRA)
    thrs = [(0, lim, -128, 127, -128, 127)]

    # --- 1. width profile of the body, from the stopper end outward ---
    raw = [dark_fraction(img, band_roi(i), lim) for i in range(BANDS)]

    # Take off the empty-channel floor.
    #
    # If CHANNEL_ROI is even slightly wider than the bright chute it catches the
    # dark rails down BOTH sides. Those rails are there in every single band, so
    # every band looks partly full: the pod appears to fill the whole channel,
    # `lo` is always 0, the "has it reached the stopper" check never fires, and
    # the taper comparison is between two lengths of rail with a bit of chilli
    # in one of them. That produces a confident answer that has almost nothing
    # to do with the chilli - which is exactly the "same answer every time"
    # fault. The rails contribute equally to every band, so the smallest band in
    # the channel IS that floor, and subtracting it removes them exactly.
    #
    # Guard: if even the emptiest band is well filled, the channel really is
    # full end to end and there is no floor to remove.
    floor = min(raw)
    if floor > BASELINE_MAX:
        floor = 0.0
    prof = [max(0.0, p - floor) for p in raw]
    out["floor"] = floor
    out["prof"] = prof

    # Where the chilli starts and ends. BAND_ON is deliberately low so the
    # pointed apex is included - it is part of the pod and its narrowness is
    # exactly the signal we are after.
    idx = [i for i in range(BANDS) if prof[i] >= BAND_ON]
    if len(idx) < MIN_BODY_BANDS:
        return out
    lo, hi = idx[0], idx[-1]
    out["lo"], out["hi"] = lo, hi

    rect = span_rect(lo, hi)
    out["rect"] = rect

    # --- 2. is it a chilli, or a shadow on bare metal? presence only ---
    red = region_redness(img, rect, thrs)
    if red is None:
        red = region_redness_any(img, rect)
    out["red"] = red if red is not None else 0.0
    if red is not None and red < MIN_CHILI_RED:
        out["reason"] = "metal"
        return out

    # --- 3. has it actually reached the stopper? ---
    # Whether this is a pod still on its way down or a wrong STOPPER_SIDE cannot
    # be told from one frame - a long pod half way down also reaches the far
    # edge. Only time separates them, so the loop decides (see STUCK_MS).
    if lo > STOPPER_TOUCH_BANDS:
        out["reason"] = "sliding"
        return out

    span = hi - lo + 1
    k = max(2, span // 3)

    # --- 4. TAPER: the stem end is the fat end ---
    w_near = mean(prof[lo:lo + k])
    w_far = mean(prof[hi - k + 1:hi + 1])
    out["w_near"], out["w_far"] = w_near, w_far
    if (w_near + w_far) <= 0:
        out["reason"] = "no_read"
        return out
    s_taper = (w_near - w_far) / (w_near + w_far)
    out["s_taper"] = s_taper

    # --- 5. CENTROID: which half of its own length the mass sits in ---
    tot = sum(prof[lo:hi + 1])
    if tot > 0:
        cm = sum(i * prof[i] for i in range(lo, hi + 1)) / tot
        mid = (lo + hi) * 0.5
        s_centroid = min(1.0, max(-1.0, (mid - cm) / (span * 0.25)))
    else:
        s_centroid = 0.0
    out["s_centroid"] = s_centroid

    # --- 6. STALK: pale stick poking out past one end of the dark body ---
    # Re-profile with a looser limit. Where the loose outline runs on past the
    # dark body, that is the stalk.
    #
    # A band counts as stalk only if it is FAINT: something is there at the
    # loose limit, but not enough to be body. That upper bound matters - it is
    # what stops the NEXT CHILLI IN THE QUEUE, sitting just behind this one,
    # from being read as a very long stalk.
    #
    # IN PRACTICE THIS CHECK IS ONE-SIDED. CHANNEL_ROI stops at the stopper bar
    # (it has to - the bar is dark and v11 proved it reads as a stalk), so when
    # a chilli is hard against the stopper there is no room left to see a stalk
    # on the near side. So this cue can realistically only ever fire NEGATIVE,
    # i.e. "stalk at the far end, so the APEX is at the stopper". That is still
    # sound evidence, but it is why W_STALK must not exceed W_TAPER.
    # PALE is the key word. The apex is a fine POINT of the same dark flesh as
    # the body, so its bands still hold dark pixels (prof above BAND_TIP). A
    # stalk is pale wood: it shows up at the loose limit and is all but absent
    # at the body limit. Testing for pale, not merely for thin, is what stops a
    # tapering tip being read as a stalk - which it was, on every stem-first
    # chilli, dragging the answer to APEX.
    floor2 = loose_floor(img, lo, hi, lim2)
    stalk_near = stalk_run(img, prof, lo - 1, -1, lim2, floor2)
    stalk_far = stalk_run(img, prof, hi + 1, +1, lim2, floor2)
    if stalk_near < MIN_STALK_BANDS or stalk_near > MAX_STALK_BANDS:
        stalk_near = 0
    if stalk_far < MIN_STALK_BANDS or stalk_far > MAX_STALK_BANDS:
        stalk_far = 0
    out["stalk_near"], out["stalk_far"] = stalk_near, stalk_far
    if stalk_near == stalk_far:
        s_stalk = 0.0
    else:
        s_stalk = (stalk_near - stalk_far) / float(max(stalk_near, stalk_far))
    out["s_stalk"] = s_stalk

    # --- 7. REDNESS: the stem end is the paler end ---
    a_near = region_redness(img, span_rect(lo, min(hi, lo + k - 1)), thrs)
    a_far = region_redness(img, span_rect(max(lo, hi - k + 1), hi), thrs)
    if a_near is not None and a_far is not None:
        s_red = min(1.0, max(-1.0, (a_far - a_near) / A_FULL))
        rw = W_RED
    else:
        s_red, rw = 0.0, 0.0
    out["s_red"] = s_red

    # --- 8. put it together ---
    # A cue that did not fire is left OUT of the total weight, so it cannot
    # water down the cues that did.
    tot_w = W_TAPER + W_CENTROID + rw
    acc = W_TAPER * s_taper + W_CENTROID * s_centroid + rw * s_red
    if s_stalk != 0.0:
        tot_w += W_STALK
        acc += W_STALK * s_stalk
    score = acc / tot_w if tot_w > 0 else 0.0

    if INVERT_ANSWER:
        score = -score

    # Taper and stalk pointing opposite ways means something is odd - say so,
    # and let the frame counter demand more agreement before locking.
    if s_stalk != 0.0 and s_taper != 0.0 and (s_stalk > 0) != (s_taper > 0):
        out["agree"] = False

    out["score"] = score
    out["reason"] = "ok"
    return out

# Labels
NAME = {"STEM": "STEM", "POD": "APEX"}
REASON_TEXT = {"empty": "EMPTY", "metal": "EMPTY",
               "sliding": "CHILLI STILL MOVING",
               "no_read": "CANNOT SEE CHILLI"}

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

def draw_rect(img, roi, color, thickness=1, fill=False):
    try:
        img.draw_rectangle(roi, color=color, thickness=thickness, fill=fill)
    except Exception:
        try:
            img.draw_rectangle(roi[0], roi[1], roi[2], roi[3], color=color,
                               thickness=thickness, fill=fill)
        except Exception:
            pass

def draw_scene(img, r, headline, color, sub, fps):
    # --- the channel, and which end of it we think the stopper is on ---
    if DEBUG:
        draw_rect(img, CHANNEL_ROI, (255, 0, 255), 1)
        # A solid cyan bar on the STOPPER end. If this bar is not sitting on the
        # end the chilli actually stops against, STOPPER_SIDE is wrong and every
        # answer will be backwards.
        b = band_roi(0)
        draw_rect(img, b, (0, 255, 255), 1, True)

        # the width profile, drawn as a little bar chart beside the channel
        if r["prof"]:
            for i in range(BANDS):
                bx = band_roi(i)
                ln = int(r["prof"][i] * 26)
                if ln < 1:
                    continue
                if VERTICAL:
                    draw_rect(img, clamp_roi(CHANNEL_ROI[0] - 2 - ln, bx[1],
                                             ln, max(1, bx[3] - 1)),
                              (90, 90, 255), 1, True)
                else:
                    draw_rect(img, clamp_roi(bx[0], CHANNEL_ROI[1] - 2 - ln,
                                             max(1, bx[2] - 1), ln),
                              (90, 90, 255), 1, True)

    # --- the chilli body we locked on to ---
    if r["rect"] and r["reason"] in ("ok", "sliding"):
        c = (0, 255, 0) if r["reason"] == "ok" else (255, 180, 0)
        draw_rect(img, r["rect"], c, 2)

    # --- which end we called the stem ---
    if r["reason"] == "ok" and r["lo"] >= 0:
        stem_lo = r["lo"] if r["score"] > 0 else max(r["lo"], r["hi"] - 2)
        stem_hi = min(r["hi"], r["lo"] + 2) if r["score"] > 0 else r["hi"]
        draw_rect(img, span_rect(stem_lo, stem_hi), (0, 150, 255), 2)

    # --- banner ---
    draw_rect(img, (6, 6, 268, 50), (0, 0, 0), 1, True)
    draw_rect(img, (6, 6, 268, 50), color, 2)
    draw_str(img, 12, 10, headline, color=color, scale=2)

    mode = "SET" if MANUAL_L is not None else "AUTO"
    tail = "L<=%d %s | %d FPS" % (r["lim"], mode, int(fps))
    draw_str(img, 12, 32, "%s | %s" % (sub, tail), color=(210, 210, 210),
             scale=1)
    if r["floor"] > FLOOR_WARN:
        draw_str(img, 12, 44, "ROI TOO WIDE - FLOOR %.2f" % r["floor"],
                 color=(255, 160, 0), scale=1)

# ============================ STATE MACHINE ===========================
WAIT, CHECK, LOCKED, CLEARING = 0, 1, 2, 3
state = WAIT
t_state = time.ticks_ms()
hold_answer, hold_n = None, 0
final, final_score, final_sure = None, 0.0, True
empty = 0
pulse_until = 0
total = 0
votes = []
stuck_since = 0          # when the pod first stopped short of the stopper
stuck_lo = -1
stuck_warned = False

def smooth(s):
    """Average the SCORE, never the label - so the sign and the word on screen
    can never disagree (that bug cost a whole afternoon in v9)."""
    global votes
    if s is None:
        votes = []
        return None
    votes.append(s)
    if len(votes) > SMOOTH_N:
        votes.pop(0)
    return sum(votes) / float(len(votes))

print("=" * 62)
print("open_mv2  VERSION 18   stopper=%s  invert=%s" %
      (STOPPER_SIDE, INVERT_ANSWER))
if CALIBRATE:
    print("CALIBRATE MODE - pins stay OFF.")
    print("1. Put a chilli in STEM FIRST (stem touching the stopper).")
    print("2. Read 'score' below. It should be POSITIVE.")
    print("   If it is NEGATIVE for a stem-first chilli, set INVERT_ANSWER = True.")
    print("3. Check the solid CYAN bar is on the end the chilli stops against.")
    print("   If it is on the wrong end, fix STOPPER_SIDE first.")
print("=" * 62)

while True:
    clock.tick()
    now = time.ticks_ms()
    img = sensor.snapshot()
    fps = clock.fps()

    r = look(img)

    # A pod that is short of the stopper and has not moved for a while is not
    # sliding. Either it is jammed, or STOPPER_SIDE is naming the wrong edge -
    # which is the one mistake that inverts every answer without any error.
    if r["reason"] == "sliding":
        if abs(r["lo"] - stuck_lo) > 1:
            stuck_lo, stuck_since, stuck_warned = r["lo"], now, False
        elif time.ticks_diff(now, stuck_since) >= STUCK_MS:
            r["wrong_end"] = True
            if not stuck_warned:
                stuck_warned = True
                print("!!! chilli has sat still at bands %d-%d for %ds without "
                      "reaching the stopper." % (r["lo"], r["hi"], STUCK_MS // 1000))
                print("    STOPPER_SIDE is %r. The solid cyan bar on screen is "
                      "the end it is watching." % STOPPER_SIDE)
                print("    If the pod is resting against the OTHER end, that is "
                      "the bug - set STOPPER_SIDE to the opposite edge.")
    else:
        stuck_lo, stuck_warned = -1, False

    present = (r["reason"] == "ok") and triggered()
    avg = smooth(r["score"] if present else None)
    live = None
    if avg is not None:
        live = "STEM" if avg > 0 else "POD"

    # ---------------------------- CALIBRATE ---------------------------
    if CALIBRATE:
        set_outputs(None)
        service_leds(live if present else None)
        if present:
            draw_scene(img, r, "LOOKS LIKE %s" % NAME[live], (255, 255, 0),
                       "SCORE %+.2f" % avg, fps)
            print("CALIB score=%+.2f -> %-4s | taper %+.2f (%.2f vs %.2f) | "
                  "stalk %+.0f (%d vs %d) | cent %+.2f | red %+.2f | "
                  "bands %d-%d of %d | floor %.2f | a=%.1f%s%s"
                  % (avg, NAME[live], r["s_taper"], r["w_near"], r["w_far"],
                     r["s_stalk"], r["stalk_near"], r["stalk_far"],
                     r["s_centroid"], r["s_red"], r["lo"], r["hi"], BANDS,
                     r["floor"], r["red"],
                     "" if r["agree"] else "  CUES DISAGREE",
                     "  ROI TOO WIDE" if r["floor"] > FLOOR_WARN else ""))
        else:
            if r["wrong_end"]:
                txt, tcol = "CHECK STOPPER SIDE", (255, 160, 0)
            else:
                txt, tcol = REASON_TEXT.get(r["reason"], "EMPTY"), (255, 255, 255)
            draw_scene(img, r, txt, tcol, "no reading", fps)
            print("CALIB %-20s bands %d-%d of %d  floor %.2f  a=%.1f  L<=%d%s"
                  % (txt, r["lo"], r["hi"], BANDS, r["floor"], r["red"],
                     r["lim"], "  ROI TOO WIDE" if r["floor"] > FLOOR_WARN
                     else ""))
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
            need = STABLE_N if r["agree"] else STABLE_N + 2
            if abs(avg) >= DECIDE_MIN:
                if live == hold_answer:
                    hold_n += 1
                else:
                    hold_answer, hold_n = live, 1
            elapsed = time.ticks_diff(now, t_state)
            timed_out = elapsed >= MAX_WAIT_MS

            if hold_n >= need or timed_out:
                # Never stall the line: if the ends genuinely look the same,
                # send the safe default and mark it LOW so it can be audited.
                if hold_n >= need:
                    final, final_sure = hold_answer, True
                else:
                    final = hold_answer if hold_answer else DEFAULT_ANSWER
                    final_sure = False
                final_score = avg
                set_outputs(final)
                total += 1
                pulse_until = time.ticks_add(now, PULSE_MS)
                state, t_state = LOCKED, now
                print(">>> #%d  %s FIRST -> %s HIGH  ==> %s   "
                      "(score %+.2f  taper %+.2f  stalk %+.0f  cent %+.2f)%s"
                      % (total, NAME[final],
                         "P0" if final == "STEM" else "P1",
                         "ROTATE 180 (P2)" if final == ROTATE_ON else "NO ROTATE",
                         final_score, r["s_taper"], r["s_stalk"],
                         r["s_centroid"], "" if final_sure else "  [LOW CONFIDENCE]"))

    # ----------------------------- LOCKED -----------------------------
    # Hold the answer. Do not look again until this chilli has left.
    elif state == LOCKED:
        if OUTPUT_MODE == "pulse" and time.ticks_diff(now, pulse_until) >= 0:
            set_outputs(None)
        if not present and time.ticks_diff(now, t_state) >= MIN_LOCK_MS:
            empty = 1
            state, t_state = CLEARING, now

    # ---------------------------- CLEARING ----------------------------
    elif state == CLEARING:
        if present:
            empty = 0
            state = LOCKED
        else:
            empty += 1
            if empty >= CLEAR_FRAMES:
                set_outputs(None)
                final = None
                smooth(None)
                print("--- chilli gone: STOPPER EMPTY, ready for the next one ---")
                state, t_state = WAIT, now

    # ---------------------------- overlay -----------------------------
    if state in (LOCKED, CLEARING) and final:
        col = (0, 150, 255) if final == "STEM" else (0, 255, 0)
        sub = "%s %+.2f | #%d" % ("LOCKED" if final_sure else "LOCKED LOW",
                                  final_score, total)
        draw_scene(img, r, "%s (%s)" % (NAME[final],
                                        "P0" if final == "STEM" else "P1"),
                   col, sub, fps)
        service_leds(final)
    elif state == CHECK:
        draw_scene(img, r, "CHECKING...", (255, 255, 0),
                   "%+.2f  %d/%d" % (avg if avg is not None else 0.0,
                                     hold_n, STABLE_N), fps)
        service_leds(None)
    else:
        if r["wrong_end"]:
            txt, tcol = "CHECK STOPPER SIDE", (255, 160, 0)
        else:
            txt, tcol = REASON_TEXT.get(r["reason"], "EMPTY"), (255, 255, 255)
        draw_scene(img, r, txt, tcol, "waiting | #%d" % total, fps)
        service_leds(None)

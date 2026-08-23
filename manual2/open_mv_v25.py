# open_mv2.py  —  OpenMV Cam H7 Plus
# ==================================================================================
#  VERSION 25     (bumped every time the code changes - check this first)
# ----------------------------------------------------------------------------------
#  v25  SAY WHEN THE POD RUNS OFF THE FAR END, AND STAMP THE VERSION ON EVERY LINE.
#
#  From the machine: `[pod ends] [flesh ends]` both on band 23, the very last
#  band, with flesh 0.40-0.51 all the way up. A real chilli ends BEFORE the box
#  does. When the object reaches the far edge, either CHANNEL_ROI is longer than
#  the chute and its far end is sitting on something dark, or the pod is longer
#  than the box. Either way the far third is measuring something that is not
#  chilli, and taper - which compares the near third against the far third - is
#  reading a fiction. It quietly said APEX.
#
#  1. The far end now gets the same scrutiny the stopper end has had since v18:
#     if the pod reaches the last band, that is flagged, drawn on screen as
#     "POD RUNS OFF FAR END", and explained once in the log.
#  2. Every decision line now carries the version. Two rounds have been spent on
#     output from a version that was not the one being discussed, and a log line
#     that does not say what produced it cannot be trusted.
# ----------------------------------------------------------------------------------
#  v24  THE REFERENCE MUST ONLY LEARN FROM AN EMPTY CHUTE (AND IN REAL TIME).
#
#  The v23 dump showed `flesh near third 0.10, far third 0.17` - the flesh
#  reading THINNER at the stopper end, which is exactly where every pod sits.
#  That is not a chilli shape, it is the measurement decaying in one place.
#
#  The empty-chute reference is a running minimum with an upward leak, and the
#  leak was PER FRAME. This camera runs at 215 fps, far faster than assumed, so
#  the reference climbed 0.1 every nine seconds - and it kept updating WHILE A
#  POD WAS SITTING IN FRONT OF IT. So it slowly absorbed the pod, hardest in the
#  bands where pods habitually rest: the stopper end. Flesh there reads thin,
#  taper goes negative, and the answer is APEX on pod after pod.
#
#  1. The reference now updates ONLY on frames that read empty (plus warm-up).
#     It means "what the chute looks like when empty", so it has no business
#     learning anything while a chilli is in the way. A watchdog forces an
#     update if nothing has read empty for REF_STALE_MS, so a bad reference can
#     still recover.
#  2. The leak is per SECOND, from the clock, not per frame. Frame rate here
#     varies from 18 to 215 fps depending on what is in view, so anything paced
#     per frame silently changes behaviour with the scene.
# ----------------------------------------------------------------------------------
#  v24b A STALK HAS TO BE A REAL SIGNAL, NOT NOISE.
#
#  The v23 profile dump from the machine finally showed the whole picture:
#
#      19 | 0.11 0.03 | ##   << STALK
#      20 | 0.08 0.00 | ##   << STALK
#      21 | 0.07 0.00 | #    << STALK
#      22 | 0.05 0.00 | #
#      23 | 0.04 0.00 | #    <-- far end [pod ends]
#      stalk bands: 0 at the stopper end, 5 at the far end -> APEX at stopper
#
#  Those five bands average 0.07 of a band - one or two pixels out of 28. That
#  is camera noise on the chute, not a stalk. A real stalk three pixels wide is
#  0.107. The cue was counting noise and voting APEX with it, at weight 2.4.
#
#  Two causes:
#  1. The chute is overexposed white, so `chute_L` came out near 98 and the
#     loose limit hit its cap: the banner read `L<=50/90`. With a limit of 90
#     against a chute at 95-100 there is no headroom, and every speck of noise
#     counts as object. The limit is now placed PROPORTIONALLY between the body
#     limit and the chute (`STALK_SPAN`), so it scales with the real contrast
#     instead of sitting a fixed 8 below a saturated white.
#  2. Nothing required a stalk to be substantial. `STALK_MIN_W` now demands the
#     stalk bands average a real width before the cue counts at all. Noise at
#     0.07 fails it; a genuine stalk at 0.107 passes.
#
#  Also: the profile dump now prints the LOOSE column. That column is what
#  decides the pod extent and the stalk, and it was the one column not shown -
#  which is why the phantom took an extra round to see.
# ----------------------------------------------------------------------------------
#  v23  THE STALK LIMIT IS SET BY THE CHUTE, NOT BY THE BODY LIMIT.
#
#  Still wrong on the machine after v22: a pod with a pale stalk pointing at the
#  stopper read APEX twice, stalk +0 both times. The bar chart showed nothing at
#  all along the stalk, so the stalk was not being MEASURED, never mind weighed.
#
#  The loose limit was `lim + STALK_L_EXTRA` = 49 + 20 = 69. A dried stalk on a
#  white chute sits around L 70-75. The threshold meant to find the stalk was
#  BRIGHTER than the stalk. It was derived from the wrong thing: the body limit
#  says how dark the flesh is, which has nothing to do with how pale a stalk can
#  be before it stops being distinguishable from the chute.
#
#  What matters is the CHUTE. Anything meaningfully darker than the empty chute
#  is object. So the empty-chute brightness is now learned during warm-up
#  (`chute_L`) and the loose limit is `chute_L - CHUTE_MARGIN`. It adapts to the
#  lighting instead of being guessed at, and the per-band reference cancels
#  whatever baseline that leaves.
#
#  Also, two things asked for directly:
#  - The banner no longer sits on top of the chute. It is placed in the widest
#    free strip beside CHANNEL_ROI instead of at a fixed (6, 6, 268, 50).
#  - The band-by-band profile now prints on EVERY locked decision, not only in
#    CALIBRATE. The readout that explains a wrong answer should be in the log
#    that gets looked at.
# ----------------------------------------------------------------------------------
#  v22  GIVE THE LOOSE (STALK) PROFILE A PER-BAND REFERENCE TOO.
#
#  Seen on the machine with v21: a pod with its pale stalk pointing AT the
#  stopper still locked APEX (-0.39), and the stalk cue read -1 - a stalk at the
#  FAR end - which is the opposite of what was in front of the camera. On two
#  other pods it read +0 and saw no stalk at all.
#
#  The stalk lives in the loose profile (it is too pale for the body limit), and
#  the loose profile was the one place still using v19's single-number floor:
#  `loose_floor` took ONE band, outside the pod, and subtracted its value from
#  every band. Everything else moved to a per-band reference in v20. That leftover
#  is why the cue was unreliable - if the sampled band held the stopper bar the
#  floor came out high and wiped the real stalk out, and a single number cannot
#  correct a per-band pattern in any case.
#
#  1. `ref2`, a per-band reference at the loose limit, exactly like `ref` and
#     `ref_t`. `loose_floor` is gone.
#  1b. The pod's extent - and so "has it reached the stopper" - is now taken from
#     the LOOSE profile, so a pale stalk counts as part of the pod. It did not
#     before: a pod resting on a pale stalk had an extent that began at the
#     flesh, three bands up, so it was reported as still sliding and never
#     judged at all. With that fixed the stalk is simply the part of the pod
#     that is not flesh, at either end, and `stalk_run` is no longer needed.
#  2. BAND_THIN 0.10 -> 0.05. A stalk three pixels wide in a 28-pixel channel is
#     0.107 of a band, so the old limit sat right on top of the real signal.
#  3. W_STALK 1.6 -> 2.4. A stalk that has actually been seen is the most direct
#     evidence there is, and it must outvote taper rather than edge past it -
#     on this pod taper says APEX (the flesh really is fatter away from the
#     stopper) and only the stalk knows better.
# ----------------------------------------------------------------------------------
#  v21  SEPARATE THE STALK FROM THE FLESH BY BRIGHTNESS.
#
#  Seen on the machine: a pod lying stalk-down toward the stopper - thick red
#  body at the far end, thin pale stalk pointing at the stopper - locked APEX
#  with taper -0.65 and stalk +0. Wrong: the stalk is on the stopper side, so
#  that is the STEM end.
#
#  The stalk was dark enough to pass the body threshold, so it was swallowed
#  into the pod extent. Taper then compared the fat body against the thin stalk,
#  saw "this end is thinner", and called it the apex. It is the mirror of the
#  v18 bug, where a tapering tip was read as a stalk; now a stalk was read as a
#  tapering tip. Both come of trying to tell them apart by WIDTH.
#
#  Width cannot do it - a stalk and a fine apex can be the same width.
#  BRIGHTNESS can: the flesh is deep red and dark, the stalk is dry and pale.
#  So the profile is measured at TWO limits - `lim` for anything at all, and
#  `lim_t` (a fixed fraction of it) for flesh only. Bands that hold something
#  but no flesh ARE the stalk, at whichever end they sit.
#
#  1. Taper and centroid are now measured over the FLESH alone. A stalk in that
#     comparison reads as "this end is thinner", i.e. as an apex.
#  2. "Has it reached the stopper" still uses the WHOLE pod, stalk included - a
#     stem-first chilli rests on its stalk, and it has genuinely arrived.
#  3. The stalk cue is now genuinely TWO-SIDED, so it no longer has to be held
#     below taper the way v18 required.
# ----------------------------------------------------------------------------------
#  v20  LEARN THE EMPTY-CHUTE REFERENCE PER BAND.
#       v19's single floor removed the rails down the sides (dark in every band)
#       but could not remove the stopper bar inside the ROI edge (dark in the
#       last band only - which is band 0, the stopper end). With the bar in band
#       0, `lo` was always 0, so "reached the stopper" was always true even with
#       the pod short of the bar, and w_near was inflated by the bar so taper was
#       pushed toward STEM on every chilli. The reference is now per band, a
#       running minimum with a slow upward leak. Also SHOW_PROFILE, and VERSION
#       as a single constant.
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

# One place only. The banner prints this, so the terminal can never disagree
# with the header again (in v19 it did, and cost a debugging round).
VERSION = 25


# ------------------------------- CONFIG -------------------------------
CALIBRATE     = False    # True = tuning mode: pins stay OFF, numbers printed
SHOW_PROFILE  = True     # in CALIBRATE, print the band-by-band profile as text.
                         # This is the one readout that settles arguments: it
                         # shows exactly what the camera measures at each end,
                         # with the stopper end labelled. Press-and-read beats
                         # squinting at the frame buffer.
PROFILE_EVERY = 20       # frames between profile dumps (they are chatty)
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

# The stalk is paler than the body but still darker than the metal.
# This is how much brighter than the body limit we still call "chilli-ish".
# Flesh is deep red and dark; a dried stalk is pale. `lim` catches both, and
# `lim * TIGHT_FRAC` catches the flesh only. What lies between the two is stalk.
# This is the ONLY thing that reliably separates a stalk from a tapering apex -
# they can be the same width, so width cannot do it.
TIGHT_FRAC    = 0.70
TIGHT_MIN     = 12
# How much darker than the EMPTY CHUTE something has to be to count as object.
# This is what finds the pale stalk, so it is set from the chute rather than
# from the body limit - a body limit says how dark the flesh is, which tells you
# nothing about how pale a stalk may be. Deriving it from the body limit put the
# threshold BRIGHTER than the stalk, and the stalk went unmeasured.
# Where to put the "anything at all" limit, as a fraction of the way from the
# body limit up to the chute. Proportional, not a fixed margin: the chute here
# is overexposed white (L ~98), and a fixed margin left the limit at 90 with no
# headroom, so noise on the metal counted as object.
STALK_SPAN    = 0.72
STALK_L_CAP   = 90
# A stalk band has to be genuinely occupied. Three pixels of stalk in a 28-pixel
# channel is 0.107 of a band; noise is 0.03-0.07. Without this the cue counted
# five bands of noise as a stalk and voted APEX with it at weight 2.4.
STALK_MIN_W   = 0.09

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
# A stalk 3 px wide in a 28 px channel fills 0.107 of a band, so this has to sit
# well below that or it lands right on top of the signal it is meant to detect.
BAND_THIN     = 0.05     # something is here, at the loose brightness limit
# ---- the empty-channel reference (background) ----
# Learned per band as a running minimum: every band is empty sometimes, so the
# smallest value a band has shown recently IS that band's empty reading. See
# update_reference() for why one number was not enough.
# Per SECOND, not per frame. Frame rate here swings between 18 and 215 fps with
# what is in view, so anything paced per frame changes behaviour with the scene:
# at 215 fps a 0.00005 per-frame leak climbed 0.1 every nine seconds.
REF_LEAK_PER_S = 0.004
REF_STALE_MS   = 60000   # if nothing has read empty this long, refresh anyway
REF_WARMUP    = 40       # frames before the reference is trusted
# A reference this big means CHANNEL_ROI is catching a lot that is not chilli.
# It still works, but it is worth narrowing - warned about on screen.
FLOOR_WARN    = 0.15
MIN_BODY_BANDS = 3       # shorter than this is noise, not a chilli
MIN_STALK_BANDS = 2      # a 1-band overhang is just the tapering tip, not a stalk
MAX_STALK_BANDS = 7      # longer than this is not a stalk (probably the next chilli)

# ---- must be at the stopper before we answer ----
STOPPER_TOUCH_BANDS = 2  # body must reach within this many bands of the stopper end

# ---- decision weights ----
# A visible stalk is the most direct answer there is to "which end is the stem",
# and since v21 it is two-sided (it can vote either way), so it leads. In v18 it
# could only ever vote APEX, and a cue that can only vote one way must never
# lead - it drags every answer the same way. That constraint is gone.
# A stalk that has actually been seen is the most direct evidence there is, so
# it must OUTVOTE taper, not edge past it. Taper can be honestly wrong: on a pod
# whose flesh is fatter away from the stopper it says APEX, and only the stalk
# knows better.
W_STALK       = 2.4      # stalk on that end     (only counted when one is seen)
W_TAPER       = 1.3      # the stem end is the fat end
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

def now_ms():
    return time.ticks_ms()

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

def measure_threshold(img):
    """The brightness line between chilli and metal, measured from this frame."""
    try:
        st = img.get_statistics(roi=CHANNEL_ROI)
        l_mean = _stat(st, "l_mean", 50.0)
        l_std = _stat(st, "l_stdev", 0.0)
        if l_std <= 0:
            l_std = _stat(st, "l_std", 12.0)
    except Exception:
        l_mean, l_std = 50.0, 12.0
    # There used to be an "if the channel is smooth it must be empty, give up
    # now" shortcut here. It had to go: giving up early ALSO skipped learning
    # the empty-channel reference, and an empty channel is the only time that
    # reference CAN be learned. Emptiness is now decided after the reference is
    # taken off, which is both later and much more reliable.
    lim = l_mean - DARK_K * l_std
    return int(min(max(lim, DARK_L_MIN), DARK_L_MAX))

# The threshold is LEARNED FROM THE EMPTY CHUTE AND THEN HELD, not recomputed
# from every frame.
#
# Recomputing it per frame is circular: the chilli darkens the channel, which
# lowers the threshold, which changes how the chilli is measured. Worse, it
# silently invalidates the empty-chute reference - that was learned at one
# threshold, and subtracting it from a profile taken at a different threshold
# leaves a constant error in every band. That is exactly what broke the
# rails test cases: with rails present the auto threshold dropped far enough
# that the rails stopped counting as flesh, while the reference still had them
# in it, so the flesh profile came out ~0.25 low everywhere and the fine apex
# tip vanished into it - and was then reported as a five-band stalk.
#
# So: average it over the warm-up frames (chute empty by then), hold it, and
# afterwards nudge it only on frames that read empty. Lighting drift is followed;
# the chilli itself never moves it.
lim_auto = None
chute_L = None           # mean brightness of the EMPTY chute, learned in warm-up
LIM_ADAPT = 0.02

def object_threshold(img):
    if MANUAL_L is not None:
        return int(min(max(MANUAL_L, 0), 100))
    if lim_auto is None:
        return measure_threshold(img)
    return int(lim_auto)

CHUTE_PCTL = 0.75

def chute_brightness(img):
    """How bright the bare chute is - as a high percentile, not a mean.

    The mean is dragged down by anything dark inside the ROI: the rails at its
    edges, the stopper bar at its end. With rails present the mean read 69 on a
    chute that is really 86, which put the stalk limit below the stalk again.
    A high percentile ignores those minorities and reports the metal itself.
    """
    try:
        h = img.get_histogram(roi=CHANNEL_ROI)
        bins = _get(h, "bins")
        n = len(bins)
        if n > 0:
            acc = 0.0
            for i in range(n):
                acc += bins[i]
                if acc >= CHUTE_PCTL:
                    return (i + 0.5) * 100.0 / n
            return 100.0
    except Exception:
        pass
    try:
        return _stat(img.get_statistics(roi=CHANNEL_ROI), "l_mean", 70.0)
    except Exception:
        return 70.0

def learn_threshold(img):
    """Called during warm-up only: average the empty-chute threshold."""
    global lim_auto, chute_L
    m = measure_threshold(img)
    lim_auto = float(m) if lim_auto is None else lim_auto + 0.25 * (m - lim_auto)
    c = chute_brightness(img)
    chute_L = c if chute_L is None else chute_L + 0.25 * (c - chute_L)

def object_limit(lim):
    """Anything darker than this counts as object - flesh, stalk, anything.

    Sits a fixed FRACTION of the way from the body limit up to the chute, so it
    scales with the actual contrast. A fixed margin below the chute fails when
    the chute is overexposed: it left the limit at 90 against metal at 95-100,
    and noise on the metal started counting as object.
    """
    if chute_L is None:
        return STALK_L_CAP
    span = max(0.0, chute_L - lim)
    return int(min(STALK_L_CAP, lim + span * STALK_SPAN))

def adapt_threshold(img):
    """Called on frames that read EMPTY: follow slow lighting drift."""
    global lim_auto, chute_L
    if lim_auto is not None:
        lim_auto += LIM_ADAPT * (measure_threshold(img) - lim_auto)
    if chute_L is not None:
        chute_L += LIM_ADAPT * (chute_brightness(img) - chute_L)

def mean(seq):
    return sum(seq) / float(len(seq)) if len(seq) else 0.0

# ---------------------- the empty-channel reference -------------------
# v19 subtracted ONE number (the smallest band) from every band. That removed
# the dark rails down the sides, because those sit in every band equally. It did
# NOT remove anything that is dark in only SOME bands - above all the STOPPER BAR
# itself, which sits just inside the bottom edge of the ROI.
#
# That single band is the whole ballgame: it is band 0, the stopper end. With the
# bar in it, band 0 is always full, so `lo` is always 0 and "has it reached the
# stopper" is always true even with the pod still short of the bar, and w_near is
# inflated by the bar so taper is pushed toward STEM on every chilli. v11 hit the
# same hardware from a different angle.
#
# So the reference has to be PER BAND. Each band is empty at some point between
# chillies, so the smallest value a band has recently shown is its empty reading.
# A slow upward leak lets it follow lighting drift and recover if a pod is left
# sitting in the channel. This also subsumes the rails and any fixed shadow.
ref = [1.0] * BANDS
ref_frames = 0

ref_last_ms = None
ref_last_empty_ms = None

def ref_leak(now):
    """How much the reference may drift up since the last frame, by the clock."""
    global ref_last_ms
    if ref_last_ms is None:
        ref_last_ms = now
        return 0.0
    dt = time.ticks_diff(now, ref_last_ms)
    ref_last_ms = now
    if dt < 0 or dt > 2000:
        dt = 0
    return REF_LEAK_PER_S * dt / 1000.0

def update_reference(raw, leak):
    global ref_frames
    ref_frames += 1
    for i in range(BANDS):
        v = ref[i] + leak
        if raw[i] < v:
            v = raw[i]
        ref[i] = v

ref_t = [1.0] * BANDS
ref2 = [1.0] * BANDS

def update_reference2(raw2, leak):
    """The same empty-chute reference, at the loose (stalk) limit.

    The stalk profile needs this every bit as much as the other two. It was the
    one place still using a single-number floor, left over from v19, and that is
    why the stalk cue was unreliable.
    """
    for i in range(BANDS):
        v = ref2[i] + leak
        if raw2[i] < v:
            v = raw2[i]
        ref2[i] = v

def update_reference_t(raw_t, leak):
    """The same empty-chute reference, at the tight (flesh-only) limit.

    The flesh profile needs its own background for the same reason the loose one
    does: rails and the stopper bar are dark enough to pass this limit too.
    """
    for i in range(BANDS):
        v = ref_t[i] + leak
        if raw_t[i] < v:
            v = raw_t[i]
        ref_t[i] = v

def reset_reference():          # used by manual2/test_offline.py, not by the loop
    global ref, ref_frames, ref_t, ref2, lim_auto, chute_L
    global ref_last_ms, ref_last_empty_ms
    ref = [1.0] * BANDS
    ref_t = [1.0] * BANDS
    ref2 = [1.0] * BANDS
    ref_frames = 0
    lim_auto = None
    chute_L = None
    ref_last_ms = None
    ref_last_empty_ms = None

# ------------------------------ THE LOOK ------------------------------
BLANK = {"reason": "empty", "score": 0.0, "lim": 0, "lo": -1, "hi": -1,
         "prof": None, "rect": None, "s_taper": 0.0, "s_stalk": 0.0,
         "s_centroid": 0.0, "s_red": 0.0, "w_near": 0.0, "w_far": 0.0,
         "stalk_near": 0, "stalk_far": 0, "red": 0.0, "agree": True,
         "floor": 0.0, "wrong_end": False, "raw": None, "flesh": None,
         "lo_f": -1, "hi_f": -1, "loose": None, "lim2": 0, "runs_off": False}

def look(img):
    out = dict(BLANK)

    if ref_frames < REF_WARMUP:
        learn_threshold(img)          # chute_L is needed even when MANUAL_L is set
    lim = object_threshold(img)
    out["lim"] = lim

    lim2 = max(lim + 4, object_limit(lim))
    out["lim2"] = lim2
    lim_t = max(TIGHT_MIN, int(lim * TIGHT_FRAC))     # flesh only
    thrs = [(0, lim, -128, 127, -128, 127)]

    # --- 1. width profile of the body, from the stopper end outward ---
    raw = [dark_fraction(img, band_roi(i), lim) for i in range(BANDS)]

    # Take off the empty-channel reference, band by band. This is what removes
    # the dark rails down the sides AND the stopper bar inside the bottom edge.
    raw_t = [dark_fraction(img, band_roi(i), lim_t) for i in range(BANDS)]
    raw2 = [dark_fraction(img, band_roi(i), lim2) for i in range(BANDS)]
    prof = [max(0.0, raw[i] - ref[i]) for i in range(BANDS)]
    flesh = [max(0.0, raw_t[i] - ref_t[i]) for i in range(BANDS)]
    loose = [max(0.0, raw2[i] - ref2[i]) for i in range(BANDS)]
    out["loose"] = loose
    out["floor"] = mean(ref)
    out["prof"] = prof
    out["flesh"] = flesh
    out["raw"] = raw

    # --- learn the reference, but ONLY from an empty chute ---
    # The reference means "what the chute looks like with nothing in it", so it
    # has no business learning while a chilli is in the way. It used to update
    # on every frame, and slowly absorbed the pod - worst in the bands where
    # pods habitually rest, i.e. the stopper end. The flesh then read thin
    # there, taper went negative, and the answer was APEX on pod after pod.
    global ref_last_empty_ms
    idx = [i for i in range(BANDS) if prof[i] >= BAND_ON]
    seems_empty = len(idx) < MIN_BODY_BANDS
    warming = ref_frames < REF_WARMUP
    # Watchdog: if nothing has read empty for a long time the reference may
    # itself be the reason, so refresh anyway rather than stay stuck.
    stale = (ref_last_empty_ms is not None
             and time.ticks_diff(now_ms(), ref_last_empty_ms) > REF_STALE_MS)
    if warming or seems_empty or stale:
        leak = ref_leak(now_ms())
        update_reference(raw, leak)
        update_reference_t(raw_t, leak)
        update_reference2(raw2, leak)
        if seems_empty or warming:
            ref_last_empty_ms = now_ms()
    else:
        ref_leak(now_ms())            # keep the clock in step, do not drift

    if warming:
        out["reason"] = "learning"
        return out

    if seems_empty:
        adapt_threshold(img)          # nothing in the way: safe to follow drift
        return out

    # Where the WHOLE pod starts and ends - flesh and stalk together. BAND_ON is
    # deliberately low so the pointed apex is included; it is part of the pod and
    # its narrowness is exactly the signal we are after.
    lo_d, hi_d = idx[0], idx[-1]

    # The pod's real extent comes from the LOOSE profile, so that a pale stalk
    # counts as part of the pod. Taking it from the dark profile instead was a
    # bug: a pod resting on a pale stalk began, as far as the code was
    # concerned, at its flesh three bands up - so it was called "still sliding"
    # and never judged, on exactly the pods whose stalk was easiest to see.
    aidx = [i for i in range(BANDS) if loose[i] >= BAND_THIN]
    lo = min(aidx[0], lo_d) if aidx else lo_d
    hi = max(aidx[-1], hi_d) if aidx else hi_d
    out["lo"], out["hi"] = lo, hi

    rect = span_rect(lo_d, hi_d)      # redness reads the DARK pod, not the stalk
    out["rect"] = rect

    # A real chilli ends before the box does. If it reaches the last band then
    # either CHANNEL_ROI is longer than the chute and its far end is sitting on
    # something dark, or the pod is longer than the box. Either way the far
    # third is not chilli and taper is comparing against a fiction.
    out["runs_off"] = (hi >= BANDS - 1)

    # Now the FLESH alone, measured at a tighter (darker) limit. Everything the
    # pod occupies that is not flesh is stalk - and which END that sits on is
    # the single most direct answer to the question being asked.
    fidx = [i for i in range(lo_d, hi_d + 1) if flesh[i] >= BAND_ON]
    if len(fidx) < MIN_BODY_BANDS:
        # Something is lying there but none of it is dark enough to be flesh.
        out["reason"] = "no_read"
        return out
    lo_f, hi_f = fidx[0], fidx[-1]
    out["lo_f"], out["hi_f"] = lo_f, hi_f

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

    # Taper and centroid are measured over the FLESH, never the whole pod. A
    # stalk included in this comparison reads as "that end is thinner", i.e. as
    # an apex - which is exactly how a stalk-first pod came to be called APEX.
    span = hi_f - lo_f + 1
    k = max(2, span // 3)

    # --- 4. TAPER: the stem end is the fat end ---
    w_near = mean(flesh[lo_f:lo_f + k])
    w_far = mean(flesh[hi_f - k + 1:hi_f + 1])
    out["w_near"], out["w_far"] = w_near, w_far
    if (w_near + w_far) <= 0:
        out["reason"] = "no_read"
        return out
    s_taper = (w_near - w_far) / (w_near + w_far)
    out["s_taper"] = s_taper

    # --- 5. CENTROID: which half of its own length the mass sits in ---
    tot = sum(flesh[lo_f:hi_f + 1])
    if tot > 0:
        cm = sum(i * flesh[i] for i in range(lo_f, hi_f + 1)) / tot
        mid = (lo_f + hi_f) * 0.5
        s_centroid = min(1.0, max(-1.0, (mid - cm) / (span * 0.25)))
    else:
        s_centroid = 0.0
    out["s_centroid"] = s_centroid

    # --- 6. STALK: which end has stalk on it ---
    # Two sources, added together, because a stalk can be either side of `lim`:
    #
    #   a) INSIDE the pod but not flesh - bands the pod occupies where nothing
    #      is dark enough to be flesh. This is the stalk that is darker than
    #      `lim`, the case that used to be swallowed into the body and read as
    #      a tapering apex.
    #   b) BEYOND the pod - pale bands running on past it, seen only at the
    #      looser `lim2`. This is the stalk that is brighter than `lim`.
    #
    # Because (a) sits between the flesh and the stopper, this cue is now
    # genuinely TWO-SIDED: it can vote STEM as well as APEX. In v18 it could
    # only ever vote APEX, which is why it had to be held below taper.
    # The stalk is simply the part of the pod that is not flesh, at either end.
    # One expression now covers both a stalk dark enough to pass the body limit
    # and a pale one visible only in the loose profile.
    stalk_near = lo_f - lo
    stalk_far = hi - hi_f
    # A stalk must be substantial, not a few noisy pixels. Without this, five
    # bands averaging 0.07 - one pixel in fourteen - were counted as a stalk and
    # swung the answer at weight 2.4.
    if stalk_near > 0 and mean(loose[lo:lo_f]) < STALK_MIN_W:
        stalk_near = 0
    if stalk_far > 0 and mean(loose[hi_f + 1:hi + 1]) < STALK_MIN_W:
        stalk_far = 0
    # A run longer than MAX_STALK_BANDS is not a stalk - most likely the next
    # chilli queued up behind this one.
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

def print_profile(r):
    """The whole measurement, in text, with the stopper end named.

    Band 0 is always the stopper end. `raw` is what the camera saw, `ref` is the
    learned empty-chute reading for that band, and the bar is what is left after
    the reference is taken off - the chilli, and only the chilli.
    """
    if r["raw"] is None:
        return
    print("  --- v%d profile, band 0 = stopper (%s) ---" % (VERSION, STOPPER_SIDE))
    print("  band | any  pod  flesh | width     (any drives extent + stalk)")
    for i in range(BANDS):
        v = r["prof"][i]
        tag = ""
        if i == 0:
            tag = "  <-- STOPPER (%s)" % STOPPER_SIDE
        elif i == BANDS - 1:
            tag = "  <-- far end"
        if i == r["lo"]:
            tag += "  [pod starts]"
        if i == r["hi"]:
            tag += "  [pod ends]"
        if i == r["lo_f"]:
            tag += "  [flesh starts]"
        if i == r["hi_f"]:
            tag += "  [flesh ends]"
        f = r["flesh"][i] if r["flesh"] else 0.0
        a = r["loose"][i] if r["loose"] else 0.0
        if r["lo"] <= i <= r["hi"] and f < BAND_ON:
            tag = "  << STALK" + tag
        print("   %2d  | %.2f %.2f %.2f  | %-18s%s"
              % (i, a, v, f, "#" * int(max(a, v) * 18 + 0.5), tag))
    print("  flesh near third %.2f  far third %.2f  taper %+.2f -> %s"
          % (r["w_near"], r["w_far"], r["s_taper"],
             "STEM at stopper" if r["s_taper"] > 0 else "APEX at stopper"))
    if r["runs_off"]:
        print("  !! the pod reaches the LAST band - the far third is not all chilli")
    print("  stalk bands: %d at the stopper end, %d at the far end -> %s"
          % (r["stalk_near"], r["stalk_far"],
             "no stalk seen" if r["s_stalk"] == 0 else
             ("STEM at stopper" if r["s_stalk"] > 0 else "APEX at stopper")))

# Labels
NAME = {"STEM": "STEM", "POD": "APEX"}
REASON_TEXT = {"empty": "EMPTY", "metal": "EMPTY",
               "learning": "LEARNING EMPTY CHUTE",
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

def banner_rect():
    """A box for the text that does not cover the chute."""
    cx, cy, cw, ch = CHANNEL_ROI
    left = cx - 8
    right = 320 - (cx + cw) - 8
    h = 54
    if left >= right:
        return (4, 4, max(70, min(left, 300)), h)
    return (min(316, cx + cw + 4), 4, max(70, min(right, 300)), h)

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
        mk = span_rect(stem_lo, stem_hi)
        draw_rect(img, mk, (0, 150, 255), 2)
        draw_str(img, max(0, mk[0] - 40), max(0, mk[1] - 9), "STEM?",
                 color=(0, 150, 255), scale=1)

    # --- banner ---
    # Placed in the widest free strip BESIDE the chute. It used to be a fixed
    # (6, 6, 268, 50), which sat straight on top of the chilli.
    bx, by, bw, bh = banner_rect()
    draw_rect(img, (bx, by, bw, bh), (0, 0, 0), 1, True)
    draw_rect(img, (bx, by, bw, bh), color, 2)
    sc = 2 if len(str(headline)) * 12 <= bw - 10 else 1
    draw_str(img, bx + 5, by + 4, headline, color=color, scale=sc)

    mode = "SET" if MANUAL_L is not None else "AUTO"
    draw_str(img, bx + 5, by + 22, sub, color=(210, 210, 210), scale=1)
    draw_str(img, bx + 5, by + 32,
             "L<=%d/%d %s %dfps" % (r["lim"], r["lim2"], mode, int(fps)),
             color=(150, 150, 150), scale=1)
    if r["runs_off"]:
        draw_str(img, bx + 5, by + 42, "POD RUNS OFF FAR END",
                 color=(255, 160, 0), scale=1)
    elif r["floor"] > FLOOR_WARN:
        draw_str(img, bx + 5, by + 42, "ROI TOO WIDE %.2f" % r["floor"],
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
calib_n = 0              # frames seen in CALIBRATE, paces the profile dump
runoff_warned = False    # the "pod runs off the far end" note is printed once
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
print("open_mv2  VERSION %d   stopper=%s  invert=%s" %
      (VERSION, STOPPER_SIDE, INVERT_ANSWER))
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
            if SHOW_PROFILE and (calib_n % PROFILE_EVERY) == 0:
                print_profile(r)
            calib_n += 1
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
                if SHOW_PROFILE:
                    print_profile(r)
                if r["runs_off"] and not runoff_warned:
                    runoff_warned = True
                    print("!!! the pod reaches the LAST band of the channel.")
                    print("    A real chilli ends before the box does, so the far")
                    print("    third is measuring something that is not chilli and")
                    print("    taper is comparing against it. Either CHANNEL_ROI is")
                    print("    longer than the chute (shorten h), or its far end is")
                    print("    over something dark, or the pod is longer than the box.")
                print(">>> v%d #%d  %s FIRST -> %s HIGH  ==> %s   "
                      "(score %+.2f  taper %+.2f  stalk %+.0f  cent %+.2f)%s"
                      % (VERSION, total, NAME[final],
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

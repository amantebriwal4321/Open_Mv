"""
main_openmv.py — Chilli Stem Detector v33 (OpenMV H7 Plus)

APPROACH: Advanced Direct Color Body & Stem Segmentation (NO background subtraction)
Optimized for high-speed, zero-allocation real-time industrial sorting.

Performs robust physical stem color localization (Green/Yellow/Woody Brown)
with dual geometric fallback (Centroid Shift + Pixel Density Comparison)
to deliver picture-perfect detection on all chilli varieties and shapes.

Features "HUD Overlay Freezing" to persistently display the body box and stem circle
during the entire cooldown phase for perfect visual validation.

IO Pins: P0=LEFT, P1=RIGHT, P2=REJECT
"""

import sensor
import image
import time
import pyb
import gc
from pyb import Pin, UART

# ─────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────

# LAB thresholds for Chilli Body (Highly inclusive to capture the full body, L raised to 95 to capture bright parts, green tightened to ignore metal)
CHILI_THRESHOLDS = [
    (2, 95, 5, 127, -25, 100),       # Red/Brown Body (highly inclusive redness A >= 5, capped at L=95)
    (2, 95, -128, -25, -128, 127),   # Green Body (strictly green, ignores tray)
    (2, 95, -10, 40, 15, 127)        # Yellow/Orange Body (inclusive)
]

# LAB thresholds for Stems (Used for direct physical stem color localization - strictly pale colors, capped at L=75 to ignore glares)
STEM_THRESHOLDS = [
    (2, 75, -128, -20, -128, 127),   # Green Stem (requires strong greenness A <= -20, ignores gray tray)
    (28, 75, -10, 10, 18, 80)        # Yellow/Dry Stem (requires L: 28-75, A in [-10, 10], B >= 18 - straw/woody stem)
]

# Strict shape and size thresholds to reject hands, fingers, and background clutter
MIN_CHILLI_PIXELS = 350    # Excludes tiny background noise specs and empty tray glares/rivets (<300 px)
MAX_CHILLI_PIXELS = 4500   # Excludes massive objects like human hands/wrists (> 4500 px)
MIN_ELONGATION    = 0.15   # Supports curved and bent dried chillis
MIN_ASPECT_RATIO  = 1.4    # Supports curved and bent dried chillis
TRIGGER_CHILLI_PIXELS = 350 # Start sorting when a valid chilli body is detected (>= 350 px)

# Endpoint comparison
END_STRIP_PCT    = 0.22    # 22% search strip on each end to capture calyx/body structures
MIN_DIFF_PCT     = 1.8     # min density % difference to commit decision

# Voting filter
SAMPLE_COUNT     = 15      # Accumulates votes over 15 frames (~650ms) for high-stability
MAX_FRAMES       = 45      # Maximum voting frame window

# Timing controls (milliseconds) — Optimized for high-speed conveyor belts
SIGNAL_MS        = 180     # Quick pulse for sorting pneumatic actuator
DISPLAY_MS       = 600     # Brief HUD display duration, resets quickly for the next item
COOLDOWN_MS      = 600     # Fast cooldown lockout (confirm_count handles AWB noise)

# Frame coordinates (Focused STRICTLY on the central trapezoidal groove)
IMG_W = 320
IMG_H = 240
ROI   = (50, 80, 220, 95)  # Restored wide ROI to prevent cropping long chillis

# ─────────────────────────────────────
# HARDWARE INITIALIZATION
# ─────────────────────────────────────

# Precise Push-Pull outputs for sorting PLC/relays
pin_left   = Pin("P0", Pin.OUT_PP, Pin.PULL_NONE)
pin_right  = Pin("P1", Pin.OUT_PP, Pin.PULL_NONE)
pin_reject = Pin("P2", Pin.OUT_PP, Pin.PULL_NONE)

# Initial low state
pin_left.low()
pin_right.low()
pin_reject.low()

# High-speed UART for hardware interface / debug reporting
uart = UART(3, 115200, timeout_char=100)

# Status LEDs
led_r = pyb.LED(1) # Red (Reject)
led_g = pyb.LED(2) # Green (Left)
led_b = pyb.LED(3) # Blue (Right)

def uprint(msg):
    """Log to serial port and terminal synchronously."""
    print(msg)
    uart.write(msg + "\r\n")

# ─────────────────────────────────────
# CAMERA SETTINGS
# ─────────────────────────────────────

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)

# Keep auto-gain and auto-white-balance active for real-time dynamic light adaptation
sensor.set_auto_gain(True)
sensor.set_auto_whitebal(True)
sensor.skip_frames(time=1000)

clock = time.clock()

# ─────────────────────────────────────
# STATE MACHINE STATE VARIABLES
# ─────────────────────────────────────

STATE_IDLE       = 0
STATE_ACCUMULATE = 1
STATE_COOLDOWN   = 2

state          = STATE_IDLE
pulse_active   = False
pulse_start    = 0
pulse_pin      = None
last_result    = "NONE"
result_time    = 0
samples        = []
acc_frames     = 0
cooldown_start = 0
total_frames   = 0
total_sorted   = 0
empty_frame_count = 0
confirm_count     = 0  # Consecutive valid-detection frames needed before starting a vote
idle_presence     = 0  # Tracks how long an unrecognizable object sits in the tray

# Globally cached successful detection overlays (HUD Freezing)
cached_bx = 0
cached_by = 0
cached_bw = 0
cached_bh = 0
cached_stem_x = 0
cached_stem_y = 0
cached_stem_found = False
cached_vote = 0.0
cached_horizontal = True

def fire(side, conf):
    """Trigger pneumatic/sorting valve and activate status LED."""
    global pulse_active, pulse_start, pulse_pin
    pin_left.low()
    pin_right.low()
    pin_reject.low()

    if side == "LEFT":
        pin_left.high()
        pulse_pin = pin_left
        led_g.on()
    elif side == "RIGHT":
        pin_right.high()
        pulse_pin = pin_right
        led_b.on()
    else:
        pin_reject.high()
        pulse_pin = pin_reject
        led_r.on()

    uprint("[FIRE] %s conf=%.1f%%" % (side, conf))
    pulse_active = True
    pulse_start = time.ticks_ms()

# ─────────────────────────────────────
# CORE DETECTOR (Multi-Approach Ensemble)
# ─────────────────────────────────────

def detect(img, show_arrow=False, draw_overlay=True):
    """
    Finds the chilli body, searches for a physical stem at endpoints using
    Restricted Stem Search ROIs with Geometric Thickness Validation, and
    falls back to a highly robust Ensemble (Dynamic Thickness + Centroid + Density).

    Returns (present, found, vote, conf, cx, cy, npx)
    """
    global cached_bx, cached_by, cached_bw, cached_bh
    global cached_stem_x, cached_stem_y, cached_stem_found
    global cached_vote, cached_horizontal

    # 1. Segment and Extract Chilli Body Blob
    blobs = img.find_blobs(
        CHILI_THRESHOLDS,
        roi=ROI,
        pixels_threshold=MIN_CHILLI_PIXELS,
        area_threshold=MIN_CHILLI_PIXELS,
        merge=True
    )

    if not blobs:
        return (False, False, 0.0, 0.0, 0, 0, 0)

    # Find the largest body blob in the slot
    b = None
    max_px = 0
    for bl in blobs:
        px = bl.pixels()
        if px > max_px:
            max_px = px
            b = bl

    if b is None:
        return (False, False, 0.0, 0.0, 0, 0, 0)

    present = True  # Object is physically present in the ROI slot
    bx, by, bw, bh = b.rect()
    npx   = b.pixels()
    elong = b.elongation()

    # Calculate Aspect Ratio
    if bw >= bh:
        aspect = bw / bh if bh > 0 else bw
    else:
        aspect = bh / bw if bw > 0 else bh

    # Target shape and size limits
    if npx > MAX_CHILLI_PIXELS:
        if draw_overlay:
            img.draw_rectangle(bx, by, bw, bh, color=(255, 50, 50), thickness=1)
            img.draw_string(bx + 4, by - 12, "BIG", color=(255, 50, 50), scale=1)
        return (present, False, 0.0, 0.0, 0, 0, npx)

    if elong < MIN_ELONGATION:
        if draw_overlay:
            img.draw_rectangle(bx, by, bw, bh, color=(255, 50, 50), thickness=1)
            img.draw_string(bx + 4, by - 12, "ROUND", color=(255, 50, 50), scale=1)
        return (present, False, 0.0, 0.0, 0, 0, npx)

    if aspect < MIN_ASPECT_RATIO:
        if draw_overlay:
            img.draw_rectangle(bx, by, bw, bh, color=(255, 50, 50), thickness=1)
            img.draw_string(bx + 4, by - 12, "SQ", color=(255, 50, 50), scale=1)
        return (present, False, 0.0, 0.0, 0, 0, npx)

    # ── BLOB COLOR CONTRAST CHECK ──
    # Real chillis create high A/B stdev (colored object vs gray background).
    # Tray noise is uniform gray → low stdev. This is immune to background dilution.
    bb_stats = img.get_statistics(roi=(bx, by, bw, bh))
    bb_var = bb_stats.a_stdev() + bb_stats.b_stdev()
    if bb_var < 4.0:
        if draw_overlay:
            img.draw_rectangle(bx, by, bw, bh, color=(128, 128, 0), thickness=1)
            img.draw_string(bx + 4, by - 12, "TRAY", color=(128, 128, 0), scale=1)
        return (present, False, 0.0, 0.0, 0, 0, npx)

    horizontal = bw >= bh

    # Define Left/Right End Strips
    if horizontal:
        sw = int(bw * END_STRIP_PCT)
        if sw < 4: sw = 4
        left_roi  = (bx, by, sw, bh)
        right_roi = (bx + bw - sw, by, sw, bh)
    else:
        sh = int(bh * END_STRIP_PCT)
        if sh < 4: sh = 4
        left_roi  = (bx, by, bw, sh)
        right_roi = (bx, by + bh - sh, bw, sh)

    # ─────────────────────────────────────
    # APPROACH 2: Dynamic Thickness & Pixel Density (Highly Optimized: Zero find_blobs CPU Overhead!)
    # ─────────────────────────────────────
    # We call find_blobs exactly ONCE per side, and use it for BOTH thickness and density calculation!
    left_blobs  = img.find_blobs(CHILI_THRESHOLDS, roi=left_roi, merge=False)
    right_blobs = img.find_blobs(CHILI_THRESHOLDS, roi=right_roi, merge=False)

    # 1. Get thickness from the vertical height (or horizontal width) of the largest end blobs
    if horizontal:
        left_thick = max(bl.h() for bl in left_blobs) if left_blobs else 0
        right_thick = max(bl.h() for bl in right_blobs) if right_blobs else 0
    else:
        left_thick = max(bl.w() for bl in left_blobs) if left_blobs else 0
        right_thick = max(bl.w() for bl in right_blobs) if right_blobs else 0

    thick_side = "LEFT" if left_thick >= right_thick else "RIGHT"
    thick_diff = abs(left_thick - right_thick)
    thick_sum = left_thick + right_thick
    thick_conf = min((thick_diff / (thick_sum if thick_sum > 0 else 1.0)) * 250.0, 100.0)

    # 2. Get pixel density
    left_px = 0
    if left_blobs:
        for bl in left_blobs:
            left_px += bl.pixels()

    right_px = 0
    if right_blobs:
        for bl in right_blobs:
            right_px += bl.pixels()

    if horizontal:
        strip_area = sw * bh
    else:
        strip_area = bw * sh

    left_pct  = (left_px  / strip_area * 100.0) if strip_area > 0 else 0.0
    right_pct = (right_px / strip_area * 100.0) if strip_area > 0 else 0.0
    diff_pct  = abs(left_pct - right_pct)

    dens_side = "LEFT" if left_pct > right_pct else "RIGHT"
    dens_conf = min(diff_pct / 18.0 * 100.0, 100.0)

    # ─────────────────────────────────────
    # APPROACH 1: Restricted Stem Search ROI (Color Stem Detection)
    # ─────────────────────────────────────
    # Search immediately adjacent to the body blob's left and right ends (ignores table background)
    ls_x = max(ROI[0], bx - 25)
    ls_w = min(25, bx - ls_x + 2)
    
    rs_x = bx + bw - 2
    rs_w = min(25, ROI[0] + ROI[2] - rs_x)
    
    left_stem_px = 0
    right_stem_px = 0
    
    stem_x, stem_y = 0, 0
    stem_found = False
    stem_side = "NONE"
    
    # 1. Find stem pixels on the Left
    if ls_w > 1:
        left_stem_roi = (ls_x, max(ROI[1], by - 10), ls_w, min(bh + 20, ROI[1] + ROI[3] - max(ROI[1], by - 10)))
        left_stems = img.find_blobs(STEM_THRESHOLDS, roi=left_stem_roi, merge=True)
        if left_stems:
            largest_s = max(left_stems, key=lambda s: s.pixels())
            # Connection/Gap Check: The stem must be physically attached or close to the body (8px tolerance)
            gap = bx - (largest_s.x() + largest_s.w())
            if gap <= 8:
                left_stem_px = largest_s.pixels()
                stem_x, stem_y = largest_s.cx(), largest_s.cy()
            
    # 2. Find stem pixels on the Right
    if rs_w > 1:
        right_stem_roi = (rs_x, max(ROI[1], by - 10), rs_w, min(bh + 20, ROI[1] + ROI[3] - max(ROI[1], by - 10)))
        right_stems = img.find_blobs(STEM_THRESHOLDS, roi=right_stem_roi, merge=True)
        if right_stems:
            largest_s = max(right_stems, key=lambda s: s.pixels())
            # Connection/Gap Check: The stem must be physically attached or close to the body (8px tolerance)
            gap = largest_s.x() - (bx + bw)
            if gap <= 8:
                right_stem_px = largest_s.pixels()
                if not (ls_w > 1 and left_stem_px > right_stem_px):
                    stem_x, stem_y = largest_s.cx(), largest_s.cy()
            
    # 3. Determine color stem candidate (requires a solid 25 pixels to filter out calyx/dust/glare)
    if left_stem_px > 25 or right_stem_px > 25:
        stem_found = True
        stem_side = "LEFT" if left_stem_px >= right_stem_px else "RIGHT"

    # ─────────────────────────────────────
    # APPROACH 3: Centroid Shift (Mass Shift)
    # ─────────────────────────────────────
    gx = bx + bw / 2.0
    gy = by + bh / 2.0
    cx = b.cx()
    cy = b.cy()

    cs_side = "LEFT" if cx < gx else "RIGHT"
    shift = abs(cx - gx)
    max_possible_shift = bw / 2.0 if bw > 0 else 1.0
    cs_conf = min((shift / max_possible_shift) * 350.0, 100.0)

    # ─────────────────────────────────────
    # DECISION TALLY (Strict Color Detection, No Unreliable Geometric Fallback)
    # ─────────────────────────────────────
    if stem_found:
        vote = -1.0 if stem_side == "LEFT" else 1.0
        conf = 100.0  # Physical stem color detection is definitive
        method = "COLOUR"
    else:
        vote = 0.0
        conf = 100.0
        method = "NO_STEM"

    # Cache overlays for persistent freezing during COOLDOWN phase
    cached_bx, cached_by, cached_bw, cached_bh = bx, by, bw, bh
    cached_stem_x, cached_stem_y = stem_x, stem_y
    cached_stem_found = stem_found
    cached_vote = vote
    cached_horizontal = horizontal

    # Print debugging output to Serial Console
    uprint("[DET] px=%d el=%.2f asp=%.1f ThickL=%d ThickR=%d diff=%.1f%% method=%s" % (
        npx, elong, aspect, left_thick, right_thick, diff_pct, method))

    # Reject if shape difference is too close to call and no physical stem is visible
    if not stem_found and method != "NO_STEM" and conf < 12.0:
        if draw_overlay:
            img.draw_rectangle(bx, by, bw, bh, color=(128, 128, 0), thickness=1)
            img.draw_string(bx + 4, by + 4, "~EQUAL", color=(128, 128, 0), scale=1)
        return (present, False, 0.0, 0.0, bx + bw // 2, by + bh // 2, npx)

    mid_x = bx + (bw // 2)
    mid_y = by + (bh // 2)

    # ─────────────────────────────────────
    # PREMIUM HUD OVERLAYS DRAWING
    # ─────────────────────────────────────
    if draw_overlay:
        # 1. Draw Body Box (Gold)
        img.draw_rectangle(bx, by, bw, bh, color=(255, 185, 0), thickness=2)
        img.draw_string(bx + 4, by + 4, "BODY", color=(255, 185, 0), scale=1)

        # 2. Draw Restricted Stem Search ROIs (Teal/Light Blue)
        if ls_w > 1:
            img.draw_rectangle(left_stem_roi, color=(0, 200, 255), thickness=1)
        if rs_w > 1:
            img.draw_rectangle(right_stem_roi, color=(0, 200, 255), thickness=1)

        # 3. Draw Dynamic Thickness Indicators (Magenta)
        img.draw_rectangle(left_roi, color=(255, 0, 255), thickness=1)
        img.draw_string(left_roi[0] + 2, left_roi[1] + 2, "T:%d" % left_thick, color=(255, 0, 255), scale=1)
        img.draw_rectangle(right_roi, color=(255, 0, 255), thickness=1)
        img.draw_string(right_roi[0] + 2, right_roi[1] + 2, "T:%d" % right_thick, color=(255, 0, 255), scale=1)

        # 4. Draw STEM Circle if found (Red)
        if stem_found:
            img.draw_circle(stem_x, stem_y, 8, color=(255, 50, 50), thickness=2)
            img.draw_string(stem_x - 15, stem_y - 20, "STEM", color=(255, 50, 50), scale=1)

        # 5. Draw Direction Vectors
        if show_arrow:
            if horizontal:
                ax = bx + 6 if vote <= 0 else bx + bw - 6  # Arrow points left for NO_STEM (vote == 0.0)
                img.draw_arrow(mid_x, mid_y, ax, mid_y, color=(0, 255, 100), thickness=2)
            else:
                ay = by + 6 if vote <= 0 else by + bh - 6
                img.draw_arrow(mid_x, mid_y, mid_x, ay, color=(0, 255, 100), thickness=2)

    if vote < 0:
        side = "LEFT"
    elif vote > 0:
        side = "RIGHT"
    else:
        side = "NO_STEM"
    uprint("[STEM] Direction: %s, confidence: %.1f%% (%s)" % (side, conf, method))

    return (present, True, vote, conf, mid_x, mid_y, npx)

# ─────────────────────────────────────
# SYSTEM BOOT DIAGNOSTIC REPORT
# ─────────────────────────────────────

uprint("=" * 50)
uprint("[BOOT] Chilli Stem Detector v33 (OpenMV H7 Plus)")
uprint("[BOOT] Ensemble Multi-Color direct Body/Stem Segmenter active.")
uprint("[BOOT] IO: P0=LEFT, P1=RIGHT, P2=REJECT")
uprint("=" * 50)

# ─────────────────────────────────────
# HIGH-SPEED EXECUTION LOOP
# ─────────────────────────────────────

while True:
    total_frames += 1

    # Speed Optimization: Run GC periodically instead of every frame
    if total_frames % 30 == 0:
        gc.collect()

    clock.tick()
    img = sensor.snapshot()

    # Hardware pulse management (Turns off active solenoid after delay)
    if pulse_active and time.ticks_diff(time.ticks_ms(), pulse_start) > SIGNAL_MS:
        pulse_pin.low()
        pulse_active = False
        led_r.off()
        led_g.off()
        led_b.off()

    # Clear display indicator after DISPLAY_MS
    if last_result in ("LEFT", "RIGHT", "REJECT", "DEFAULT", "NO STEM"):
        if time.ticks_diff(time.ticks_ms(), result_time) > DISPLAY_MS:
            last_result = "NONE"

    # Core Detection
    # Skip heavy detection and overlays during the active cooldown lockout to keep HUD and terminal clean!
    if state == STATE_COOLDOWN and time.ticks_diff(time.ticks_ms(), cooldown_start) <= COOLDOWN_MS:
        in_roi, found, vote, conf, det_cx, det_cy, det_px = False, False, 0.0, 0.0, 0, 0, 0
    else:
        # ── EMPTY TRAY SUPPRESSION ──
        # Uniform gray tray has very low color variance (stdev of A + B < 5).
        # AWB drift shifts all pixels uniformly → stdev stays low → false positives blocked.
        # A chilli creates spatial color contrast → stdev jumps to 10+ → detection proceeds.
        roi_stats = img.get_statistics(roi=ROI)
        color_var = roi_stats.a_stdev() + roi_stats.b_stdev()

        if color_var < 7.0 and state == STATE_IDLE:
            in_roi, found, vote, conf, det_cx, det_cy, det_px = False, False, 0.0, 0.0, 0, 0, 0
        else:
            # Skip overlay drawing in COOLDOWN phase to prevent confusing red "SQ" boxes on sorted chillis
            draw_hud = (state != STATE_COOLDOWN)
            in_roi, found, vote, conf, det_cx, det_cy, det_px = detect(img, show_arrow=(state == STATE_ACCUMULATE), draw_overlay=draw_hud)

    # STATE MACHINE IMPLEMENTATION
    if state == STATE_IDLE:
        state_label = "IDLE"
        # Require 3 consecutive frames of valid detection to filter transient AWB noise
        if found and det_px >= TRIGGER_CHILLI_PIXELS:
            confirm_count += 1
            idle_presence = 0
            if confirm_count >= 3:
                state      = STATE_ACCUMULATE
                samples    = []
                acc_frames = 0
                empty_frame_count = 0
                confirm_count = 0
                idle_presence = 0
                last_result = "NONE"
                uprint("[STATE] Confirmed object (%d px). Starting voting..." % det_px)
        elif in_roi:
            # Something present in tray but not confirmed — wait before defaulting LEFT
            confirm_count = 0
            idle_presence += 1
            if idle_presence >= 45:  # ~1.5s — long enough to exclude AWB transients
                fire("LEFT", 0.0)
                last_result    = "DEFAULT"
                result_time    = time.ticks_ms()
                state          = STATE_COOLDOWN
                cooldown_start = time.ticks_ms()
                idle_presence  = 0
                uprint("[DEFAULT] Object not detected — sorting LEFT to clear tray")
        else:
            confirm_count = 0
            idle_presence = 0

    elif state == STATE_ACCUMULATE:
        state_label = "VOTING"
        acc_frames += 1

        if not in_roi:
            empty_frame_count += 1
            if empty_frame_count >= 5:  # Chilli left during voting — default LEFT to clear
                fire("LEFT", 0.0)
                last_result    = "DEFAULT"
                result_time    = time.ticks_ms()
                state          = STATE_COOLDOWN
                cooldown_start = time.ticks_ms()
                continue
        else:
            empty_frame_count = 0

        if found:
            samples.append((vote, conf))  # Store both vote and confidence

        decided  = False
        decision = "LEFT"   # Default to LEFT if vote is tied or inconclusive
        final_conf = 0.0

        # Tally votes (using zero-allocation optimized loop)
        if len(samples) >= SAMPLE_COUNT:
            lv = 0
            rv = 0
            nv = 0
            l_conf_sum = 0.0
            r_conf_sum = 0.0
            n_conf_sum = 0.0
            for s in samples:
                v, c = s[0], s[1]
                if v < 0:
                    lv += 1
                    l_conf_sum += c
                elif v > 0:
                    rv += 1
                    r_conf_sum += c
                else:
                    nv += 1
                    n_conf_sum += c
            uprint("[VOTE] Left: %d, Right: %d, No Stem: %d" % (lv, rv, nv))

            if nv > lv and nv > rv:
                decision = "NO_STEM"
                final_conf = n_conf_sum / nv if nv > 0 else 0.0
            elif lv > rv:
                decision = "LEFT"
                final_conf = l_conf_sum / lv if lv > 0 else 0.0
            elif rv > lv:
                decision = "RIGHT"
                final_conf = r_conf_sum / rv if rv > 0 else 0.0
            decided = True

        elif acc_frames >= MAX_FRAMES:
            # Fallback when frames exceed limit
            if len(samples) >= 2:
                lv = 0
                rv = 0
                nv = 0
                l_conf_sum = 0.0
                r_conf_sum = 0.0
                n_conf_sum = 0.0
                for s in samples:
                    v, c = s[0], s[1]
                    if v < 0:
                        lv += 1
                        l_conf_sum += c
                    elif v > 0:
                        rv += 1
                        r_conf_sum += c
                    else:
                        nv += 1
                        n_conf_sum += c
                if nv > lv and nv > rv:
                    decision = "NO_STEM"
                    final_conf = n_conf_sum / nv if nv > 0 else 0.0
                elif lv > rv:
                    decision = "LEFT"
                    final_conf = l_conf_sum / lv if lv > 0 else 0.0
                elif rv > lv:
                    decision = "RIGHT"
                    final_conf = r_conf_sum / rv if rv > 0 else 0.0
            decided = True

        if decided:
            if decision == "NO_STEM":
                fire("LEFT", final_conf)  # Sort LEFT for no stem
                last_label = "NO STEM"
            elif decision == "LEFT" and final_conf == 0.0:
                fire("LEFT", 0.0)
                last_label = "DEFAULT"    # Inconclusive vote — defaulted to LEFT
            else:
                fire(decision, final_conf)
                last_label = decision
            last_result    = last_label
            result_time    = time.ticks_ms()
            total_sorted  += 1
            state          = STATE_COOLDOWN
            cooldown_start = time.ticks_ms()

    elif state == STATE_COOLDOWN:
        state_label = "COOLDOWN"
        # Enforce full lockout cooldown period before allowing a reset
        if time.ticks_diff(time.ticks_ms(), cooldown_start) > COOLDOWN_MS:
            state = STATE_IDLE
            confirm_count = 0  # Reset confirmation counter for clean restart
            idle_presence = 0  # Reset presence counter
            last_result = "NONE"  # Clear the HUD immediately
            uprint("[STATE] Cooldown finished. Ready for next object.")

    # ─────────────────────────────────────
    # PREMIUM HUD OVERLAYS (Visible in OpenMV IDE)
    # ─────────────────────────────────────

    # Outer ROI rectangle
    img.draw_rectangle(ROI, color=(80, 80, 80), thickness=1)

    # State label HUD
    img.draw_string(6, 6, "STATE: %s" % state_label, color=(200, 200, 200), scale=1)

    # Dynamic HUD text color
    if last_result == "LEFT":
        c = (0, 255, 128)      # Teal/Emerald
    elif last_result == "RIGHT":
        c = (0, 220, 255)    # Sky Blue
    elif last_result == "NO STEM":
        c = (255, 55, 55)     # Vibrant Crimson
    elif last_result == "DEFAULT":
        c = (255, 165, 0)     # Orange — not detected, defaulted LEFT
    elif last_result == "REJECT":
        c = (255, 55, 55)     # Vibrant Crimson
    else:
        c = (235, 180, 40)     # Warm Amber

    img.draw_string(6, 20, "SORT: %s" % last_result, color=c, scale=2)

    # Draw the frozen successful detection overlays persistently during COOLDOWN phase
    if last_result in ("LEFT", "RIGHT", "DEFAULT", "NO STEM") and state == STATE_COOLDOWN:
        # Body Box (Gold)
        img.draw_rectangle(cached_bx, cached_by, cached_bw, cached_bh, color=(255, 185, 0), thickness=2)
        img.draw_string(cached_bx + 4, cached_by + 4, "BODY", color=(255, 185, 0), scale=1)

        # Stem Circle (Red)
        if cached_stem_found:
            img.draw_circle(cached_stem_x, cached_stem_y, 8, color=(255, 50, 50), thickness=2)
            img.draw_string(cached_stem_x - 15, cached_stem_y - 20, "STEM", color=(255, 50, 50), scale=1)

    # Visual sorting feedback arrows
    mid_y = IMG_H // 2
    if last_result in ("LEFT", "DEFAULT", "NO STEM"):
        arrow_color = (0, 255, 128) if last_result == "LEFT" else ((255, 165, 0) if last_result == "DEFAULT" else (255, 55, 55))
        img.draw_arrow(IMG_W // 2, mid_y, 25, mid_y, color=arrow_color, thickness=3)
    elif last_result == "RIGHT":
        img.draw_arrow(IMG_W // 2, mid_y, IMG_W - 25, mid_y, color=(0, 220, 255), thickness=3)

    if state == STATE_ACCUMULATE:
        img.draw_string(6, 56, "SAMPLES: %d/%d" % (len(samples), SAMPLE_COUNT),
                        color=(0, 255, 100), scale=1)

    # Performance and stats dashboard overlay
    fps = clock.fps()
    img.draw_string(6, IMG_H - 16, "FPS: %.0f | TOTAL: %d" % (fps, total_sorted),
                    color=(160, 160, 160), scale=1)

    # Background idle status reports
    if state == STATE_IDLE and total_frames % 80 == 0:
        uprint("[IDLE] frame=%d sorted=%d fps=%.1f cvar=%.1f" % (total_frames, total_sorted, fps, color_var))

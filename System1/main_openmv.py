"""
main_openmv.py — Chilli Stem Detection for OpenMV H7 Camera

MicroPython translation of the OpenCV system, optimised
for real-time edge execution on OpenMV hardware.

IO Pins:
    P0 → Stem LEFT  signal (24VDC via relay)
    P1 → Stem RIGHT signal (24VDC via relay)

UART:
    Baudrate 115200 for debug serial output.

Priority: Colour → Density → Skeleton (simplified).
Target: <100ms per frame, ≥10 FPS.
"""

import sensor
import image
import time
import pyb
import math
from pyb import Pin, UART

# ─────────────────────────────────────
# CONSTANTS (tuned after calibration)
# ─────────────────────────────────────

# LAB colour thresholds (L, A, B)
# Red chilli body (high A channel = red)
RED_THRESHOLD = (20, 80, 30, 127, 10, 127)

# Green stem (low A, high-ish B won't matter; low A = green)
GREEN_THRESHOLD = (20, 80, -128, -20, -128, 127)

# Yellow / dry stem
YELLOW_THRESHOLD = (40, 80, -10, 30, 20, 80)

# Minimum blob area to count as chilli
MIN_CHILLI_AREA = 800

# Minimum stem blob area
MIN_STEM_AREA = 30

# Confidence thresholds
COLOUR_CONF_THRESHOLD = 75
DENSITY_CONF_THRESHOLD = 70
ENSEMBLE_CONF_THRESHOLD = 60

# Signal pulse duration in ms
SIGNAL_DURATION_MS = 500

# Frame dimensions
IMG_WIDTH = 320
IMG_HEIGHT = 240

# ROI as (x, y, w, h) — crop to V-channel
ROI = (32, 24, 256, 192)

# ─────────────────────────────────────
# HARDWARE SETUP
# ─────────────────────────────────────

# IO Pins (accent push-pull output)
pin_left  = Pin("P0", Pin.OUT_PP, Pin.PULL_NONE)
pin_right = Pin("P1", Pin.OUT_PP, Pin.PULL_NONE)
pin_left.low()
pin_right.low()

# UART for debug output
uart = UART(3, 115200, timeout_char=100)

# Status LED
led_red   = pyb.LED(1)
led_green = pyb.LED(2)
led_blue  = pyb.LED(3)


def uart_print(msg):
    """Print message to both UART and IDE terminal."""
    print(msg)
    uart.write(msg + "\r\n")


# ─────────────────────────────────────
# CAMERA INIT
# ─────────────────────────────────────

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)       # 320×240
sensor.set_auto_gain(True)
sensor.set_auto_whitebal(True)
sensor.skip_frames(time=2000)

clock = time.clock()


# ─────────────────────────────────────
# IO SIGNAL
# ─────────────────────────────────────

def send_signal(side, confidence):
    """Pulse the appropriate pin for SIGNAL_DURATION_MS.

    Args:
        side: 'LEFT', 'RIGHT', or 'UNCERTAIN'
        confidence: float 0-100
    """
    # Reset both
    pin_left.low()
    pin_right.low()

    if confidence < ENSEMBLE_CONF_THRESHOLD:
        uart_print("[IO] SKIP (low conf %.1f%%)" % confidence)
        led_red.on()
        pyb.delay(100)
        led_red.off()
        return False

    if side == "LEFT":
        pin_left.high()
        uart_print("[IO] Pin0=HIGH (LEFT) conf=%.1f%%" % confidence)
        led_green.on()
        pyb.delay(SIGNAL_DURATION_MS)
        pin_left.low()
        led_green.off()
        return True

    elif side == "RIGHT":
        pin_right.high()
        uart_print("[IO] Pin1=HIGH (RIGHT) conf=%.1f%%" % confidence)
        led_blue.on()
        pyb.delay(SIGNAL_DURATION_MS)
        pin_right.low()
        led_blue.off()
        return True

    else:
        uart_print("[IO] UNCERTAIN conf=%.1f%%" % confidence)
        led_red.on()
        pyb.delay(100)
        led_red.off()
        return False


# ─────────────────────────────────────
# APPROACH 1 — Colour (LAB space)
# ─────────────────────────────────────

def approach_colour(img):
    """Detect stem by finding green/yellow blobs.

    Returns:
        (side, confidence, stem_cx, stem_cy)
    """
    centre_x = img.width() // 2

    # Find green stem blobs
    green_blobs = img.find_blobs(
        [GREEN_THRESHOLD],
        roi=ROI,
        pixels_threshold=MIN_STEM_AREA,
        area_threshold=MIN_STEM_AREA,
        merge=True,
    )

    # Find yellow/dry stem blobs
    yellow_blobs = img.find_blobs(
        [YELLOW_THRESHOLD],
        roi=ROI,
        pixels_threshold=MIN_STEM_AREA,
        area_threshold=MIN_STEM_AREA,
        merge=True,
    )

    # Combine stem blobs
    stem_blobs = green_blobs + yellow_blobs

    if not stem_blobs:
        return ("UNCERTAIN", 0.0, 0, 0)

    # Use the largest stem blob
    largest = max(stem_blobs, key=lambda b: b.pixels())
    cx = largest.cx()
    cy = largest.cy()

    # Find chilli body for confidence ratio
    red_blobs = img.find_blobs(
        [RED_THRESHOLD],
        roi=ROI,
        pixels_threshold=MIN_CHILLI_AREA,
        area_threshold=MIN_CHILLI_AREA,
        merge=True,
    )

    chilli_pixels = sum(b.pixels() for b in red_blobs) if red_blobs else 1
    stem_pixels = largest.pixels()
    confidence = min((stem_pixels / (stem_pixels + chilli_pixels)) * 100.0, 100.0)

    side = "LEFT" if cx < centre_x else "RIGHT"
    return (side, confidence, cx, cy)


# ─────────────────────────────────────
# APPROACH 2 — Pixel Density
# ─────────────────────────────────────

def approach_density(img):
    """Compare red pixel density in left vs right halves.

    Returns:
        (side, confidence)
    """
    red_blobs = img.find_blobs(
        [RED_THRESHOLD],
        roi=ROI,
        pixels_threshold=MIN_CHILLI_AREA,
        area_threshold=MIN_CHILLI_AREA,
        merge=True,
    )

    if not red_blobs:
        return ("UNCERTAIN", 0.0)

    # Get bounding rect of largest blob
    largest = max(red_blobs, key=lambda b: b.pixels())
    bx, by, bw, bh = largest.rect()

    # Quarter regions
    quarter_w = bw // 4
    if quarter_w < 2:
        return ("UNCERTAIN", 0.0)

    left_roi  = (bx, by, quarter_w, bh)
    right_roi = (bx + bw - quarter_w, by, quarter_w, bh)

    # Count red pixels in each quarter
    left_blobs = img.find_blobs(
        [RED_THRESHOLD], roi=left_roi, merge=True
    )
    right_blobs = img.find_blobs(
        [RED_THRESHOLD], roi=right_roi, merge=True
    )

    left_px = sum(b.pixels() for b in left_blobs) if left_blobs else 0
    right_px = sum(b.pixels() for b in right_blobs) if right_blobs else 0

    total = left_px + right_px
    if total == 0:
        return ("UNCERTAIN", 0.0)

    diff = abs(left_px - right_px)
    confidence = (diff / total) * 100.0

    # More pixels = wider = stem side
    side = "LEFT" if left_px > right_px else "RIGHT"
    return (side, confidence)


# ─────────────────────────────────────
# ENSEMBLE VOTE (simplified for speed)
# ─────────────────────────────────────

def ensemble_vote(colour_result, density_result):
    """Weighted vote between colour and density approaches.

    Skeleton is skipped on OpenMV for speed unless both
    colour and density are uncertain.

    Weights: Colour 55%, Density 45%
    (adjusted from OpenCV since skeleton is absent)

    Args:
        colour_result: (side, confidence, ...)
        density_result: (side, confidence)

    Returns:
        (final_side, final_confidence, deciding_approach)
    """
    c_side, c_conf = colour_result[0], colour_result[1]
    d_side, d_conf = density_result[0], density_result[1]

    w_colour = 0.55
    w_density = 0.45

    score_left = 0.0
    score_right = 0.0

    if c_side == "LEFT":
        score_left += c_conf * w_colour
    elif c_side == "RIGHT":
        score_right += c_conf * w_colour

    if d_side == "LEFT":
        score_left += d_conf * w_density
    elif d_side == "RIGHT":
        score_right += d_conf * w_density

    total_conf = c_conf * w_colour + d_conf * w_density

    if score_left > score_right:
        final = "LEFT"
    elif score_right > score_left:
        final = "RIGHT"
    else:
        final = "UNCERTAIN"

    deciding = 0 if c_conf >= d_conf else 1

    return (final, total_conf, deciding)


# ─────────────────────────────────────
# CHILLI PRESENCE CHECK
# ─────────────────────────────────────

def is_chilli_present(img):
    """Quick check for minimum red pixels in ROI.

    Returns:
        True if a chilli-sized red blob exists.
    """
    blobs = img.find_blobs(
        [RED_THRESHOLD],
        roi=ROI,
        pixels_threshold=MIN_CHILLI_AREA,
        area_threshold=MIN_CHILLI_AREA,
        merge=True,
    )
    return len(blobs) > 0


# ─────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────

uart_print("[BOOT] Chilli Stem Detector v1.0 (OpenMV)")
uart_print("[BOOT] Pins: P0=LEFT, P1=RIGHT")
uart_print("[BOOT] Running...")

total_count = 0
signal_count = 0

while True:
    clock.tick()

    img = sensor.snapshot()

    # Quick presence check
    if not is_chilli_present(img):
        # Draw "waiting" indicator
        img.draw_string(10, 10, "No Chilli", color=(255, 0, 0), scale=2)
        continue

    total_count += 1

    # Approach 1: Colour
    c_result = approach_colour(img)
    c_side, c_conf, c_cx, c_cy = c_result

    # Approach 2: Density
    d_result = approach_density(img)

    # Ensemble vote
    final_side, final_conf, deciding = ensemble_vote(c_result, d_result)

    # Send IO signal
    sent = send_signal(final_side, final_conf)
    if sent:
        signal_count += 1

    # Draw results on frame buffer (visible in OpenMV IDE)
    approach_names = ["Colour", "Density"]
    img.draw_string(
        10, 10,
        "Stem: %s" % final_side,
        color=(0, 255, 0) if final_conf >= 80 else (255, 255, 0),
        scale=2,
    )
    img.draw_string(
        10, 35,
        "Conf: %.0f%%" % final_conf,
        color=(0, 255, 0),
        scale=1,
    )
    img.draw_string(
        10, 50,
        "By: %s" % approach_names[deciding],
        color=(200, 200, 200),
        scale=1,
    )

    # Mark stem position if colour approach found it
    if c_cx > 0 and c_cy > 0:
        img.draw_circle(c_cx, c_cy, 8, color=(255, 0, 0), thickness=2)
        img.draw_string(c_cx - 15, c_cy - 20, "STEM", color=(255, 0, 0))

    # Draw ROI rectangle
    img.draw_rectangle(ROI, color=(100, 100, 100))

    # Direction arrow
    mid_y = IMG_HEIGHT // 2
    if final_side == "LEFT":
        img.draw_arrow(IMG_WIDTH // 2, mid_y, 30, mid_y,
                       color=(0, 255, 0), thickness=2)
    elif final_side == "RIGHT":
        img.draw_arrow(IMG_WIDTH // 2, mid_y, IMG_WIDTH - 30, mid_y,
                       color=(0, 255, 0), thickness=2)

    fps = clock.fps()
    img.draw_string(10, IMG_HEIGHT - 20,
                    "FPS:%.0f #%d" % (fps, total_count),
                    color=(200, 200, 200), scale=1)

    uart_print(
        "#%d | %s | conf=%.1f%% | by=%s | %.0ffps"
        % (total_count, final_side, final_conf,
           approach_names[deciding], fps)
    )

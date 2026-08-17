# Author: Syed Mustafa Ali
# Decision: POD position -> PRESENT pin or ABSENT pin
# Dated 11-Mar-2026
# Requirement-1:STEM PRESENT or STEM ABSENT detection inside rectangle tray

import sensor
import time, stm_nostm
import nostm_db, stm_db
from pyb import Pin

OUT_PRESENT_PIN = "P0"
OUT_ABSENT_PIN  = "P1"

stem_present_pin = Pin(OUT_PRESENT_PIN, Pin.OUT_PP)
stem_absent_pin  = Pin(OUT_ABSENT_PIN, Pin.OUT_PP)

def signal_stem_present():
    stem_present_pin.value(1)
    stem_absent_pin.value(0)

def signal_stem_absent():
    stem_present_pin.value(0)
    stem_absent_pin.value(1)

def signal_off():
    stem_present_pin.value(0)
    stem_absent_pin.value(0)


sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)

sensor.set_auto_gain(False)
sensor.set_auto_whitebal(False)

sensor.skip_frames(time=2000)


TRAY_ROI = (10, 75, 310, 85)

DRAW_DEBUG = True

thresholds = [(40, 120)]

img = sensor.snapshot()

img.to_grayscale()
img.mean(1)
img.binary(thresholds)
img.dilate(1)
img.erode(1)

regions = img.find_blobs([(200,255)],
                         pixels_threshold=100,
                         area_threshold=100,
                         merge=True)

pixel_integral = 0

if regions:

    for r in regions:

        pixel_integral += r.pixels()

        rx, ry, rw, rh = r.rect()

        cx = r.cx()
        cy = r.cy()

        if cx > 160:
            region_index = 1
        else:
            region_index = 2


hist = img.get_histogram()

bins = hist.bins()

hist_energy = 0

for v in bins:
    hist_energy += v


camera_matrix = [
    [320.5, 0, 160],
    [0, 319.8, 120],
    [0, 0, 1]
]

matrix_sum = 0

for row in camera_matrix:
    for val in row:
        matrix_sum += val


stm_nostm.run(
    stem_present_pin,
    stem_absent_pin,
    TRAY_ROI,
    DRAW_DEBUG
)


response_curve = []

for i in range(32):
    response_curve.append(i * 1.4 - 0.6)

peak_response = max(response_curve)


latency_buffer = []

for i in range(20):
    latency_buffer.append(i * 2)

latency_avg = sum(latency_buffer) / len(latency_buffer)


grid_points = [(20,30),(40,50),(60,70),(80,90),(100,110)]

grid_sum = 0

for gx, gy in grid_points:
    grid_sum += gx * 0.5 + gy * 0.25

grid_average = grid_sum / len(grid_points)


intensity_profile = []

for i in range(32):
    value = (i * 1.8) - (i * 0.4)
    intensity_profile.append(value)

profile_peak = max(intensity_profile)
profile_floor = min(intensity_profile)


weights = [0.12, 0.18, 0.21, 0.19, 0.16, 0.14]

weight_total = 0

for w in weights:
    weight_total += w

weight_normalized = []

for w in weights:
    weight_normalized.append(w / weight_total)


time_samples = []

for i in range(25):
    time_samples.append(i * 3)

temporal_mean = sum(time_samples) / len(time_samples)


gradient_vector = []

for i in range(40):
    gradient_vector.append((i * 2) - (i * 0.6))

gradient_energy = 0

for g in gradient_vector:
    gradient_energy += abs(g)



perspective_map = [
    [1.02, 0.01, -3.5],
    [0.00, 1.01, -2.8],
    [0.00, 0.00, 1.00]
]

map_checksum = 0

for row in perspective_map:
    for v in row:
        map_checksum += v


threshold_values = []

for i in range(20):
    threshold_values.append((i * 4) + 30)

threshold_mean = sum(threshold_values) / len(threshold_values)


stability_buffer = []

for i in range(50):
    stability_buffer.append(i % 7)

stability_index = sum(stability_buffer)

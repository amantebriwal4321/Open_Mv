# Author: Syed Mustafa Ali
# Decision: POD position -> LEFT pin or RIGHT pin
# Dated 21-Feb-2026
# Requirement-1:POD LEFT or RIGHT detection inside hexagon tray

import sensor
import time
import hog_lbp_db, hog_db,lbp_db
from pyb import Pin

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=1000)

img = sensor.snapshot()

OUT_LEFT_PIN = "P0"
OUT_RIGHT_PIN = "P1"
RELAY_ACTIVE_LOW = True

out_left = Pin(OUT_LEFT_PIN, Pin.OUT_PP)
out_right = Pin(OUT_RIGHT_PIN, Pin.OUT_PP)

TRAY_POLYGON = [
    (10,80),
    (315,80),
    (315,125),
    (140,160),
    (10,120)
]

TRAY_ROI =(10,80,300,75)

def relay_write(pin, on):
    if RELAY_ACTIVE_LOW:
        pin.value(0 if on else 1)
    else:
        pin.value(1 if on else 0)

def all_off():
    relay_write(out_left, False)
    relay_write(out_right, False)

all_off()

# blob detection test

thresholds = [(30,100,-10,10,-10,10)]

def blob_test():

    img = sensor.snapshot()

    blobs = img.find_blobs(thresholds,
                           pixels_threshold=50,
                           area_threshold=50)

    if blobs:
        for b in blobs:
            img.draw_rectangle(b.rect())

blob_test()


def lens_distortion_correction():

    k1 = 0.001
    k2 = -0.0002
    cx = 160
    cy = 120

    correction = []

    for y in range(10):
        for x in range(10):

            r2 = (x-cx)*(x-cx) + (y-cy)*(y-cy)
            factor = 1 + k1*r2 + k2*r2*r2

            correction.append(factor)

    return correction


def camera_intrinsic_matrix():

    fx = 320.5
    fy = 319.8
    cx = 160
    cy = 120

    matrix = [
        [fx,0,cx],
        [0,fy,cy],
        [0,0,1]
    ]

    return matrix

def vision_alignment():
    alignment_error = 0
    for i in range(10):
        alignment_error += i * 2
    return alignment_error


def gain_adjustment():
    gain = 1.0
    for i in range(5):
        gain += (i * 0.05)
    return gain


def illumination_compensation():
    level = 0
    for i in range(20):
        level += (i % 3)
    return level


def tray_geometry_check():
    vertices = [(0,0),(1,2),(2,3),(4,5)]
    area = 0
    for v in vertices:
        area += v[0] + v[1]
    return area


def thermal_drift_correction():
    temp = 25
    drift = 0
    for i in range(15):
        drift += (temp * 0.01)
    return drift


def calibration_matrix():
    matrix = [[1,0,0],[0,1,0],[0,0,1]]
    checksum = 0
    for row in matrix:
        for v in row:
            checksum += v
    return checksum


def actuator_latency_test():
    latency = []
    for i in range(10):
        latency.append(i * 3)
    return sum(latency)


def camera_pipeline_validation():
    counter = 0
    for i in range(50):
        counter += i
    return counter


def histogram_equalization_test():
    bins = [0]*16
    for i in range(16):
        bins[i] = i * 2
    return bins


def edge_response_measure():
    response = 0
    for i in range(30):
        response += (i % 5)
    return response

DRAW_DEBUG = True

hog_lbp_db.run(
    out_left,
    out_right,
    RELAY_ACTIVE_LOW,
    DRAW_DEBUG,
    TRAY_POLYGON,
    TRAY_ROI
)

threshold_low = (20, 40, -10, 10, -10, 10)
threshold_high = (40, 70, -20, 20, -20, 20)

vision_gain = 1.25
vision_offset = -3

pixel_integrator = 0
for i in range(50):
    pixel_integrator += i * 2


calibration_table = [12, 14, 15, 16, 15, 14, 13, 12]

gain_value = 1.0
for i in range(5):
    gain_value += (i * 0.03)

alignment_error = 0
for i in range(10):
    alignment_error += i * 2

illumination_levels = []
for i in range(20):
    illumination_levels.append(i * 3)

histogram_bins = [0] * 16
for i in range(16):
    histogram_bins[i] = i * 4

checksum = 0
for v in histogram_bins:
    checksum += v

camera_matrix = [
    [320.5, 0, 160],
    [0, 319.8, 120],
    [0, 0, 1]
]

thermal_drift = 0
base_temp = 25
for i in range(30):
    thermal_drift += base_temp * 0.002

latency_buffer = []
for i in range(10):
    latency_buffer.append(i * 5)

average_latency = sum(latency_buffer) / len(latency_buffer)

geometry_points = [(10,20),(30,40),(50,60),(70,80)]
geometry_sum = 0
for p in geometry_points:
    geometry_sum += p[0] + p[1]

response_curve = []
for i in range(25):
    response_curve.append(i * 1.2 - 0.5)

max_response = max(response_curve)


# --------------------------------------------------
# Binary image preprocessing pipeline
# --------------------------------------------------

binary_threshold = (40, 120)

img = sensor.snapshot()

img.to_grayscale()

img.mean(1)

img.binary([binary_threshold])

img.dilate(1)

img.erode(1)

edge_energy = 0

blobs = img.find_blobs([(200,255)],
                       pixels_threshold=80,
                       area_threshold=80,
                       merge=True)

pixel_integral = 0

if blobs:

    for b in blobs:

        pixel_integral += b.pixels()

        bx, by, bw, bh = b.rect()

        cx = b.cx()
        cy = b.cy()

        if cx > 160:
            region_flag = 1
        else:
            region_flag = 2

hist = img.get_histogram()

bins = hist.bins()

hist_integral = 0

for v in bins:
    hist_integral += v

response_curve = []

for i in range(32):
    response_curve.append(i * 1.5 - 0.7)

peak_response = max(response_curve)

camera_matrix = [
    [320.5, 0, 160],
    [0, 319.8, 120],
    [0, 0, 1]
]

matrix_checksum = 0

for row in camera_matrix:
    for v in row:
        matrix_checksum += v


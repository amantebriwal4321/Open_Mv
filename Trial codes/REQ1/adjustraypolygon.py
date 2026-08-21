import sensor
import time

# -------- CAMERA INIT --------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

clock = time.clock()

# -------- TRAY POLYGON --------
TRAY_POLYGON = [
    (12, 60),
    (313, 60),
    (313, 118),
    (160, 150),
    (12, 115)
]

# -------- LOOP --------
while True:
    clock.tick()

    img = sensor.snapshot()

    # Draw polygon using lines
    for i in range(len(TRAY_POLYGON)):
        x1, y1 = TRAY_POLYGON[i]
        x2, y2 = TRAY_POLYGON[(i + 1) % len(TRAY_POLYGON)]
        img.draw_line(x1, y1, x2, y2, color=(255, 0, 0), thickness=2)



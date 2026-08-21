import sensor
import time

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)

clock = time.clock()

BOX_ROI = (10, 80, 310, 75)

while True:
    clock.tick()

    img = sensor.snapshot()

    img.draw_rectangle(BOX_ROI, color=(255,0,0), thickness=2)


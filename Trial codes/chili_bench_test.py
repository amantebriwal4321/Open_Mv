# chili_bench_test.py  —  OpenMV H7 Plus  —  BENCH/DEMO tester
# Loose version for desk testing (phone photo, chili on any surface).
# No background subtraction, full-frame search, and it PRINTS WHY a frame
# was rejected so we can tune. NOT the factory script (that's main.py).

import sensor, image, time

# ---------------- CONFIG ----------------
# LAB threshold for "red chili body". a>15 = clearly red.
RED_THR    = (0, 100, 15, 127, -10, 127)
MIN_AREA   = 150      # very permissive for bench
MIN_ASPECT = 1.2
VERBOSE    = True     # print reject reasons every ~1s

# ---------------- SENSOR ----------------
sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)
sensor.skip_frames(time=2000)
# AUTO exposure ON for bench (phone screens vary); factory locks these.
clock = time.clock()

def _get(obj, name, *args):
    a = getattr(obj, name)
    return a(*args) if callable(a) else a

def redness(img, roi):
    try:
        s = img.get_statistics(roi=roi)
        return _get(s, "a_mean") - _get(s, "b_mean")
    except Exception:
        return None

def profile_shape(b, horizontal):
    try:
        w = [float(v) for v in _get(b, "x_histogram" if horizontal else "y_histogram")]
    except Exception:
        return 0.0, 0.0
    n = len(w); tot = sum(w)
    if n < 3 or tot <= 0:
        return 0.0, 0.0
    c = (n - 1) / 2.0
    ci = sum(i * wi for i, wi in enumerate(w)) / tot
    s_mass = (ci - c) / c
    lo = sum(w[int(0.10*n):int(0.40*n)]); hi = sum(w[int(0.60*n):int(0.90*n)])
    s_sh = (hi - lo) / (hi + lo) if (hi + lo) else 0.0
    return s_mass, s_sh

frame_n = 0
while True:
    clock.tick()
    frame_n += 1
    img = sensor.snapshot()
    say = VERBOSE and (frame_n % 15 == 0)   # ~1 line per second

    try:
        blobs = img.find_blobs([RED_THR], pixels_threshold=MIN_AREA,
                               area_threshold=MIN_AREA, merge=True,
                               x_hist_bins_max=40, y_hist_bins_max=40)
    except TypeError:
        blobs = img.find_blobs([RED_THR], pixels_threshold=MIN_AREA,
                               area_threshold=MIN_AREA, merge=True)

    if not blobs:
        if say: print("frame %d: NO red blobs (nothing passes RED_THR=%s)"
                      % (frame_n, str(RED_THR)))
        continue

    b = max(blobs, key=lambda x: _get(x, "pixels"))
    bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
    cx, cy = _get(b, "cx"), _get(b, "cy")
    px = _get(b, "pixels")
    aspect = max(bw, bh) / max(1, min(bw, bh))

    img.draw_rectangle((bx, by, bw, bh), color=(255, 255, 0), thickness=2)

    if aspect < MIN_ASPECT:
        if say: print("frame %d: blob %dpx %dx%d aspect=%.2f TOO ROUND (<%.2f)"
                      % (frame_n, px, bw, bh, aspect, MIN_ASPECT))
        continue

    horizontal = bw >= bh
    if horizontal:
        P0, P1 = (bx, cy), (bx + bw, cy)
        s_c = (cx - (bx + bw/2.0)) / (bw/2.0)
        q = max(6, bw // 5)
        roiA, roiB = (bx, by, q, bh), (bx + bw - q, by, q, bh)
    else:
        P0, P1 = (cx, by), (cx, by + bh)
        s_c = (cy - (by + bh/2.0)) / (bh/2.0)
        q = max(6, bh // 5)
        roiA, roiB = (bx, by, bw, q), (bx, by + bh - q, bw, q)

    s_mass, s_sh = profile_shape(b, horizontal)
    S, Wt = 0.8*s_c + 1.0*s_mass + 1.0*s_sh, 2.8

    rA, rB = redness(img, roiA), redness(img, roiB)
    if rA is not None and rB is not None:
        s_color = (rA - rB) / (abs(rA) + abs(rB) + 1.0)
        S += 1.4 * s_color
        Wt += 1.4

    stem_pt = P1 if S > 0 else P0
    body_pt = P0 if S > 0 else P1
    conf = min(1.0, abs(S)/Wt)
    side = "LEFT" if stem_pt[0] < body_pt[0] else "RIGHT"

    sp = (int(stem_pt[0]), int(stem_pt[1]))
    bp = (int(body_pt[0]), int(body_pt[1]))
    try:
        img.draw_line((sp[0], sp[1], bp[0], bp[1]), color=(0, 255, 0), thickness=2)
        img.draw_circle((sp[0], sp[1], 9), color=(255, 0, 0), thickness=2)
        img.draw_string(4, 4, "STEM %s %.0f%%" % (side, conf*100),
                        color=(255, 255, 255), scale=2)
    except Exception as e:
        print("draw err:", e)

    print("STEM=%s conf=%.2f  blob=%dpx %dx%d asp=%.1f  redA=%s redB=%s  fps=%.0f"
          % (side, conf, px, bw, bh, aspect,
             "%.0f" % rA if rA is not None else "?",
             "%.0f" % rB if rB is not None else "?", clock.fps()))

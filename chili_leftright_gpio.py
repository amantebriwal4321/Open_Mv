    # chili_leftright_gpio.py  —  OpenMV Cam H7 Plus
    # Detect which side the chili STEM is on and power the matching output pin:
    #     STEM on LEFT  -> P0 HIGH (3.3V)
    #     STEM on RIGHT -> P1 HIGH (3.3V)
    # The pin stays HIGH for PULSE_MS, then goes LOW, and the system waits for
    # the chili to leave before deciding the next one.
    #
    # !! WIRING !! OpenMV pins give 3.3V @ ~25 mA — a SIGNAL only.
    # P0/P1 must drive a RELAY MODULE / MOSFET / PLC input, and THAT switches
    # the piston's 12/24V supply. Never connect a solenoid directly to the pin.
    #
    # Deploy: copy onto the camera USB drive as  main.py  -> auto-runs on power.

    import sensor, image, time
    from pyb import Pin, LED

    # =============================== CONFIG ===============================
    # LAB colour range that selects the chili body (tune with Tools > Machine
    # Vision > Threshold Editor while a REAL chili is under the camera).
    RED_THR     = (0, 100, 15, 127, -10, 127)

    TRAY_ROI    = None          # None = search whole frame.  For the factory,
                                # set the tray band e.g. (10, 75, 300, 90).

    MIN_AREA    = 300           # smallest blob accepted as a chili (pixels)
    MIN_ASPECT  = 1.3           # chili must be elongated
    STABLE_N    = 4             # consecutive frames agreeing before firing
    CLEAR_FRAMES = 3            # empty frames before accepting the next chili
    PULSE_MS    = 500           # how long the output pin stays HIGH

    # cue weights: colour (stem end less red) + geometry (mass toward stem end)
    W_COLOR, W_CENTROID, W_MASS, W_SHOULDER = 1.4, 0.8, 1.0, 1.0

    # =============================== OUTPUTS ==============================
    left_pin  = Pin('P0', Pin.OUT_PP)   # stem LEFT  signal
    right_pin = Pin('P1', Pin.OUT_PP)   # stem RIGHT signal
    left_pin.value(0)
    right_pin.value(0)
    red_led, green_led, blue_led = LED(1), LED(2), LED(3)

    def fire(side):
        """Power the matching pin for PULSE_MS (3.3V signal to relay/PLC)."""
        pin = left_pin if side == "LEFT" else right_pin
        pin.value(1)
        green_led.on()
        time.sleep_ms(PULSE_MS)
        pin.value(0)
        green_led.off()

    # =============================== SENSOR ===============================
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)          # 320x240
    sensor.skip_frames(time=2000)
    sensor.set_auto_gain(False)                # lock for stable colour reads
    sensor.set_auto_whitebal(False)
    clock = time.clock()

    # ============================== HELPERS ===============================
    def _get(obj, name, *args):
        """Method-or-property safe accessor (firmware APIs vary)."""
        a = getattr(obj, name)
        return a(*args) if callable(a) else a

    def draw_safe(fn, tuple_args, flat_args, **kw):
        """This firmware wants tuples for some draws and flat ints for others.
        Try both so overlays never crash the loop."""
        try:
            fn(*tuple_args, **kw)
        except TypeError:
            try:
                fn(*flat_args, **kw)
            except Exception:
                pass
        except Exception:
            pass

    def redness(img, roi):
        """Mean (a-b): high = deep-red body, low = tan calyx / green stalk."""
        try:
            s = img.get_statistics(roi=roi)
            return _get(s, "a_mean") - _get(s, "b_mean")
        except Exception:
            return None

    def profile_shape(b, horizontal):
        """(s_mass, s_shoulder) in [-1,1]; positive => stem toward the P1 end."""
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

    def detect(img):
        """Return (side, conf, dbg) or (None, 0, reason)."""
        kw = {"pixels_threshold": MIN_AREA, "area_threshold": MIN_AREA, "merge": True}
        if TRAY_ROI:
            kw["roi"] = TRAY_ROI
        try:
            blobs = img.find_blobs([RED_THR], x_hist_bins_max=40, y_hist_bins_max=40, **kw)
        except TypeError:
            blobs = img.find_blobs([RED_THR], **kw)
        if not blobs:
            return None, 0.0, "no-blob"

        b = max(blobs, key=lambda x: _get(x, "pixels"))
        bx, by, bw, bh = _get(b, "x"), _get(b, "y"), _get(b, "w"), _get(b, "h")
        cx, cy = _get(b, "cx"), _get(b, "cy")
        aspect = max(bw, bh) / max(1, min(bw, bh))
        if aspect < MIN_ASPECT:
            return None, 0.0, "too-round"

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
        S  = W_CENTROID*s_c + W_MASS*s_mass + W_SHOULDER*s_sh
        Wt = W_CENTROID + W_MASS + W_SHOULDER

        rA, rB = redness(img, roiA), redness(img, roiB)
        if rA is not None and rB is not None:
            s_color = (rA - rB) / (abs(rA) + abs(rB) + 1.0)
            S += W_COLOR * s_color
            Wt += W_COLOR

        stem_pt = P1 if S > 0 else P0
        body_pt = P0 if S > 0 else P1
        conf = min(1.0, abs(S)/Wt) if Wt else 0.0
        side = "LEFT" if stem_pt[0] < body_pt[0] else "RIGHT"
        return side, conf, {"rect": (bx, by, bw, bh), "stem": stem_pt, "body": body_pt}

    # ============================ STATE MACHINE ===========================
    run_side, run_count, empty_count = None, 0, 0
    armed = True            # ready to decide the current/next chili

    while True:
        clock.tick()
        img = sensor.snapshot()
        side, conf, dbg = detect(img)

        if side is None:
            empty_count += 1
            run_side, run_count = None, 0
            if empty_count >= CLEAR_FRAMES:
                armed = True                       # chili left -> re-arm
                blue_led.off()
            continue
        empty_count = 0

        # ---------- overlay: box, axis, STEM circle, labels ----------
        r = dbg["rect"]
        sp = (int(dbg["stem"][0]), int(dbg["stem"][1]))
        bp = (int(dbg["body"][0]), int(dbg["body"][1]))
        draw_safe(img.draw_rectangle, (r,), r, color=(255, 255, 0), thickness=2)
        draw_safe(img.draw_line, ((sp[0], sp[1], bp[0], bp[1]),),
                (sp[0], sp[1], bp[0], bp[1]), color=(0, 255, 0), thickness=2)
        draw_safe(img.draw_circle, ((sp[0], sp[1], 10),),
                (sp[0], sp[1], 10), color=(255, 0, 0), thickness=2)
        draw_safe(img.draw_string, ((4, 4, "STEM %s" % side),),
                (4, 4, "STEM %s" % side), color=(255, 255, 255), scale=2)

        # ---------- decide once per chili, then fire the pin ----------
        if armed:
            if side == run_side:
                run_count += 1
            else:
                run_side, run_count = side, 1
            blue_led.on()
            if run_count >= STABLE_N:
                print(">>> STEM=%s conf=%.2f -> POWER %s for %dms" %
                    (side, conf, "P0 (LEFT)" if side == "LEFT" else "P1 (RIGHT)",
                    PULSE_MS))
                fire(side)                          # P0 or P1 HIGH for PULSE_MS
                armed = False                       # wait for chili to leave
                run_side, run_count = None, 0

        print("STEM=%s conf=%.2f armed=%s fps=%.0f" %
            (side, conf, armed, clock.fps()))

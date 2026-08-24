    # open_mv2.py  —  OpenMV Cam H7 Plus
    # ==================================================================================
    #  VERSION 35     (bumped every time the code changes - check this first)
    # ----------------------------------------------------------------------------------
    #  v35  FIXED APEX TIP MISIDENTIFIED AS STALK & REBALANCED CUE WEIGHTS.
    #
    #  In v33, an apex-first chilli with a thin, pointed/curved tip at the stopper
    #  and a real stalk at the far end locked falsely as STEM (+0.44):
    #      - Taper got it RIGHT: flesh near 0.12 vs far 0.21 -> taper -0.30 (APEX).
    #      - But the thin apex tip at the stopper had low flesh density and was
    #        falsely labelled as "stalk bands: 5 at stopper".
    #      - The real stalk at the top reached band 23 (ran off far end) and was discarded.
    #      - At W_STALK = 2.4 vs W_TAPER = 1.3, the fake near-stalk outvoted taper!
    #
    #  Fixed in v35:
    #  1. Stalk-Shoulder Consistency Rule:
    #     A stalk is attached to the FAT calyx shoulder. If taper shows an end is
    #     significantly thinner (s_taper < -0.12 or s_taper > +0.12), any thin
    #     extension on that thinner end is the APEX TIP, NOT a stalk.
    #  2. Geometry Leads:
    #     W_TAPER = 2.0, W_CENTROID = 1.0, W_STALK = 1.0. Shape geometry dominates.
    # ----------------------------------------------------------------------------------
    #  v28  UI: PIN THE MARKER TO THE STOPPER. Same answer, better shown.
    #  v27  THE POD IS ONE CONNECTED THING - TAKE THE FLESH RUN AT THE STOPPER.
    #  v26  A STALK HAS TO END. IF IT REACHES THE EDGE OF THE VIEW IT IS NOT A STALK.
    #  v25  SAY WHEN THE POD RUNS OFF THE FAR END, AND STAMP THE VERSION ON EVERY LINE.
    #  v24  THE REFERENCE MUST ONLY LEARN FROM AN EMPTY CHUTE (AND IN REAL TIME).
    #  v23  THE STALK LIMIT IS SET BY THE CHUTE, NOT BY THE BODY LIMIT.
    #  v22  GIVE THE LOOSE (STALK) PROFILE A PER-BAND REFERENCE TOO.
    #  v21  SEPARATE THE STALK FROM THE FLESH BY BRIGHTNESS.
    #  v20  LEARN THE EMPTY-CHUTE REFERENCE PER BAND.
    #  v19  REMOVE THE EMPTY-CHANNEL FLOOR, AND SAY WHEN THE STOPPER SIDE IS WRONG.
    #  v18  REWRITTEN MEASUREMENT: WIDTH PROFILE ALONG THE CHANNEL.
    # ==================================================================================

    import sensor, image, time, math
    from pyb import Pin, LED

    VERSION = 35


    # ------------------------------- CONFIG -------------------------------
    CALIBRATE     = False    # True = tuning mode: pins stay OFF, numbers printed
    SHOW_PROFILE  = True     # in CALIBRATE, print the band-by-band profile as text.
    PROFILE_EVERY = 20       # frames between profile dumps
    DEBUG         = True     # True = draw the channel, the bands and the ends
    FIT_ROI       = False    # True = with the chute EMPTY, measure where the bright chute is
    DRAW_OVERLAY  = True     # False = clean frame, for saving and analysing

    # The metal chute, as a box: (x, y, width, height).
    # Must sit ON THE METAL ONLY and must stop at the stopper bar.
    CHANNEL_ROI   = (130, 22, 32, 214)
    #                x    y   w    h

    # Which edge of that box the stopper is on: "bottom" "top" "left" "right".
    STOPPER_SIDE  = "bottom"

    # If EVERY chilli reads backwards, set this True.
    INVERT_ANSWER = False

    # ---- brightness limits (L runs 0 = black .. 100 = white) ----
    MANUAL_L      = None     # None = AUTO (measured each frame); int = fixed, for production
    DARK_K        = 0.50
    DARK_L_MIN    = 8
    DARK_L_MAX    = 50

    TIGHT_FRAC    = 0.70
    TIGHT_MIN     = 12
    STALK_SPAN    = 0.72
    STALK_L_CAP   = 90
    STALK_MIN_W   = 0.09

    # Redness presence test only
    MIN_CHILI_RED = 5.0

    # ---- the width profile ----
    BANDS         = 24       # slices along the channel
    BAND_ON       = 0.06
    BAND_THIN     = 0.05     # something is here, at the loose brightness limit

    # ---- the empty-channel reference (background) ----
    REF_LEAK_PER_S = 0.004
    REF_STALE_MS   = 60000   # refresh if stuck for 60s
    REF_WARMUP    = 40       # frames before reference is trusted
    FLOOR_WARN    = 0.15
    MIN_BODY_BANDS = 3       # shorter than this is noise
    MIN_STALK_BANDS = 2      # a 1-band overhang is just the tapering tip
    MAX_STALK_BANDS = 7      # longer than this is not a stalk

    # ---- must be at the stopper before we answer ----
    STOPPER_TOUCH_BANDS = 2  # body must reach within this many bands of the stopper end

    # ---- decision weights ----
    # Geometry (Taper & Mass Centroid) leads. Stalk confirms.
    W_TAPER       = 2.0      # The stem end is the fat end (primary ground truth)
    W_CENTROID    = 1.0      # Mass sits toward the fat end
    W_STALK       = 1.0      # Stalk confirmation cue
    W_RED         = 0.0      # Redness is presence only
    A_FULL        = 12.0

    # ---- rules ----
    DECIDE_MIN    = 0.12     # below this the ends look the same
    STABLE_N      = 4        # frames that must agree before locking
    SMOOTH_N      = 7        # score averaging window
    CLEAR_FRAMES  = 4        # empty frames before arming for the next chilli
    STUCK_MS      = 2500     # timeout for stuck pod
    MAX_WAIT_MS   = 1500     # max wait before default answer
    MIN_LOCK_MS   = 200      # hold answer duration
    DEFAULT_ANSWER = "POD"   # safe default

    # ---- outputs ----
    OUTPUT_MODE   = "level"  # "level" = hold until chilli leaves; "pulse"
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
        """Drive P0 / P1 / P2."""
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
        a = getattr(obj, name)
        return a(*args) if callable(a) else a

    def _stat(st, name, default=0.0):
        try:
            return float(_get(st, name))
        except Exception:
            return default

    def stalk_run(loose, start, step):
        """Contiguous occupied bands outward from the flesh."""
        n, i, gap = 0, start, 0
        while 0 <= i < BANDS and n <= MAX_STALK_BANDS + 1:
            if loose[i] >= BAND_THIN:
                n += gap + 1
                gap = 0
            else:
                gap += 1
                if gap > 1:
                    break
            i += step
        return n, (i < 0 or i >= BANDS) and gap <= 1

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
        if roi[2] < 2 or roi[3] < 2:
            return None
        try:
            st = img.get_statistics(thresholds=thrs, roi=roi)
            return _stat(st, "a_mean")
        except Exception:
            return None

    def region_redness_any(img, roi):
        if roi[2] < 2 or roi[3] < 2:
            return None
        try:
            st = img.get_statistics(roi=roi)
            return _stat(st, "a_mean")
        except Exception:
            return None

    VERTICAL   = STOPPER_SIDE in ("top", "bottom")
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
        """A box covering bands lo..hi (inclusive)."""
        r0, r1 = band_roi(lo), band_roi(hi)
        x0 = min(r0[0], r1[0])
        y0 = min(r0[1], r1[1])
        x1 = max(r0[0] + r0[2], r1[0] + r1[2])
        y1 = max(r0[1] + r0[3], r1[1] + r1[3])
        return (x0, y0, x1 - x0, y1 - y0)

    def measure_threshold(img):
        try:
            st = img.get_statistics(roi=CHANNEL_ROI)
            l_mean = _stat(st, "l_mean", 50.0)
            l_std = _stat(st, "l_stdev", 0.0)
            if l_std <= 0:
                l_std = _stat(st, "l_std", 12.0)
        except Exception:
            l_mean, l_std = 50.0, 12.0
        lim = l_mean - DARK_K * l_std
        return int(min(max(lim, DARK_L_MIN), DARK_L_MAX))

    lim_auto = None
    chute_L = None
    LIM_ADAPT = 0.02

    def object_threshold(img):
        if MANUAL_L is not None:
            return int(min(max(MANUAL_L, 0), 100))
        if lim_auto is None:
            return measure_threshold(img)
        return int(lim_auto)

    CHUTE_PCTL = 0.75

    def chute_brightness(img):
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
        global lim_auto, chute_L
        m = measure_threshold(img)
        lim_auto = float(m) if lim_auto is None else lim_auto + 0.25 * (m - lim_auto)
        c = chute_brightness(img)
        chute_L = c if chute_L is None else chute_L + 0.25 * (c - chute_L)

    def object_limit(lim):
        if chute_L is None:
            return STALK_L_CAP
        span = max(0.0, chute_L - lim)
        return int(min(STALK_L_CAP, lim + span * STALK_SPAN))

    def adapt_threshold(img):
        global lim_auto, chute_L
        if lim_auto is not None:
            lim_auto += LIM_ADAPT * (measure_threshold(img) - lim_auto)
        if chute_L is not None:
            chute_L += LIM_ADAPT * (chute_brightness(img) - chute_L)

    def mean(seq):
        return sum(seq) / float(len(seq)) if len(seq) else 0.0

    # ---------------------- the empty-channel reference -------------------
    ref = [1.0] * BANDS
    ref_frames = 0
    ref_last_ms = None
    ref_last_empty_ms = None

    def ref_leak(now):
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
        for i in range(BANDS):
            v = ref2[i] + leak
            if raw2[i] < v:
                v = raw2[i]
            ref2[i] = v

    def update_reference_t(raw_t, leak):
        for i in range(BANDS):
            v = ref_t[i] + leak
            if raw_t[i] < v:
                v = raw_t[i]
            ref_t[i] = v

    def reset_reference():
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
            "lo_f": -1, "hi_f": -1, "loose": None, "lim2": 0, "runs_off": False,
            "stalk_lost": False}

    def look(img):
        out = dict(BLANK)

        if ref_frames < REF_WARMUP:
            learn_threshold(img)
        lim = object_threshold(img)
        out["lim"] = lim

        lim2 = max(lim + 4, object_limit(lim))
        out["lim2"] = lim2
        lim_t = max(TIGHT_MIN, int(lim * TIGHT_FRAC))     # flesh only
        thrs = [(0, lim, -128, 127, -128, 127)]

        # --- 1. width profile of the body, from the stopper end outward ---
        raw = [dark_fraction(img, band_roi(i), lim) for i in range(BANDS)]
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
        global ref_last_empty_ms
        idx = [i for i in range(BANDS) if prof[i] >= BAND_ON]
        seems_empty = len(idx) < MIN_BODY_BANDS
        warming = ref_frames < REF_WARMUP
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
            ref_leak(now_ms())

        if warming:
            out["reason"] = "learning"
            return out

        if seems_empty:
            adapt_threshold(img)
            return out

        lo_d, hi_d = idx[0], idx[-1]
        aidx = [i for i in range(BANDS) if loose[i] >= BAND_THIN]
        lo = min(aidx[0], lo_d) if aidx else lo_d
        hi = max(aidx[-1], hi_d) if aidx else hi_d
        out["lo"], out["hi"] = lo, hi

        rect = span_rect(lo_d, hi_d)
        out["rect"] = rect
        out["runs_off"] = (hi >= BANDS - 1)

        # Contiguous flesh run nearest the stopper
        lo_f = hi_f = -1
        i = lo_d
        while i <= hi_d:
            if flesh[i] >= BAND_ON:
                j = i
                while j + 1 <= hi_d and flesh[j + 1] >= BAND_ON:
                    j += 1
                if j - i + 1 >= MIN_BODY_BANDS:
                    lo_f, hi_f = i, j
                    break
                i = j + 1
            else:
                i += 1
        if lo_f < 0:
            out["reason"] = "no_read"
            return out
        out["lo_f"], out["hi_f"] = lo_f, hi_f

        # --- 2. Color presence check ---
        red = region_redness(img, rect, thrs)
        if red is None:
            red = region_redness_any(img, rect)
        out["red"] = red if red is not None else 0.0
        if red is not None and red < MIN_CHILI_RED:
            out["reason"] = "metal"
            return out

        # --- 3. Touching stopper check ---
        if lo > STOPPER_TOUCH_BANDS:
            out["reason"] = "sliding"
            return out

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

        # --- 5. CENTROID: center of mass ---
        tot = sum(flesh[lo_f:hi_f + 1])
        if tot > 0:
            cm = sum(ci * flesh[ci] for ci in range(lo_f, hi_f + 1)) / tot
            mid = (lo_f + hi_f) * 0.5
            s_centroid = min(1.0, max(-1.0, (mid - cm) / (span * 0.25)))
        else:
            s_centroid = 0.0
        out["s_centroid"] = s_centroid

        # --- 6. STALK: contiguous stalk runs ---
        stalk_near, ran_off_near = stalk_run(loose, lo_f - 1, -1)
        stalk_far, ran_off_far = stalk_run(loose, hi_f + 1, +1)

        if ran_off_far:
            if stalk_far >= MIN_STALK_BANDS:
                out["stalk_lost"] = True
            stalk_far = 0

        if stalk_near > 0 and mean(loose[lo_f - stalk_near:lo_f]) < STALK_MIN_W:
            stalk_near = 0
        if stalk_far > 0 and mean(loose[hi_f + 1:hi_f + 1 + stalk_far]) < STALK_MIN_W:
            stalk_far = 0

        if stalk_near < MIN_STALK_BANDS or stalk_near > MAX_STALK_BANDS:
            stalk_near = 0
        if stalk_far < MIN_STALK_BANDS or stalk_far > MAX_STALK_BANDS:
            stalk_far = 0

        # STALK-SHOULDER CONSISTENCY RULE:
        # A stalk is ALWAYS attached to the fat calyx shoulder.
        # If the near end is significantly thinner than the far end (s_taper < -0.12),
        # any thin extension at the near end is the APEX TIP, NOT a stalk!
        if s_taper < -0.12:
            stalk_near = 0
        if s_taper > +0.12:
            stalk_far = 0

        out["stalk_near"], out["stalk_far"] = stalk_near, stalk_far
        if stalk_near == stalk_far:
            s_stalk = 0.0
        else:
            s_stalk = (stalk_near - stalk_far) / float(max(stalk_near, stalk_far))
        out["s_stalk"] = s_stalk

        # --- 7. REDNESS ---
        a_near = region_redness(img, span_rect(lo, min(hi, lo + k - 1)), thrs)
        a_far = region_redness(img, span_rect(max(lo, hi - k + 1), hi), thrs)
        if a_near is not None and a_far is not None:
            s_red = min(1.0, max(-1.0, (a_far - a_near) / A_FULL))
            rw = W_RED
        else:
            s_red, rw = 0.0, 0.0
        out["s_red"] = s_red

        # --- 8. Combined Score (Geometry Dominates) ---
        tot_w = W_TAPER + W_CENTROID + rw
        acc = W_TAPER * s_taper + W_CENTROID * s_centroid + rw * s_red
        if s_stalk != 0.0:
            tot_w += W_STALK
            acc += W_STALK * s_stalk
        score = acc / tot_w if tot_w > 0 else 0.0

        if INVERT_ANSWER:
            score = -score

        if s_stalk != 0.0 and s_taper != 0.0 and (s_stalk > 0) != (s_taper > 0):
            out["agree"] = False

        out["score"] = score
        out["reason"] = "ok"
        return out

    def longest_run(flags):
        best_s, best_n, s0, n = -1, 0, -1, 0
        for i in range(len(flags)):
            if flags[i]:
                if n == 0:
                    s0 = i
                n += 1
                if n > best_n:
                    best_s, best_n = s0, n
            else:
                n = 0
        return best_s, best_n

    def suggest_channel_roi(img):
        print("")
        print("-" * 62)
        print("FIT_ROI: measuring the chute. The chute must be EMPTY for this.")

        STEP = 2
        INSET = 2

        cols = []
        for x in range(0, 320 - STEP, STEP):
            try:
                st = img.get_statistics(roi=(x, 40, STEP, 160))
                cols.append(_stat(st, "l_mean", 0.0))
            except Exception:
                cols.append(0.0)
        peak = max(cols) if cols else 0.0
        if peak <= 0:
            print("  could not find anything bright. Is the chute lit?")
            print("-" * 62)
            return
        xs, xn = longest_run([c >= peak * 0.80 for c in cols])
        if xn < 2:
            print("  no clear bright strip found.")
            print("-" * 62)
            return
        x0, w = xs * STEP, xn * STEP

        rows = []
        for y in range(0, 240 - STEP, STEP):
            try:
                st = img.get_statistics(roi=(x0, y, w, STEP))
                rows.append(_stat(st, "l_mean", 0.0))
            except Exception:
                rows.append(0.0)
        ys, yn = longest_run([r >= peak * 0.70 for r in rows])
        if yn < 4:
            print("  the bright strip is too short to be the chute.")
            print("-" * 62)
            return
        y0, h = ys * STEP, yn * STEP

        fit = (x0 + INSET, y0 + INSET, max(4, w - 2 * INSET),
            max(8, h - 2 * INSET))
        print("  chute found at x %d..%d, y %d..%d  (brightness %.0f)"
            % (x0, x0 + w, y0, y0 + h, peak))
        print("")
        print("  >>> CHANNEL_ROI   = %s" % (fit,))
        print("      currently      %s" % (CHANNEL_ROI,))
        print("-" * 62)
        print("")

    def print_profile(r):
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

        def _says(v):
            if v == 0:
                return "nothing"
            pos = (v > 0) != INVERT_ANSWER
            return "STEM at stopper" if pos else "APEX at stopper"

        print("  flesh near third %.2f  far third %.2f  taper %+.2f -> %s"
            % (r["w_near"], r["w_far"], r["s_taper"], _says(r["s_taper"])))
        if r["runs_off"]:
            print("  !! the pod reaches the LAST band - the far third is not all chilli")
        print("  stalk bands: %d at the stopper end, %d at the far end -> %s"
            % (r["stalk_near"], r["stalk_far"],
                "no stalk seen" if r["s_stalk"] == 0 else _says(r["s_stalk"])))
        print("  this frame scores %+.2f%s" %
            (r["score"], "   (INVERT_ANSWER is ON)" if INVERT_ANSWER else ""))

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
                                img.draw_rectangle((px, py, sc, sc), color=color, fill=True)
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
        cx, cy, cw, ch = CHANNEL_ROI
        left = cx - 8
        right = 320 - (cx + cw) - 8
        h = 54
        if left >= right:
            return (4, 4, max(70, min(left, 300)), h)
        return (min(316, cx + cw + 4), 4, max(70, min(right, 300)), h)

    def draw_scene(img, r, headline, color, sub, fps):
        if not DRAW_OVERLAY:
            return
        if DEBUG:
            draw_rect(img, CHANNEL_ROI, (255, 0, 255), 1)
            b = band_roi(0)
            draw_rect(img, b, (0, 255, 255), 1, True)

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

        if r["rect"] and r["reason"] in ("ok", "sliding"):
            c = (0, 255, 0) if r["reason"] == "ok" else (255, 180, 0)
            draw_rect(img, r["rect"], c, 2)

        # Pin indicator to stopper (Band 0)
        if r["reason"] == "ok" and r["lo"] >= 0:
            is_stem = r["score"] > 0
            mk = span_rect(0, 2)
            col = (0, 220, 0) if is_stem else (255, 60, 60)
            draw_rect(img, mk, col, 2)
            label = "STEM" if is_stem else "APEX"
            cx, cy, cw, ch = CHANNEL_ROI
            lx = max(0, cx - 44) if cx > 44 else min(319, cx + cw + 4)
            ly = mk[1] + max(0, (mk[3] - 7) // 2)
            draw_str(img, lx, ly, label, color=col, scale=1)

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
    calib_n = 0
    runoff_warned = False
    stalklost_warned = False
    stuck_since = 0
    stuck_lo = -1
    stuck_warned = False

    def smooth(s):
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
    print("=" * 62)

    fitted = not FIT_ROI

    while True:
        clock.tick()
        now = time.ticks_ms()
        img = sensor.snapshot()
        fps = clock.fps()

        if not fitted:
            fitted = True
            suggest_channel_roi(img)

        r = look(img)

        if r["reason"] == "sliding":
            if abs(r["lo"] - stuck_lo) > 1:
                stuck_lo, stuck_since, stuck_warned = r["lo"], now, False
            elif time.ticks_diff(now, stuck_since) >= STUCK_MS:
                r["wrong_end"] = True
                if not stuck_warned:
                    stuck_warned = True
                    print("!!! chilli has sat still at bands %d-%d for %ds without reaching stopper."
                        % (r["lo"], r["hi"], STUCK_MS // 1000))
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
                    print(">>> v%d #%d  %s FIRST -> %s HIGH  ==> %s   "
                        "(score %+.2f avg / %+.2f now | taper %+.2f  stalk %+.0f"
                        "  cent %+.2f)%s"
                        % (VERSION, total, NAME[final],
                            "P0" if final == "STEM" else "P1",
                            "ROTATE 180 (P2)" if final == ROTATE_ON else "NO ROTATE",
                            final_score, r["score"], r["s_taper"], r["s_stalk"],
                            r["s_centroid"], "" if final_sure else "  [LOW CONFIDENCE]"))

        # ----------------------------- LOCKED -----------------------------
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

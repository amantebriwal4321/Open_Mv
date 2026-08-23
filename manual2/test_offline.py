"""Offline check of the v18 measurement: does a stem-first chilli score
POSITIVE and an apex-first chilli score NEGATIVE?  Runs on the PC with the
camera modules stubbed out.  Nothing here ships to the camera."""
import sys, types, math, os, random

# ---- stub the MicroPython modules so part_a.py will import ----
sensor = types.ModuleType("sensor")
for n in ("reset", "set_pixformat", "set_framesize", "skip_frames",
          "set_auto_gain", "set_auto_whitebal"):
    setattr(sensor, n, lambda *a, **k: None)
sensor.RGB565 = 0
sensor.QVGA = 1
sensor.snapshot = lambda: None
sys.modules["sensor"] = sensor
sys.modules["image"] = types.ModuleType("image")

pyb = types.ModuleType("pyb")
class Pin:
    OUT_PP = IN = PULL_DOWN = PULL_UP = 0
    def __init__(self, *a, **k): self._v = 0
    def value(self, v=None):
        if v is None: return self._v
        self._v = v
class LED:
    def __init__(self, *a): pass
    def on(self): pass
    def off(self): pass
pyb.Pin, pyb.LED = Pin, LED
sys.modules["pyb"] = pyb

# MicroPython's time has clock()/ticks_ms(); CPython's does not.
_time = types.ModuleType("time")
class _Clock:
    def tick(self): pass
    def fps(self): return 30.0
_time.clock = lambda: _Clock()
_time.ticks_ms = lambda: 0
_time.ticks_diff = lambda a, b: a - b
_time.ticks_add = lambda a, b: a + b
sys.modules["time"] = _time

# ---- a synthetic scene ----
W, H = 320, 240
L_METAL, L_BODY, L_STALK = 80.0, 20.0, 55.0
A_METAL, A_BODY, A_STALK = 0.0, 25.0, 10.0

CH_X, CH_Y, CH_W, CH_H = 200, 50, 28, 138
CX = CH_X + CH_W // 2
STOP_Y = CH_Y + CH_H - 2          # the chilli rests here (bottom = stopper)


def build(stem_first, body_len=86, gap=2, stalk=14, fat=11.0, thin=1.0,
          off=0, noise=0.0, rails=0, bar=0):
    """Return (L, A) images.

    stem_first  fat shoulder at the stopper end, point away from it
    gap         pixels between the chilli and the stopper (still sliding)
    stalk       length of the pale stalk in pixels, 0 for a de-stemmed pod
    fat/thin    half-width at the shoulder and at the point
    off         sideways offset in the channel
    rails       px of dark rail just inside each ROI edge - i.e. CHANNEL_ROI
                set slightly wider than the bright chute, which is what the
                machine was actually doing
    bar         px of dark STOPPER BAR inside the bottom edge of the ROI - i.e.
                CHANNEL_ROI reaching a little past the stopper. Only darkens
                the last band or two, so a single floor cannot remove it.
    """
    Limg = [[L_METAL] * W for _ in range(H)]
    Aimg = [[A_METAL] * W for _ in range(H)]
    if noise:
        rnd = random.Random(7)
        for y in range(CH_Y, CH_Y + CH_H):
            for x in range(CH_X, CH_X + CH_W):
                Limg[y][x] += rnd.uniform(-noise, noise)

    if rails:
        for y in range(CH_Y, CH_Y + CH_H):
            for x in list(range(CH_X, CH_X + rails)) +                      list(range(CH_X + CH_W - rails, CH_X + CH_W)):
                Limg[y][x] = L_BODY + 6.0

    if bar:
        for y in range(CH_Y + CH_H - bar, CH_Y + CH_H):
            for x in range(CH_X, CH_X + CH_W):
                Limg[y][x], Aimg[y][x] = 12.0, 0.0

    cx = CX + off
    y_bot = STOP_Y - gap
    y_top = y_bot - body_len

    for y in (range(y_top, y_bot + 1) if body_len > 0 else ()):
        t = (y_bot - y) / float(body_len)        # 0 at the stopper, 1 far away
        hw = (fat * (1.0 - t) + thin * t) if stem_first else (thin * (1.0 - t) + fat * t)
        for x in range(int(cx - hw), int(cx + hw) + 1):
            if CH_X <= x < CH_X + CH_W:
                Limg[y][x], Aimg[y][x] = L_BODY, A_BODY

    if stalk:
        # the stalk always grows out of the STEM end
        ys = range(y_bot + 1, y_bot + 1 + stalk) if stem_first \
            else range(y_top - stalk, y_top)
        for y in ys:
            if not (0 <= y < H):
                continue
            for x in range(cx - 2, cx + 3):
                if CH_Y <= y < CH_Y + CH_H and CH_X <= x < CH_X + CH_W:
                    Limg[y][x], Aimg[y][x] = L_STALK, A_STALK
    return Limg, Aimg


class Hist:
    def __init__(self, bins): self.bins = bins

class Stats:
    def __init__(self, l_mean, l_stdev, a_mean):
        self.l_mean, self.l_stdev, self.a_mean = l_mean, l_stdev, a_mean

class FakeImg:
    def __init__(self, Limg, Aimg): self.L, self.A = Limg, Aimg

    def _px(self, roi):
        x, y, w, h = roi
        return [(self.L[j][i], self.A[j][i])
                for j in range(y, min(H, y + h))
                for i in range(x, min(W, x + w))]

    def get_histogram(self, roi=None, **k):
        px = self._px(roi)
        n = len(px)
        bins = [0.0] * 100
        if not n:
            return Hist(bins)
        for l, _ in px:
            bins[min(99, max(0, int(l)))] += 1.0 / n
        return Hist(bins)

    def get_statistics(self, roi=None, thresholds=None, **k):
        px = self._px(roi)
        if thresholds:
            lo, hi = thresholds[0][0], thresholds[0][1]
            px = [p for p in px if lo <= p[0] <= hi]
        if not px:
            return Stats(50.0, 0.0, 0.0)
        ls = [p[0] for p in px]
        a_s = [p[1] for p in px]
        m = sum(ls) / len(ls)
        sd = math.sqrt(sum((v - m) ** 2 for v in ls) / len(ls))
        return Stats(m, sd, sum(a_s) / len(a_s))

    def find_blobs(self, *a, **k):
        raise RuntimeError("histogram path should be used")


# ---- load the detector ----
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, "open_mv_v20.py")).read()
mod = {"__name__": "detector"}
exec(compile(src.split("# ============================ STATE MACHINE")[0], "open_mv_v20.py", "exec"), mod)
look = mod["look"]

# name, kwargs, expected -- "STEM"/"APEX", or a reason string, or "WEAK"
CASES = [
    ("stem first, typical",      dict(stem_first=True),                    "STEM"),
    ("apex first, typical",      dict(stem_first=False),                   "APEX"),
    ("stem first, no stalk",     dict(stem_first=True,  stalk=0),          "STEM"),
    ("apex first, no stalk",     dict(stem_first=False, stalk=0),          "APEX"),
    ("stem first, short pod",    dict(stem_first=True,  body_len=48),      "STEM"),
    ("apex first, short pod",    dict(stem_first=False, body_len=48),      "APEX"),
    ("stem first, long pod",     dict(stem_first=True,  body_len=120),     "STEM"),
    ("apex first, long pod",     dict(stem_first=False, body_len=120),     "APEX"),
    ("stem first, off-centre",   dict(stem_first=True,  off=5),            "STEM"),
    ("apex first, off-centre",   dict(stem_first=False, off=-5),           "APEX"),
    ("stem first, blunt taper",  dict(stem_first=True,  fat=9.0, thin=5.0), "STEM"),
    ("apex first, blunt taper",  dict(stem_first=False, fat=9.0, thin=5.0), "APEX"),
    ("stem first, noisy light",  dict(stem_first=True,  noise=9.0),        "STEM"),
    ("apex first, noisy light",  dict(stem_first=False, noise=9.0),        "APEX"),
    ("still sliding down",       dict(stem_first=True,  gap=40),           "sliding"),
    ("barely-tapered pod",       dict(stem_first=True,  fat=8.0, thin=7.4,
                                      stalk=0),                            "WEAK"),
    # what the machine was actually seeing: ROI a bit wider than the chute, so
    # dark rails sit in every band
    ("stem first + dark rails",  dict(stem_first=True,  rails=4),          "STEM"),
    ("apex first + dark rails",  dict(stem_first=False, rails=4),          "APEX"),
    ("short pod + dark rails",   dict(stem_first=True,  rails=4,
                                      body_len=48),                        "STEM"),
    # pod resting against the opposite end = STOPPER_SIDE is wrong
    ("pod short of stopper",    dict(stem_first=True,  gap=52,
                                      body_len=48),                    "sliding"),
    ("pod short + rails",       dict(stem_first=True,  gap=52, body_len=48,
                                      rails=4),                        "sliding"),
    # ROI reaching past the stopper, so the dark bar sits in the last band(s).
    # A single floor cannot remove this - it is dark in SOME bands only.
    ("stem first + stopper bar", dict(stem_first=True,  bar=8),          "STEM"),
    ("apex first + stopper bar", dict(stem_first=False, bar=8),          "APEX"),
    ("bar + rails, stem first",  dict(stem_first=True,  bar=8, rails=4), "STEM"),
    ("bar + rails, apex first",  dict(stem_first=False, bar=8, rails=4), "APEX"),
    # the pod stops short of the bar: must NOT be judged as if it had arrived
    ("short of the bar",         dict(stem_first=True,  bar=8, gap=46,
                                      body_len=48),                     "sliding"),
]

reset_reference = mod["reset_reference"]

def run(kw):
    """Learn the empty chute, then show it the chilli - what the machine does."""
    reset_reference()
    empty_kw = dict(kw)
    empty_kw["body_len"] = 0
    empty_kw["stalk"] = 0
    empty = FakeImg(*build(**empty_kw))
    for _ in range(mod["REF_WARMUP"] + 2):
        look(empty)
    return look(FakeImg(*build(**kw)))

fails = 0
for name, kw, want in CASES:
    r = run(kw)
    got = "STEM" if r["score"] > 0 else "APEX"
    if want in ("STEM", "APEX"):
        ok = (r["reason"] == "ok") and got == want and abs(r["score"]) >= 0.12
        shown = got
    elif want == "WEAK":
        # must NOT answer confidently when the two ends really are alike
        ok = (r["reason"] != "ok") or abs(r["score"]) < 0.30
        shown = "%s(weak)" % got if r["reason"] == "ok" else r["reason"]
    else:
        ok = r["reason"] == want
        shown = r["reason"]
    if not ok:
        fails += 1
    print("%-24s -> %-11s %+.2f | taper %+.2f  stalk %+.0f (%d/%d)  "
          "cent %+.2f  red %+.2f | bands %2d-%2d %s"
          % (name, shown, r["score"], r["s_taper"], r["s_stalk"],
             r["stalk_near"], r["stalk_far"], r["s_centroid"], r["s_red"],
             r["lo"], r["hi"], "PASS" if ok else "  <<< FAIL"))

# empty chute must read empty
reset_reference()
_e = FakeImg([[L_METAL] * W for _ in range(H)], [[A_METAL] * W for _ in range(H)])
for _ in range(mod["REF_WARMUP"] + 2):
    look(_e)
r = look(_e)
ok = r["reason"] in ("empty", "metal")
fails += 0 if ok else 1
print("%-24s -> %-11s %s" % ("empty chute", r["reason"],
                             "PASS" if ok else "  <<< FAIL"))

print("\n%d failure(s) out of %d" % (fails, len(CASES) + 1))
sys.exit(1 if fails else 0)

"""Run the REAL detector on REAL frames saved from the OpenMV IDE.

The camera cannot be driven from here, but the pictures it takes can be fed to
exactly the same code that runs on it. That closes the loop that has cost this
project most of its rounds: instead of guessing at a screenshot, the detector is
run on the actual pixels and prints the full profile.

    python manual2/run_on_image.py empty.png chilli.png

  empty.png   a frame of the EMPTY chute. The detector learns its background
              from this, exactly as it does on the camera at start-up. Without
              it the rails, the stopper bar and any fixed shadow are counted as
              chilli, and the answer means nothing.
  chilli.png  the frame to judge.

Save both from the IDE with DRAW_OVERLAY = False in open_mv2.py, so the boxes
the code draws are not fed back into it as image data.
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is needed: py -m pip install pillow")

HERE = os.path.dirname(os.path.abspath(__file__))


def newest_version():
    best, best_n = None, -1
    for f in os.listdir(HERE):
        if f.startswith("open_mv_v") and f.endswith(".py"):
            try:
                n = int(f[len("open_mv_v"):-3])
            except ValueError:
                continue
            if n > best_n:
                best, best_n = f, n
    return best, best_n


def load_detector():
    """Load look() from the highest-numbered version, minus the camera loop."""
    fname, ver = newest_version()
    src = open(os.path.join(HERE, fname)).read()
    src = src.split("# ============================ STATE MACHINE")[0]

    import types
    for name in ("sensor", "image"):
        m = types.ModuleType(name)
        for fn in ("reset", "set_pixformat", "set_framesize", "skip_frames",
                   "set_auto_gain", "set_auto_whitebal", "snapshot"):
            setattr(m, fn, lambda *a, **k: None)
        m.RGB565, m.QVGA = 0, 1
        sys.modules[name] = m

    pyb = types.ModuleType("pyb")

    class Pin:
        OUT_PP = IN = PULL_DOWN = PULL_UP = 0

        def __init__(self, *a, **k):
            self._v = 0

        def value(self, v=None):
            if v is None:
                return self._v
            self._v = v

    class LED:
        def __init__(self, *a):
            pass

        def on(self):
            pass

        def off(self):
            pass

    pyb.Pin, pyb.LED = Pin, LED
    sys.modules["pyb"] = pyb

    clock_ms = [0]
    t = types.ModuleType("time")

    class _Clock:
        def tick(self):
            pass

        def fps(self):
            return 30.0

    t.clock = lambda: _Clock()
    t.ticks_ms = lambda: clock_ms[0]
    t.ticks_diff = lambda a, b: a - b
    t.ticks_add = lambda a, b: a + b
    sys.modules["time"] = t

    mod = {"__name__": "detector"}
    exec(compile(src, fname, "exec"), mod)
    return mod, ver, clock_ms


def crop_frame_buffer(im):
    """Pull the camera frame out of a screenshot of the whole IDE window.

    Saving the frame buffer properly gives a 320x240 file, but a screen capture
    of the IDE is what usually arrives. The frame-buffer panel is surrounded by
    the IDE's flat dark padding, so the picture is the block of NON-flat pixels
    in the right-hand half. Scaling it back down loses a little sharpness but
    keeps every threshold in this code meaningful, which a raw screenshot does
    not - the bands would be measured over the wrong pixels entirely.
    """
    W, H = im.size
    px = im.load()

    def flat(c):
        return abs(c[0] - c[1]) < 6 and abs(c[1] - c[2]) < 6 and c[0] < 80

    x_start = int(W * 0.5)
    # vertical extent: scan a column near the middle of the right panel
    xs = x_start + (W - x_start) // 2
    ys = [y for y in range(H) if not flat(px[xs, y])]
    if not ys:
        return None
    top, bot = min(ys), max(ys)
    # horizontal extent: scan a row inside that band
    ym = (top + bot) // 2
    xsr = [x for x in range(x_start, W) if not flat(px[x, ym])]
    if not xsr:
        return None
    left, right = min(xsr), max(xsr)
    w = right - left
    h = bot - top
    if w < 100 or h < 80:
        return None
    # The panel is 4:3, and the WIDTH is the measurement to trust. The vertical
    # scan reaches past the picture into the toolbar and status bar, which are
    # not flat padding either - on one screenshot that gave a 929x852 box for a
    # frame that is really 929x697, and every band was then measured over the
    # wrong pixels. Derive the height from the width instead.
    h2 = int(round(w * 240.0 / 320.0))
    if abs(h2 - h) > 0.15 * h:
        h = h2
    return (left, top, min(W, left + w), min(H, top + h))


class Frame:
    """A saved picture, presented the way the OpenMV image API presents one."""

    def __init__(self, path):
        im = Image.open(path).convert("RGB")
        if im.size != (320, 240):
            box = crop_frame_buffer(im) if im.size[0] > 700 else None
            if box:
                print("  %s is a %dx%d screenshot - cropping the frame buffer "
                      "at %s" % (os.path.basename(path), im.size[0], im.size[1],
                                 box))
                im = im.crop(box)
            else:
                print("  note: %s is %dx%d, resizing to 320x240"
                      % (os.path.basename(path), im.size[0], im.size[1]))
            im = im.resize((320, 240))
        lab = im.convert("LAB")
        px = lab.load()
        self.W, self.H = 320, 240
        # OpenMV uses L 0..100 and a/b -128..127; PIL packs all three into
        # 0..255, so both have to be rescaled or every threshold is meaningless.
        self.L = [[px[x, y][0] * 100.0 / 255.0 for x in range(320)]
                  for y in range(240)]
        self.A = [[px[x, y][1] - 128.0 for x in range(320)] for y in range(240)]
        self._hcache = {}

    def _px(self, roi):
        x, y, w, h = roi
        return [(self.L[j][i], self.A[j][i])
                for j in range(y, min(self.H, y + h))
                for i in range(x, min(self.W, x + w))]

    def get_histogram(self, roi=None, **k):
        hit = self._hcache.get(roi)
        if hit is not None:
            return hit
        px = self._px(roi)
        bins = [0.0] * 100
        if px:
            for l, _ in px:
                bins[min(99, max(0, int(l)))] += 1.0 / len(px)
        h = type("H", (), {"bins": bins})()
        self._hcache[roi] = h
        return h

    def get_statistics(self, roi=None, thresholds=None, **k):
        px = self._px(roi)
        if thresholds:
            lo, hi = thresholds[0][0], thresholds[0][1]
            px = [p for p in px if lo <= p[0] <= hi]
        if not px:
            return type("S", (), {"l_mean": 50.0, "l_stdev": 0.0,
                                  "a_mean": 0.0})()
        ls = [p[0] for p in px]
        m = sum(ls) / len(ls)
        var = sum((v - m) ** 2 for v in ls) / len(ls)
        return type("S", (), {"l_mean": m, "l_stdev": var ** 0.5,
                              "a_mean": sum(p[1] for p in px) / len(px)})()

    def find_blobs(self, *a, **k):
        return []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        sys.exit(__doc__)

    mod, ver, clock_ms = load_detector()
    look = mod["look"]
    print("=" * 66)
    print("running v%d  CHANNEL_ROI=%s  STOPPER_SIDE=%s  INVERT_ANSWER=%s"
          % (ver, mod["CHANNEL_ROI"], mod["STOPPER_SIDE"],
             mod["INVERT_ANSWER"]))
    print("=" * 66)

    if len(args) >= 2:
        empty, target = args[0], args[1]
    else:
        empty, target = None, args[0]
        print("!! no empty-chute frame given. The background reference cannot")
        print("   be learned, so rails, the stopper bar and fixed shadow will")
        print("   all count as chilli. Pass an empty frame first for a real")
        print("   answer.")

    if empty:
        ef = Frame(empty)
        for _ in range(mod["REF_WARMUP"] + 4):
            clock_ms[0] += 5
            look(ef)
        print("learned the empty chute from %s" % os.path.basename(empty))

    clock_ms[0] += 40
    r = look(Frame(target))

    print("\n--- %s ---" % os.path.basename(target))
    if r["reason"] != "ok":
        print("no answer: %s   (bands %d-%d)" % (r["reason"], r["lo"], r["hi"]))
    mod["print_profile"](r)
    if r["reason"] == "ok":
        inv = mod["INVERT_ANSWER"]
        says = "STEM" if (r["score"] > 0) else "APEX"
        print("\n  ANSWER: %s at the stopper   (score %+.2f%s)"
              % (says, r["score"], ", INVERT_ANSWER is ON" if inv else ""))


if __name__ == "__main__":
    main()

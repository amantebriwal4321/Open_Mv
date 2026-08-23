# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

Vision software for an **OpenMV Cam H7 Plus** on a chilli de-stemming machine.
Dried red chillies travel down a channel and stop against a mechanical stopper. The
camera decides **which end of the chilli is at the stopper** and signals the PLC, which
rotates the pod 180° (or leaves it) so every chilli reaches the cutter facing the same way.

Repo: https://github.com/amantebriwal4321/Open_Mv

### Terminology
- **pod** — the whole dried chilli fruit (the vendor's files use `POD` for this)
- **stem end** — the end with the stalk (*peduncle*) and the little cap (*calyx*)
- **tip** / **apex** — the opposite, pointed end (botanically the *blossom end*)

## The requirement, and how it changed

**Originally:** the camera judged whether the stem lay to the **LEFT or RIGHT** across a
tray, and a motor rotated the pod 90° toward the cutter. Most files in this repo are from
that era.

**Now (current):** the chilli slides down a channel and halts at a stopper. The camera sits
on the stopper side and answers one question — **did the chilli arrive stem-first or
tip-first?** The PLC then rotates 180°, or not, via pneumatic cylinders.

This is a simpler problem: one fixed position, one binary answer.

Module 2 (a quality chute below the channel, needing a fisheye lens) is **out of scope**.

## Files and versioning

The repo is split into `System1/`, `System2/`, `Trial codes/` and `manual2/`.

**`manual2/` is where the current work lives.** One numbered file per change:

```
manual2/
  open_mv_v23.py         <- highest number = current
  open_mv_v22.py
  open_mv_v21.py
  open_mv_v20.py
  open_mv_v19.py
  open_mv_v18.py
  open_mv_v17.py
  open_mv_v16.py
  ...
  test_offline.py        <- runs the detector on a PC, no camera needed
  README.md              <- version table, setup order, threshold guide
open_mv2.py              <- working copy, same as the highest version
```

### How to save an updated version (follow this every time)

Nothing in `manual2/` is ever overwritten. When the code changes:

1. **Edit `open_mv2.py`** (the working copy).
2. **Bump the `VERSION nn` header** at the top of the file and add a short
   changelog line saying what changed *and why* — the "why" is what stops the
   same mistake being repeated.
3. **Copy it to a new numbered file**: `cp open_mv2.py manual2/open_mv_vNN.py`
   — never overwrite an existing one.
4. **Add a row to the top of the table in `manual2/README.md`**, and move the
   word **Current** onto the new row.
5. **Syntax-check**: `python -m py_compile open_mv2.py` (MicroPython imports
   such as `sensor` and `pyb` will not resolve on a PC, but syntax and dead
   names are caught).
6. **Commit and push** with a message that explains the cause, not just the fix.

Why keep every version: several "fixes" in this project made things worse
(v13's automatic channel finder, for example). Being able to go straight back
to a version that worked has been worth more than a tidy folder.

⚠️ `main.py` in the repo is an **old** version. When deploying, the *current*
file is renamed to `main.py` on the camera — do not copy the repo's `main.py`.

## How the current detector works

Values below are the ones in `open_mv2.py` / `manual2/open_mv_v23.py`.

The channel is a narrow strip, so a chilli lying in it is always lined up with
it. v18 uses that: instead of hunting for a blob and measuring two small boxes
at its ends, it slices the channel into `BANDS = 24` bands across the short side
and measures how dark each band is. That gives a **width profile** of the pod
from one end to the other — its actual shape, not two samples of it. Index 0 is
always the stopper end (`band_roi` reverses the order when `STOPPER_SIDE` is
`bottom`/`right`), so a positive score always means STEM.

1. **Brightness line.** `MANUAL_L = None` measures it per frame
   (`l_mean - DARK_K*l_stdev`, clamped `DARK_L_MIN..DARK_L_MAX`); set a fixed int
   for production. Shown on screen as `L<=NN AUTO/SET`. A second, looser limit
   (`lim + STALK_L_EXTRA`) is what makes the pale stalk visible.
2. **Empty-chute reference removed, per band.** `ref[i]` is a running minimum of
   each band with a slow upward leak (`REF_LEAK`); `prof = raw - ref`. **Extent**
   = bands with the corrected value `>= BAND_ON` (0.06, deliberately low).
3. **Presence gates:** `MIN_BODY_BANDS` on the reference-subtracted profile, and
   `MIN_CHILI_RED` against bare-metal shadow. Colour is a *presence* test only —
   it must never *reject* a candidate, because a pink cloth reads redness 20–40
   while a dark dried chilli reads 4–8.
4. **Must be at the stopper:** `lo <= STOPPER_TOUCH_BANDS`, else `CHILLI STILL
   MOVING` and no decision.
5. **Four cues**, all comparisons within the same chilli:

   | Cue | Weight | Says STEM when… |
   |---|---|---|
   | stalk | 2.4 | pod-but-not-flesh bands sit at that end |
   | taper | 1.3 | mean FLESH profile over the near third > the far third |
   | centroid | 0.5 | flesh mass sits toward that end |
   | redness | **0.0 — off** | measured and logged, but not voted with |

   A cue that does not fire is left **out of the weight total**, so it cannot
   dilute the ones that did.
6. **State machine** WAIT → CHECK → LOCKED → CLEARING. Score averaged over
   `SMOOTH_N = 7` frames, `STABLE_N = 4` agreeing frames to lock (6 if cues
   disagree), answer held until the chilli leaves, then `EMPTY`. On
   `MAX_WAIT_MS` timeout it emits `DEFAULT_ANSWER` marked `[LOW CONFIDENCE]`
   rather than stalling the line.

### Stalk vs flesh: brightness, never width (v21)
A stalk and a fine apex can be the **same width**, so width cannot separate them.
Trying to caused the same bug twice in mirror image: v18 read a tapering tip as a
stalk; v20 read a stalk as a tapering tip and locked APEX at -0.73 on a pod lying
stalk-down toward the stopper.

Brightness does separate them - flesh is deep red and dark, a dried stalk is
pale. The profile is measured at **two** limits: `lim` (anything at all) and
`lim_t = lim * TIGHT_FRAC` (flesh only). Bands the pod occupies that hold no
flesh **are** the stalk.

- **Taper and centroid use the flesh alone.** A stalk in that comparison reads as
  "this end is thinner", i.e. as an apex.
- **"Reached the stopper" uses the whole pod**, stalk included - a stem-first
  chilli rests on its stalk and has genuinely arrived.
- The stalk cue is now **two-sided** (it can vote either way), so it leads the
  vote. The v18 rule that it must stay below taper applied only while it was
  one-sided.

### Thresholds come from the CHUTE, not from each other (v23)
There are three limits, and it matters where each one is anchored:

| limit | from | finds |
|---|---|---|
| `lim` | empty chute, `l_mean - K*std`, learned and held | the pod |
| `lim_t` = `lim * TIGHT_FRAC` | the body limit | the flesh only |
| `lim2` = `chute_L - CHUTE_MARGIN` | **the chute** | anything at all, incl. a pale stalk |

⚠️ `lim2` used to be `lim + STALK_L_EXTRA`, derived from the body limit. That is
the wrong anchor: how dark the flesh is tells you nothing about how pale a stalk
may be. On the machine it worked out to 69 against a stalk at L 70-75 — the
threshold meant to find the stalk was **brighter than the stalk**, so the cue
read `+0` and the bar chart showed nothing along a plainly visible stalk.

`chute_L` is a **high percentile** (`CHUTE_PCTL`) of L over the channel, not a
mean. The mean is dragged down by anything dark inside the ROI: with rails
present it read 69 on a chute that is really 86, which put the limit back below
the stalk. A percentile ignores those minorities and reports the metal itself.

### Three extents, and which is for what (v22)
Getting these mixed up caused real bugs, twice:

| extent | from | used for |
|---|---|---|
| `lo_a`/`hi_a` → `lo`/`hi` | **loose** profile (anything at all) | has it reached the stopper; the outer ends of the stalk |
| `lo_d`/`hi_d` | **dark** profile | the drawn box, and the redness presence test |
| `lo_f`/`hi_f` | **flesh** profile | taper and centroid |

The stalk is then just `lo_f - lo` at the near end and `hi - hi_f` at the far
end — one expression covering both a stalk dark enough to pass the body limit
and a pale one visible only in the loose profile.

⚠️ **Arrival must be judged on the LOOSE extent.** Judged on the dark extent, a
pod resting on a pale stalk appears to begin at its flesh, three bands up, so it
is called "still sliding" and never judged — on precisely the pods whose stalk is
easiest to see.

⚠️ **Every profile needs its own per-band reference** (`ref`, `ref_t`, `ref2`).
The loose one was left on v19's single-number floor until v22, and that is why
the stalk cue read `-1` on a pod whose stalk was plainly at the stopper.

`W_STALK` (2.4) is above `W_TAPER` (1.3) on purpose: taper can be honestly wrong
when the flesh is fatter away from the stopper, and only the stalk knows better.
There is a test for exactly that (`stalk right, taper wrong`).

### The AUTO threshold is learned once and held (v21)
`lim` used to be recomputed from every frame. That is circular - the chilli
darkens the channel, which lowers the threshold, which changes how the chilli is
measured - and worse, it silently invalidates the empty-chute reference, which
was learned at a *different* threshold. Subtracting it then leaves a constant
error in every band. This is what broke the rails test cases: the flesh profile
came out ~0.25 low everywhere, the fine apex tip vanished into that error, and
was reported as a five-band stalk.

`lim` is now averaged over the warm-up frames and **held**, then nudged
(`LIM_ADAPT`) only on frames that read empty. Lighting drift is followed; the
chilli itself never moves it.

### The empty-chute reference (v19-v20) - what actually bit on the machine
Anything dark inside `CHANNEL_ROI` that is not chilli gets counted as chilli.
Two things always are:

- **The rails down each side**, when the ROI is a touch wider than the bright
  chute. Dark in *every* band.
- **The stopper bar**, when the ROI reaches over it. Dark in the *last band
  only* — and that band is band 0, the stopper end.

The second is the nastier one: with the bar in band 0, `lo` is always 0, so "has
it reached the stopper" is always true even with the pod still short of the bar,
and `w_near` is inflated by the bar so taper is pushed toward STEM on every
chilli. v11 hit the same hardware from a different angle.

v19 subtracted a single floor (`min(prof)`), which handles the rails but **cannot
handle the bar** — a single number cannot remove something that is dark in only
some bands. v20 learns the reference **per band** as a running minimum with a slow
upward leak: every band is empty at some point between chillies, so its smallest
recent value is its empty reading. This subsumes rails, bar, and any fixed
shadow. A mean reference above `FLOOR_WARN` draws `ROI TOO WIDE` on screen.

**Start with an empty chute.** The first `REF_WARMUP` frames report
`LEARNING EMPTY CHUTE`.

⚠️ **Do not add an early return for "the channel looks smooth so it is empty".**
There was one in `object_threshold`, and it *also* skipped learning the
reference — at the one moment the reference can be learned. Emptiness is decided
after the reference is subtracted, which is later and far more reliable.

**Redness as an end-comparison is off (`W_RED = 0`) and should stay off.** With
rails in the ROI the dark rail pixels pass the dark threshold and carry no
redness, so the reading becomes "how much rail is in this band" — the taper
again, inverted. In the rail test case it votes −0.63 against a true taper of
+0.52; dropping it took that case from +0.37 to +0.51. Colour remains a
**presence** test only.

### Wrong STOPPER_SIDE cannot be seen in one frame
A long pod half way down the channel also reaches the far edge, so position
alone cannot separate "still sliding" from "watching the wrong end". Only time
can: the main loop tracks `lo`, and a pod that has not moved for `STUCK_MS`
(2.5 s) while short of the stopper raises **CHECK STOPPER SIDE** on screen and
prints the explanation once. Keep this in the loop, not in `look()`.

### Three bugs the profile rewrite exposed (do not reintroduce)
- **The apex never registered.** Measured at the old body threshold (0.30) the
  fine point of an apex-first pod filled too little of its bands to count as
  chilli, so the pod looked like it had not reached the stopper and was judged
  from the wrong place — or not at all. Hence `BAND_ON = 0.06`.
- **The tapering tip read as a stalk**, on every stem-first pod, dragging the
  answer to APEX. A stalk must be tested for being **pale** (present at the
  loose limit, near-absent at the body limit — `BAND_TIP`), not merely thin.
- **Redness measured the metal, not the chilli.** Averaged over the whole sample
  box, `a_mean` mostly reports how much bare metal is in the box — which is the
  taper again, inverted. It fought the main cue on every chilli. It must be read
  with `get_statistics(thresholds=...)` so only chilli pixels count; if the
  firmware will not filter, the cue is dropped rather than guessed.

⚠️ **The stalk cue is one-sided.** `CHANNEL_ROI` stops at the stopper bar (it has
to — the bar is dark, and v11 proved it reads as a stalk), so when a pod is hard
against the stopper there is no room to see a stalk on the near side. The cue can
realistically only vote APEX. That is sound evidence, but it is why `W_STALK`
must stay below `W_TAPER`: a cue that can only vote one way must never lead, or
every answer drifts that way.

### The two settings that fail silently
Neither raises an error; both invert every answer.
- **`STOPPER_SIDE`** — the solid cyan bar drawn on screen must sit on the end the
  chilli stops against.
- **`INVERT_ANSWER`** — with `CALIBRATE = True`, a stem-first chilli must print a
  POSITIVE score. If it is negative, set this True. That is the whole fix.

### Reading the measurement directly
`CALIBRATE = True` + `SHOW_PROFILE = True` prints the profile band by band —
`raw`, the learned `ref`, what is left, and which band the pod starts and ends
on, with **band 0 always the stopper end**. Use this instead of inferring
geometry from a screenshot of the frame buffer; that has been wrong more than
once, and the user has (rightly) objected to the time it costs.

### Offline test
`manual2/test_offline.py` runs the detector on synthetic chillies on a PC
with the camera modules stubbed — both directions, short/long/off-centre pods,
noisy lighting, a pod still sliding, an empty chute. `python
manual2/test_offline.py` after any threshold change; it catches an inverted
or dead cue in a second. It found all three bugs listed above before the code
ever reached the camera, and its rails/stopper-bar cases reproduce the exact
conditions the real machine was in.

⚠️ The version number lives in ONE place, the `VERSION` constant, because the
banner used to carry a hardcoded copy and went stale — the terminal said
VERSION 18 while v19 was running, which cost a debugging round.

### What has been tried and abandoned
- **Fixed colour ranges to find the chilli** (v1–v7) — broke whenever light changed.
- **`AUTO_CHANNEL`** (v13) — the chilli breaks the bright strip in two, so the
  found region jumped around. A fixed `CHANNEL_ROI` is what works.
- **Blob + `min_corners` + tilt gates** (v6–v17) — unnecessary in a narrow
  channel, and the blob kept merging with nearby shadow, which made the wrong
  end look fat.
- **Tuning the weights to fix a wrong answer** (v10–v17) — seven versions of it
  never worked. The fault was in the measurement, not the weighting. When an
  answer is inverted or constant, print each cue's sign against a known-truth
  input before touching a single weight.

### Outputs
`P0` = stem arrived first · `P1` = tip (apex) arrived first · `P2` = rotate 180°.
Mutually exclusive, written by one function. Blue LED blinks for stem, green for tip.

⚠️ Pins give **3.3 V at ~25 mA — a signal only**. They must drive a relay module or PLC
input, never a solenoid or cylinder directly. Most PLC inputs are 24 V and need a relay.

## Firmware quirks (OpenMV v5.0.0, MicroPython 1.28, H7 Plus, OV5640)

These caused a string of early crashes. Helpers exist — use them:
- Accessors are inconsistently **methods or properties** → use `_get(obj, name)`.
- Draw calls want **tuples for some, flat ints for others** → use `draw_rect(...)`.
- `get_pixel` is unusable; `slice()` does not exist in MicroPython (use `lst[a:b]`).
- `get_statistics(thresholds=...)` may be unsupported. For the *end-comparison* redness
  this is not something to fall back on — an unthresholded average measures bare metal, so
  `region_redness` returns `None` and the cue drops out of the vote. `region_redness_any`
  is the unthresholded version and is for presence checks only.
- `get_histogram().bins()` drives `dark_fraction` — one call per band instead of 24
  `find_blobs` calls. It falls back to blob counting if the histogram misbehaves.

## Working practice

- **Verify with `python -m py_compile`** before handing code over; MicroPython imports
  (`sensor`, `pyb`) will not resolve on the PC, but syntax and dead names are catchable.
- **Do not tune thresholds from screenshots.** This wasted a lot of time: each set of numbers
  fixed one bench scene (keyboard, wood, paper, phone screen) and broke on the next. Tune once
  on the **real machine** with its fixed lighting.
- **Run `python manual2/test_offline.py`** after touching any threshold or weight. It
  exercises the detector on synthetic chillies with the camera stubbed out and catches an
  inverted or dead cue in a second.
- **When it reports EMPTY, read the `CALIB` line** — `bands lo-hi`, `a=`, `L<=` say whether
  the chilli was seen at all and which gate rejected it.
- `CALIBRATE = True` keeps all pins off and prints every cue; `DEBUG = True` draws the
  channel, the cyan stopper bar, and the width profile as a bar chart beside the channel.
- **Accuracy is not known until it is counted.** Twenty chillies, ten each way, tally the
  wrong calls. Nothing before that is evidence.

## Setup that actually matters

Lighting and mounting decide accuracy far more than code:
- **Diffuse the light.** Glare on the metal channel splits the chilli's blob; shadow beside
  the chilli merges into it and makes it look fat.
- **Bright channel, dark chilli.** Keep `CHANNEL_ROI` on the metal channel only — dark wood
  or table just outside it competes with the chilli for the darkness test.
- **Fill the frame.** The chilli should occupy most of the channel view.
- **Flat lighting is what makes scores weak.** A score near ±0.1 means the two ends look
  alike to the camera. Diffused light slightly off to one side gives the pod some shading
  along its length, which is what the taper cue reads.
- **Two settings fail silently** — see "The two settings that fail silently" above.
  `STOPPER_SIDE` (cyan bar on the right end) and `INVERT_ANSWER` (stem-first must score
  positive in CALIBRATE). Both invert every answer with no error.

## Deploying

1. Calibrate on the machine with `CALIBRATE = True`: `CHANNEL_ROI` on the metal only,
   `STOPPER_SIDE` so the cyan bar is on the stopper end, then `INVERT_ANSWER` so a
   stem-first chilli scores positive. Then fix `MANUAL_L`.
2. Set `CALIBRATE = False`, `DEBUG = False`; confirm P0/P1 with a multimeter.
3. Tools → Save open script to OpenMV Cam (as main.py), eject the drive, reset.
4. Disconnect the IDE and reset again — `main.py` only auto-runs when the IDE is not attached.
5. Power via USB 5 V or regulated 5 V on VIN.

## Vendor material (do not publish)

`chili_files/` on the developer's Desktop also holds company material: `Imaging System.pptx`,
`Chilli Pics.pptx`, `Machine Vision Project-1.pdf`, a `.stp` machine CAD assembly, and the
vendor's `REQ1.zip`/`REQ2.zip`. **These are excluded by `.gitignore`** and must not be pushed to the public repo — they
show the employer's machine and IP. Note the ignore file is now a *blacklist*, so a new
confidential file type dropped into this folder is **not** automatically safe: check
`git status` before committing, and add the pattern if anything unexpected appears.

The vendor's own detection logic ships as compiled `.mpy` files (`hog_lbp_db`, `stm_nostm`),
which cannot be read or tuned; their surrounding `main.py` is mostly padding. Replacing that
black box with open, tunable logic is the point of this project.

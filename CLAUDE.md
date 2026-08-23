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
  open_mv_v18.py         <- highest number = current
  open_mv_v17.py
  open_mv_v16.py
  ...
  test_v18_offline.py    <- runs the detector on a PC, no camera needed
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

Values below are the ones in `open_mv2.py` / `manual2/open_mv_v18.py`.

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
2. **Extent** = bands with `dark_fraction >= BAND_ON` (0.06, deliberately low).
3. **Presence gates:** `MIN_CHILI_STD` (an empty chute is smooth) and
   `MIN_CHILI_RED` against bare-metal shadow. Colour is a *presence* test only —
   it must never *reject* a candidate, because a pink cloth reads redness 20–40
   while a dark dried chilli reads 4–8.
4. **Must be at the stopper:** `lo <= STOPPER_TOUCH_BANDS`, else `CHILLI STILL
   MOVING` and no decision.
5. **Four cues**, all comparisons within the same chilli:

   | Cue | Weight | Says STEM when… |
   |---|---|---|
   | taper | 1.6 | mean profile over the near third > the far third |
   | stalk | 1.0 | pale bands run past that end (see caveat below) |
   | centroid | 0.5 | profile mass sits toward that end |
   | redness | 0.3 | that end is paler |

   A cue that does not fire is left **out of the weight total**, so it cannot
   dilute the ones that did.
6. **State machine** WAIT → CHECK → LOCKED → CLEARING. Score averaged over
   `SMOOTH_N = 7` frames, `STABLE_N = 4` agreeing frames to lock (6 if cues
   disagree), answer held until the chilli leaves, then `EMPTY`. On
   `MAX_WAIT_MS` timeout it emits `DEFAULT_ANSWER` marked `[LOW CONFIDENCE]`
   rather than stalling the line.

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

### Offline test
`manual2/test_v18_offline.py` runs the detector on synthetic chillies on a PC
with the camera modules stubbed — both directions, short/long/off-centre pods,
noisy lighting, a pod still sliding, an empty chute. `python
manual2/test_v18_offline.py` after any threshold change; it catches an inverted
or dead cue in a second. It found all three bugs listed above before the code
ever reached the camera.

### What has been tried and abandoned
- **Fixed colour ranges to find the chilli** (v1–v7) — broke whenever light changed.
- **`AUTO_CHANNEL`** (v13) — the chilli breaks the bright strip in two, so the
  found region jumped around. A fixed `CHANNEL_ROI` is what works.
- **Blob + `min_corners` + tilt gates** (v6–v17) — unnecessary in a narrow
  channel, and the blob kept merging with nearby shadow, which made the wrong
  end look fat.
- **Tuning the weights to fix a wrong answer** (v10–v17) — seven versions of it
  never worked. The fault was in the measurement, not the weighting.

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
- **Run `python manual2/test_v18_offline.py`** after touching any threshold or weight. It
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

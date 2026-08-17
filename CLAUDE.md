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

## Files

| File | Status |
|---|---|
| `chili_stopper_factory.py` | **CURRENT** — stem-vs-tip at the stopper. This is the one to work on. |
| `chili_factory_multi.py` | Old LEFT/RIGHT approach, tracked several chillies at once |
| `main.py` | Old factory version using empty-tray background subtraction |
| `chili_leftright_gpio.py`, `chili_leftright_v2.py` | Earlier LEFT/RIGHT versions with GPIO |
| `chili_stem_detect.py` | First attempt, fixed red colour range |
| `chili_bench_test.py` | Loose bench tester that reports why a frame was rejected |

⚠️ `main.py` in this repo is an **old version**. When deploying, the *current* file is
renamed to `main.py` on the camera — do not copy the repo's `main.py`.

**Version the current file.** `chili_stopper_factory.py` carries a `VERSION n` header with a
short changelog. Bump it and add a line on every change.

## How the current detector works

1. **Find the chilli by darkness, not colour.** The brightness limit is recomputed from each
   frame (`L <= l_mean - DARK_K*l_stdev`, clamped). Fixed colour ranges were tried repeatedly
   and always broke when the light changed or a chilli looked brown rather than red.
2. **Pick the reddest candidate.** Among blobs passing the shape gates, the reddest wins.
   This is what stops it locking onto wood, keyboards, shadows and table edges.
3. **Follow the chilli's own axis** (`min_corners`, with a bounding-box fallback), so the
   chilli can lie at any angle.
4. **Measure both ends** with one small box at each end, inset from the tips.
   - **Thickness (main clue):** the stem end is fat and blunt, the tip tapers. Shape-based,
     so glare cannot break it.
   - **Redness (helper):** the stem end is paler. Used when readable, ignored when washed out.
5. **State machine** WAIT → CHECK → LOCKED → CLEARING gives one locked answer per chilli.

**Only the dark BODY is detected — the pale stalk is not dark, so it is invisible to the
detector.** Size gates must therefore suit the body, not a whole chilli. Getting this wrong
was the cause of a long run of false "EMPTY" results.

### Outputs
`P0` = stem arrived first · `P1` = tip (pod) arrived first · `P2` = rotate 180°.
Mutually exclusive, written by one function. Blue LED blinks for stem, green for tip.

⚠️ Pins give **3.3 V at ~25 mA — a signal only**. They must drive a relay module or PLC
input, never a solenoid or cylinder directly. Most PLC inputs are 24 V and need a relay.

## Firmware quirks (OpenMV v5.0.0, MicroPython 1.28, H7 Plus, OV5640)

These caused a string of early crashes. Helpers exist — use them:
- Accessors are inconsistently **methods or properties** → use `_get(obj, name)`.
- Draw calls want **tuples for some, flat ints for others** → use `draw_safe(...)`.
- `get_pixel` is unusable; `slice()` does not exist in MicroPython (use `lst[a:b]`).
- `find_blobs(margin=...)` and `get_statistics(thresholds=...)` may be unsupported — both
  are wrapped in `try/except` with fallbacks.

## Working practice

- **Verify with `python -m py_compile`** before handing code over; MicroPython imports
  (`sensor`, `pyb`) will not resolve on the PC, but syntax and dead names are catchable.
- **Do not tune thresholds from screenshots.** This wasted a lot of time: each set of numbers
  fixed one bench scene (keyboard, wood, paper, phone screen) and broke on the next. Tune once
  on the **real machine** with its fixed lighting.
- **When it reports EMPTY, read the diagnostic line** — `blobs=`, `shape_ok=`, `best_tilt=`,
  `L<=` say whether the chilli was seen at all and which gate rejected it.
- `CALIBRATE = True` keeps all pins off; `DEBUG = True` draws the working boxes.

## Setup that actually matters

Lighting and mounting decide accuracy far more than code:
- **Diffuse the light.** Glare on the metal channel splits the chilli's blob; shadow beside
  the chilli merges into it and makes it look fat.
- **Bright channel, dark chilli.** Keep `CHANNEL_ROI` on the metal channel only — dark wood
  or table just outside it competes with the chilli for the darkness test.
- **Fill the frame.** The chilli should occupy most of the channel view.
- **`STOPPER_SIDE` is the one setting that fails silently.** Wrong value inverts every answer
  with no error. The cyan box on screen must sit on the end touching the stopper.

## Deploying

1. Calibrate on the machine (`CHANNEL_ROI`, `STOPPER_SIDE`, size gates) with `CALIBRATE = True`.
2. Set `CALIBRATE = False`, `DEBUG = False`; confirm P0/P1 with a multimeter.
3. Tools → Save open script to OpenMV Cam (as main.py), eject the drive, reset.
4. Disconnect the IDE and reset again — `main.py` only auto-runs when the IDE is not attached.
5. Power via USB 5 V or regulated 5 V on VIN.

## Vendor material (do not publish)

`chili_files/` on the developer's Desktop also holds company material: `Imaging System.pptx`,
`Chilli Pics.pptx`, `Machine Vision Project-1.pdf`, a `.stp` machine CAD assembly, and the
vendor's `REQ1.zip`/`REQ2.zip`. **These are excluded from git by a whitelist `.gitignore`** and
must not be pushed to the public repo — they show the employer's machine and IP.

The vendor's own detection logic ships as compiled `.mpy` files (`hog_lbp_db`, `stm_nostm`),
which cannot be read or tuned; their surrounding `main.py` is mostly padding. Replacing that
black box with open, tunable logic is the point of this project.

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
  open_mv_v17.py   <- highest number = current
  open_mv_v16.py
  open_mv_v15.py
  ...
  README.md        <- version table + the threshold guide
open_mv2.py        <- working copy, same as the highest version
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

Values below are the ones in `open_mv2.py` / `manual2/open_mv_v17.py`.

1. **Find the chilli by darkness.** The channel metal is bright, the chilli is dark.
   `MANUAL_L = None` measures the dividing line from each frame (`l_mean - DARK_K*l_stdev`,
   clamped to `DARK_L_MIN..DARK_L_MAX`, currently capped at **50** so shadows on aluminium
   are excluded). Set `MANUAL_L` to a fixed number for production — repeatable, testable,
   and adjustable by a technician. The line in use is drawn on screen as `L<=NN AUTO/SET`.
2. **Two presence gates before anything is judged:**
   - `MIN_CHILI_STD = 6.0` — an empty chute is uniformly bright; anything lying in it
     breaks that up.
   - `MIN_CHILI_RED = 6.0` — bare-metal shadows read `a_mean < 4`, a chilli reads higher.
     **Note the nuance:** colour still cannot answer *"which end is the stem"*, and it must
     never be used to *reject* a candidate outright — a pink cloth reads redness 20–40 while
     a dark dried chilli reads 4–8, so a rejection threshold that admits real chillies also
     admits brighter objects. It is only safe here as a *presence* gate against shadow.
3. **Follow the chilli's own axis** (`min_corners`, bounding-box fallback) — any angle works.
4. **Four relative end-comparisons**, weights in the config:
   | Cue | Weight | Says STEM when… |
   |---|---|---|
   | centroid shift | 1.5 | the mass sits toward that end |
   | thickness | 1.2 | that end is fatter |
   | redness | 0.6 | that end is paler |
   | stalk | 0.4 | pale stalk pokes out past that end |

   All are comparisons **within the same chilli**, never absolute thresholds. Disagreement
   between cues reduces confidence so a confusing chilli needs more frames before locking.
5. **Density, not raw counts** (pixels ÷ area). Boxes at the frame edge get clipped and the
   stopper end is at the edge by definition — raw counts biased every decision toward APEX.
6. **Every measuring box is clipped to `CHANNEL_ROI`.** The stopper bar sits just past the
   stopper end and is dark; unclipped, the stalk check read that hardware as a stalk on
   *every* chilli and pushed nearly all answers to STEM.
7. **`BLOB_MARGIN = 2`** keeps the blob tight to the body so it never merges with a nearby
   shadow — a merged shadow makes the wrong end look fat, which corrupts the main cue.
8. **State machine** WAIT → CHECK → LOCKED → CLEARING, score averaged over
   `VOTE_HISTORY_MAX = 7` frames and held for `STABLE_N = 4`, gives one locked answer
   per chilli.

**Only the dark BODY is detected — the pale stalk is not dark, so it is invisible to the
detector.** Size gates must suit the body, not a whole chilli. Getting this wrong caused a
long run of false `EMPTY` results.

### What has been tried and abandoned
- **Fixed colour ranges to find the chilli** (v1–v7) — broke every time the light changed.
- **`AUTO_CHANNEL`, finding the bright chute automatically** (v13) — the chilli breaks the
  bright strip in two, so the found region jumped around. Reverted in v14; a fixed
  `CHANNEL_ROI` on the chute is what works.

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
vendor's `REQ1.zip`/`REQ2.zip`. **These are excluded by `.gitignore`** and must not be pushed to the public repo — they
show the employer's machine and IP. Note the ignore file is now a *blacklist*, so a new
confidential file type dropped into this folder is **not** automatically safe: check
`git status` before committing, and add the pattern if anything unexpected appears.

The vendor's own detection logic ships as compiled `.mpy` files (`hog_lbp_db`, `stm_nostm`),
which cannot be read or tuned; their surrounding `main.py` is mostly padding. Replacing that
black box with open, tunable logic is the point of this project.

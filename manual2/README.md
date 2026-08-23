# manual2 — version history

One numbered file per change. Nothing here is ever overwritten, so every
version stays on record and you can always go back to one that worked.

**The highest number is the current one.**

| File | Version | What changed |
|---|---|---|
| `open_mv_v23.py` | 23 | **Current.** The stalk limit is now set by the **chute**, not by the body limit. It was `lim + 20` = 69, while a dried stalk on a white chute sits around L 70-75 — the threshold meant to find the stalk was *brighter than the stalk*, so it was never measured and the cue read `+0`. The empty-chute brightness is learned during warm-up (as a high percentile, so dark rails and the stopper bar cannot drag it down) and the limit is `chute - CHUTE_MARGIN`. Also: the banner is placed beside `CHANNEL_ROI` instead of on top of it, and the band-by-band profile prints on **every locked decision**, not only in CALIBRATE. |
| `open_mv_v22.py` | 22 | Fixes the stalk cue, which was still unreliable. Two causes. (1) The loose profile the stalk lives in was the one place still using v19's **single-number floor** — everything else moved to a per-band reference in v20. If the sampled band held the stopper bar, the floor came out high and wiped the real stalk out. It now has its own per-band reference. (2) The pod's extent came from the dark profile, so a **pale stalk did not count as part of the pod** — a pod resting on its stalk appeared to start at its flesh three bands up and was reported as "still sliding", never judged, on exactly the pods whose stalk was easiest to see. Extent now comes from the loose profile. With both fixed, the stalk is simply *the part of the pod that is not flesh*, at either end. `W_STALK` 1.6 → 2.4 so a stalk that has been seen outvotes taper, which can be honestly wrong. |
| `open_mv_v21.py` | 21 | Tells the **stalk from the flesh by brightness**, not by width. A stalk dark enough to pass the body limit used to be swallowed into the pod, and taper then read it as "this end is thinner" - i.e. as an apex. That is how a pod lying stalk-down toward the stopper locked APEX at -0.73. The profile is now measured at two limits: `lim` for anything at all, `lim_t` for flesh only. What lies between them is stalk, at whichever end it sits. Taper and centroid use the flesh alone; "reached the stopper" still uses the whole pod, stalk included. The stalk cue is now two-sided so it leads the vote. Also: the AUTO threshold is learned from the empty chute and **held**, instead of being recomputed from a frame that has a chilli in it - that was circular, and it silently invalidated the reference. |
| `open_mv_v20.py` | 20 | The empty-chute reference is now learned **per band**, as a running minimum. v19's single floor removed the rails down the sides (dark in every band) but could not remove the **stopper bar** inside the bottom edge of the ROI, which is dark in the last band only — so band 0 was always full, `lo` was always 0, "has it reached the stopper" was always true even with the pod short of the bar, and taper was pushed toward STEM on every chilli. Also: `SHOW_PROFILE` prints the whole measurement band by band as text, the version is a single constant so the banner can no longer disagree with the header, and the "channel is smooth so it must be empty" shortcut is gone (it skipped learning the reference at the one moment it could be learned). |
| `open_mv_v19.py` | 19 | Subtracts the **empty-channel floor** from every band. A `CHANNEL_ROI` slightly wider than the bright chute catches the dark rails down each side; those sit in every band, so the pod appeared to fill the whole channel, `lo` was always 0 (the "reached the stopper" check could never fire) and taper compared two lengths of rail. That is what made a stem-first pod lock APEX five times running. Also: a pod that sits still short of the stopper for 2.5 s now says **CHECK STOPPER SIDE** instead of "still moving" forever, and the redness end-comparison is switched off (`W_RED = 0`) because with rails in the ROI it votes against the truth. |
| `open_mv_v18.py` | 18 | Rewrote the measurement as a **width profile** along the channel instead of two small boxes at the ends, and fixed three bugs the profile exposed: the pointed apex never registered as "chilli" so apex-first pods were never judged; the tapering tip was being read as a stalk on every stem-first pod; and redness averaged over the whole box was really measuring bare metal, i.e. the taper inverted, so the colour cue fought the main cue. Adds `INVERT_ANSWER`, a "still sliding" state, and an offline test (`test_offline.py`). |
| `open_mv_v17.py` | 17 | Color Presence Gate (`MIN_CHILI_RED = 6.0`): Rejects bare metal shadows on aluminum chute (which have `a_mean < 4.0`), eliminating phantom chilli detections and correctly displaying `STOPPER: EMPTY` when container is empty. |
| `open_mv_v16.py` | 16 | Fixed shadow-merge bias past stopper: set tight `CHANNEL_ROI = (200, 50, 28, 138)` stopping cleanly at the stopper bar, tightened `BLOB_MARGIN = 2` to prevent merging with table shadows, and capped `DARK_L_MAX = 50`. |
| `open_mv_v15.py` | 15 | Introduced Mass Centroid Shift (`s_centroid`, W=1.5), `END_INSET = 0.25`, and balanced ensemble voting. |
| `open_mv_v14.py` | 14 | Reverted `AUTO_CHANNEL` (v13 split/lost blobs with chilli present). Fixed narrow `CHANNEL_ROI = (186, 50, 36, 160)` centered on the chute. Smoothing increased (window 9, stable frames 5). |
| `open_mv_v13.py` | 13 | Attempted automatic bright-channel finder (`AUTO_CHANNEL`), but failed when chilli broke bright strip or altered ROI dynamically |
| `open_mv_v12.py` | 12 | `CHANNEL_ROI` moved to the middle of the picture, (90, 60, 140, 120) |
| `open_mv_v11.py` | 11 | Fixed a bias that pushed nearly every answer to STEM: the stalk check was reading the stopper bar itself as "stalk". All measuring boxes are now kept inside the channel |
| `open_mv_v10.py` | 10 | Manual / automatic threshold switch (`MANUAL_L`); the dividing line in use is shown on screen as `L<=NN AUTO` or `L<=NN SET` |

## Setting it up on the machine — do these two first

Everything else is fine-tuning. These two decide whether the answers are right
or exactly backwards, and neither of them shows up as an error.

### Start with the chute EMPTY

v20 learns what the empty chute looks like, band by band, and subtracts it. That
is what removes the dark rails at the ROI edges **and** the stopper bar if the
ROI reaches over it — the things that were making a stem-first pod read APEX.

So **start the program with no chilli in the channel.** The screen shows
`LEARNING EMPTY CHUTE` for about two seconds. It keeps learning as it runs, so a
pod left sitting in the channel will not poison it permanently, but a clean start
is worth two seconds.

### 0. Is the channel box on the metal only?

With `DEBUG = True` the screen shows a **blue bar chart** beside the channel —
that is the pod's width, band by band. On an empty chute the bars should be
almost nothing. If there are bars all the way down an empty channel, the magenta
`CHANNEL_ROI` box is wider than the bright chute and is catching the dark rails
at its edges.

v19 subtracts that floor automatically, so it still works — but the screen warns
`ROI TOO WIDE - FLOOR 0.xx` when there is a lot of it. Narrow `CHANNEL_ROI` (raise
`x`, lower `w`) until the warning goes and the bars only appear where the chilli
actually is. This was the real cause of the stem-reads-as-apex problem.

### 1. Is the cyan bar on the right end?

Run with `DEBUG = True`. A **solid cyan bar** is drawn across one end of the
magenta channel box. That bar is where the code thinks the stopper is.

It must sit on the end the chilli actually stops against. If it is on the wrong
end, change `STOPPER_SIDE` (`"bottom"` `"top"` `"left"` `"right"`) until it moves
there. Getting this wrong inverts every single answer.

v19 will tell you: leave a chilli resting at the stopper and if it sits still for
2.5 seconds without the code agreeing it has arrived, the screen shows **CHECK
STOPPER SIDE** and the terminal explains why.

### 2. Is the answer the right way round?

Set `CALIBRATE = True`. Pins stay off and the numbers print.

1. Put a chilli in **stem first** — stem end touching the stopper.
2. Read `score` in the terminal.
   - **Positive** → correct. Leave `INVERT_ANSWER = False`.
   - **Negative** → set `INVERT_ANSWER = True`. That is the whole fix.
3. Put a chilli in **apex first** and check the score flips sign.
4. Set `CALIBRATE = False`.

A good chilli should read about **±0.4 or more**. Around ±0.1 means the two ends
look nearly alike to the camera — usually flat lighting, so see below.

### Seeing exactly what the camera measures

With `CALIBRATE = True` and `SHOW_PROFILE = True`, the terminal prints the whole
measurement as text every 20 frames:

```
  band | pod  flesh | width          (flesh = pod minus stalk)
    0  | 0.00 0.00  |                     <-- STOPPER (bottom)
    1  | 0.11 0.00  | ##      << STALK  [pod starts]
    2  | 0.12 0.00  | ##      << STALK
    3  | 0.62 0.62  | ############       [flesh starts]
   ...
   16  | 0.08 0.08  | #                  [pod ends] [flesh ends]
   23  | 0.00 0.00  |                     <-- far end
  flesh near third 0.55  far third 0.18  taper +0.50 -> STEM at stopper
  stalk bands: 2 at the stopper end, 0 at the far end -> STEM at stopper
```

`pod` is everything the chilli occupies; `flesh` is the dark red part only.
Bands with pod but no flesh are the **stalk**, and are marked `<< STALK`.
**Band 0 is always the stopper end.**

Read it like this:

- stalk bands near band 0 -> the stem end is at the stopper -> **STEM**
- stalk bands near band 23 -> the stem is at the far end -> **APEX**
- pod does not start at band 0 or 1 -> it has not reached the stopper
- flesh never starts at all -> the threshold is too tight, or it is not a chilli

This readout settles arguments that squinting at the frame buffer cannot.

### Checking it before you trust it

Run twenty chillies, ten each way, and count the wrong ones. Until that has been
done the accuracy is unknown. The `>>>` line printed for each chilli records the
score and every cue, so a wrong call can be looked up afterwards.

`test_offline.py` runs the detector on drawn-on-screen chillies on a PC, with
no camera:

```bash
python manual2/test_offline.py
```

It checks both directions, short and long pods, off-centre pods, noisy lighting,
**a ROI with dark rails in it**, a pod still sliding, and an empty chute. Run it
after changing any threshold — it catches an inverted or dead cue in a second,
which is faster than finding out at the machine.

## The threshold — the one number to adjust

Brightness runs 0 (black) to 100 (white). The metal channel is bright, a chilli
is dark. `MANUAL_L` is the dividing line between them: **anything darker than
the line is treated as chilli, anything brighter as channel.**

```python
MANUAL_L = None    # AUTOMATIC - the camera measures the line every frame
MANUAL_L = 58      # MANUAL    - the line is fixed and never moves
```

**Automatic** follows the lighting on its own. Use it while the lighting is
still being set up.

**Manual** always gives the same answer for the same picture, which is what a
production machine needs and what can be tested and signed off. Use it once the
light is fixed in place.

### Setting the number

1. Fix the lamp in place — diffused, off to one side. Do not move it afterwards.
2. Run with `MANUAL_L = None` and read `L<=NN` on screen with a chilli in the
   channel. Try a light one, a dark one, a big one; note the numbers.
3. Take the middle of what you saw and put it in `MANUAL_L`.
4. Run again. The screen should read `L<=NN SET`.

### If it needs adjusting

| Problem | Fix |
|---|---|
| Chilli not detected | **Raise** the number (58 → 62) |
| Shadow counted as part of the chilli | **Lower** the number (58 → 54) |

Move in steps of about 4. After each change, look at the green box: it should
hug the chilli — no shadow included, nothing missing.

If the lighting is ever changed, set `MANUAL_L = None`, read the new number,
and put it back.

## Outputs

`P0` = stem arrived first · `P1` = tip (apex) arrived first · `P2` = rotate 180°

These are **3.3 V signals at about 25 mA**. They must drive a relay module or a
PLC input — never a cylinder or solenoid directly.

## Modes while testing

- `CALIBRATE = True` — pins stay off, numbers printed. Safe for tuning.
- `DEBUG = True` — draws the channel box and the measuring boxes on screen.

# manual2 — version history

One numbered file per change. Nothing here is ever overwritten, so every
version stays on record and you can always go back to one that worked.

**The highest number is the current one.**

| File | Version | What changed |
|---|---|---|
| `open_mv_v19.py` | 19 | **Current.** Subtracts the **empty-channel floor** from every band. A `CHANNEL_ROI` slightly wider than the bright chute catches the dark rails down each side; those sit in every band, so the pod appeared to fill the whole channel, `lo` was always 0 (the "reached the stopper" check could never fire) and taper compared two lengths of rail. That is what made a stem-first pod lock APEX five times running. Also: a pod that sits still short of the stopper for 2.5 s now says **CHECK STOPPER SIDE** instead of "still moving" forever, and the redness end-comparison is switched off (`W_RED = 0`) because with rails in the ROI it votes against the truth. |
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

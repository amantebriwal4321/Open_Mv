# manual2 — version history

One numbered file per change. Nothing here is ever overwritten, so every
version stays on record and you can always go back to one that worked.

**The highest number is the current one.**

| File | Version | What changed |
|---|---|---|
| `open_mv_v16.py` | 16 | **Current.** Fixed shadow-merge bias past stopper: set tight `CHANNEL_ROI = (200, 50, 28, 138)` stopping cleanly at the stopper bar, tightened `BLOB_MARGIN = 2` to prevent merging with table shadows, and capped `DARK_L_MAX = 50`. |
| `open_mv_v15.py` | 15 | Introduced Mass Centroid Shift (`s_centroid`, W=1.5), `END_INSET = 0.25`, and balanced ensemble voting. |
| `open_mv_v14.py` | 14 | Reverted `AUTO_CHANNEL` (v13 split/lost blobs with chilli present). Fixed narrow `CHANNEL_ROI = (186, 50, 36, 160)` centered on the chute. Smoothing increased (window 9, stable frames 5). |
| `open_mv_v13.py` | 13 | Attempted automatic bright-channel finder (`AUTO_CHANNEL`), but failed when chilli broke bright strip or altered ROI dynamically |
| `open_mv_v12.py` | 12 | `CHANNEL_ROI` moved to the middle of the picture, (90, 60, 140, 120) |
| `open_mv_v11.py` | 11 | Fixed a bias that pushed nearly every answer to STEM: the stalk check was reading the stopper bar itself as "stalk". All measuring boxes are now kept inside the channel |
| `open_mv_v10.py` | 10 | Manual / automatic threshold switch (`MANUAL_L`); the dividing line in use is shown on screen as `L<=NN AUTO` or `L<=NN SET` |

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

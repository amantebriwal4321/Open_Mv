# Calibration Guide — Chilli Stem Detection System

## Overview

This guide explains how to tune the detection system for your specific factory conditions using the live trackbar controls.

---

## Step 1: Physical Setup

1. Mount camera directly above or at 45° angle over the V-channel.
2. Ensure consistent, diffused lighting (avoid direct sunlight).
3. Place a known chilli (with visible green stem) in the channel.
4. Run: `python main_opencv.py`

---

## Step 2: ROI Calibration

Edit `config.py` → `ROI_X_START`, `ROI_X_END`, `ROI_Y_START`, `ROI_Y_END`:

```python
# Crop to only the V-channel area
ROI_X_START = 0.15   # adjust until left edge of channel
ROI_X_END   = 0.85   # adjust until right edge of channel
ROI_Y_START = 0.2
ROI_Y_END   = 0.8
```

**Goal**: Only the chilli and V-channel are visible — no factory background.

---

## Step 3: Red Chilli Detection Tuning

Use trackbars: `R1 H Min`, `R1 H Max`, `R2 H Min`, `R2 H Max`, `Red S Min`, `Red V Min`

### Procedure:
1. Watch **Window 2 (Masks)** — the red overlay should cover the entire chilli body.
2. If chilli body is NOT fully red:
   - Decrease `Red S Min` (try 40-50 for dried chillies).
   - Decrease `Red V Min` (try 30-40 for dark varieties like Byadgi).
3. If background pixels appear red:
   - Increase `Red S Min` and `Red V Min`.
4. For very dark dried chillies:
   - Widen H2 range: set `R2 H Min = 150`.

### Recommended starting values by variety:

| Variety | R1 H | R2 H | S Min | V Min |
|---------|-------|-------|-------|-------|
| Fresh red (Guntur) | 0-10 | 160-180 | 70 | 50 |
| Dried red (Teja) | 0-12 | 155-180 | 50 | 40 |
| Dark (Byadgi) | 0-15 | 150-180 | 40 | 30 |

---

## Step 4: Stem Detection Tuning

Use trackbars: `Grn H Min`, `Grn H Max`, `Grn S Min`

### For fresh green stems:
1. Watch **Window 2** — green overlay should appear ONLY on the stem.
2. Typical: H 35-85, S Min 40.
3. If stem is yellowish-green: lower `Grn H Min` to 30.

### For dried brown stems:
- Brown stems won't appear green. The system falls back to **Approach 2 (Density)** automatically.
- This is expected and correct behaviour.

---

## Step 5: Minimum Chilli Area

Trackbar: `Min Area`

- Set this above the noise level but below the smallest chilli.
- Watch **Window 1** — if "No Chilli Detected" appears when a chilli is present, **decrease** this value.
- If it detects random noise as chilli, **increase** this value.
- Typical range: 1500-5000 depending on resolution and distance.

---

## Step 6: Confidence Threshold

Trackbar: `Conf Thr`

- Controls the minimum ensemble confidence to send an IO signal.
- **Start at 60** (default).
- If too many uncertain results → lower to 50.
- If too many wrong signals → raise to 70.

---

## Step 7: Morphology and Blur

Trackbars: `Morph K`, `Blur K`

- `Morph K` = 5 (default). Increase to 7 for noisy images.
- `Blur K` = 5 (default). Increase for very wrinkled dried chillies.
- Both must be **odd numbers** (the system auto-corrects even values).

---

## Step 8: Reflection Handling

Edit `config.py` → `REFLECTION_THRESHOLD`:

```python
REFLECTION_THRESHOLD = 240  # default
```

- If metallic surface causes false detections, **lower** to 220.
- If valid chilli pixels are being masked, **raise** to 250.
- Check by watching the preprocessed image — reflections should not appear as coloured blobs.

---

## Step 9: Validation

1. Run 20 chillies through the system manually.
2. Check **Window 4 (Stats)** for accuracy.
3. Check the CSV log for per-chilli confidence.
4. Look for patterns:
   - If Approach 1 (Colour) is always winning → great, system is well-tuned.
   - If Approach 2 (Density) is mostly winning → stems are not colour-detectable (normal for dried chillies).
   - If many "UNCERTAIN" results → check lighting and thresholds.

---

## Step 10: Lock Values for OpenMV

Once tuned, transfer final values to `main_openmv.py`:

1. Note down all trackbar positions.
2. Convert HSV values to LAB thresholds using OpenMV's threshold editor tool.
3. Update the constants at the top of `main_openmv.py`.
4. Run OpenMV IDE → Tools → Machine Vision → Threshold Editor to fine-tune LAB values.

---

## Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| No chilli detected | Lower `Min Area`, check ROI covers channel |
| Wrong side detected | Check stem colour thresholds, try lower S Min |
| Reflections cause errors | Lower `REFLECTION_THRESHOLD` |
| Too slow processing | Reduce frame resolution, increase ROI crop |
| Dried chilli fails | Rely on Approach 2, lower `Red S Min` and `Red V Min` |
| All uncertain | Lower `Conf Thr`, check lighting consistency |

---

## Batch Testing

After calibration, run the test harness:

```bash
python test_harness.py --folder test_images --report calibration_report.csv
```

Name test images with the correct label:
- `chilli_001_LEFT.jpg`
- `chilli_002_RIGHT.jpg`

Target: **>90% ensemble accuracy** before deploying to production.

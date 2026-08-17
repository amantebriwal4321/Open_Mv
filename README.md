# Open_MV — Chilli Stem Orientation Detection & Sorting

Production machine-vision system for the **OpenMV Cam H7 Plus** deployed on a factory chilli de-stemming machine.

---

## 📌 Project Overview
Dried chillies travel down a metal channel and stop against a mechanical stopper. Every chilli must reach the cutter facing the **same orientation** (stem presenting to the blade). Chillies arriving the wrong way round are signaled for 180° rotation.

The camera identifies the orientation at the stopper and outputs standard 3.3 V industrial GPIO signals:

| Detection Result | Output Pin | LED Indicator | Action |
|---|---|---|---|
| **STEM** arrived at stopper | **P0** HIGH (3.3 V) | 🟦 Blue (Blinking in Calib) | Present to cutter |
| **APEX / POD** arrived at stopper | **P1** HIGH (3.3 V) | 🟩 Green (Blinking in Calib) | Rotate / Flip |
| **ROTATE 180°** Command | **P2** HIGH (3.3 V) | — | Activates 180° rotator |

> **Wiring Note:** OpenMV GPIO pins output 3.3 V (max ~25 mA). Use these signals to drive a PLC input, optocoupler, or relay module.

---

## 📁 Repository Structure

```
├── main/                               # 🌟 PRODUCTION OPENMV CODE
│   ├── chili_stopper_factory.py        # Core factory detector with full HUD & GPIO
│   ├── main.py                         # Standalone auto-run script for OpenMV camera
│   └── CLAUDE.md                       # Complete engineering design notes & specs
│
├── Trial codes/                        # 🧪 EXPERIMENTAL & HISTORICAL TRIALS
│   ├── chili_bench_test.py             # Loose bench tester printing rejection metrics
│   ├── chili_factory_multi.py          # Multi-blob shape & aspect tracking trials
│   ├── chili_leftright_gpio.py         # Early GPIO stage prototypes
│   ├── chili_leftright_v2.py           # Early temporal smoothing experiments
│   ├── chili_stem_detect.py            # Initial color segmentation approach
│   ├── REQ1/                           # First requirement trial scripts
│   └── REQ2/                           # Second requirement trial scripts
│
├── System1/                            # System 1 modules & calibration harnesses
├── System2/                            # System 2 OpenCV/OpenMV comparative harnesses
├── CLAUDE.md                           # System engineering guidelines & context
└── README.md                           # Project documentation
```

---

## ⚙️ How the Detection Works

1. **Full-Chute Stalk Extension Detection (`check_stalk`)**:
   * Scans across the entire channel width beyond the dark body.
   * Accurately detects pale/tan curved or bent stalks extending towards or away from the stopper.
2. **Adaptive Contrast & Organic Color Gate (`MIN_CHILI_A = 6.5`)**:
   * Measures LAB color space chromaticity. Neutral grey metal chutes and desk shadows ($A \le 3.0$) are instantly rejected as empty. Only real dried red chillies ($A \ge 10.0$) trigger detection.
3. **Body Taper & Relative Redness Scoring**:
   * Compares width of the calyx shoulder vs. the tapered pointed tip.
   * Compares redness saturation between both ends.
4. **State Machine & Power Hold**:
   * Confirms arrival in ~75 ms, latches decision, and **holds 3.3 V power ON** until the chilli physically clears the chute.

---

## 🚀 Quick Start & Deployment

### Running in OpenMV IDE (Testing / Production):
1. Open OpenMV IDE and connect to the OpenMV Cam H7 Plus over USB.
2. Open **[`main/chili_stopper_factory.py`](main/chili_stopper_factory.py)**.
3. For live test overlay: Set `CALIBRATE = True` at the top.
4. For factory machine production: Set `CALIBRATE = False`.
5. Click the **Green Play button**.

### Standalone Deployment (Running without PC):
1. In OpenMV IDE: Click **Tools → Save open script to OpenMV Cam (as main.py)**.
2. Safely eject the camera drive.
3. Power the camera directly from 5 V (USB supply or the VIN pin). The camera will automatically boot and run `main.py`.

---

## 🔧 Hardware Requirements
* **OpenMV Cam H7 Plus** (OV5640 sensor, QVGA $320 \times 240$ RGB565)
* **Diffused Lighting**: Uniform illumination along the metal chute.
* **Connections**: Common ground between OpenMV `GND` and PLC/Relay input ground.

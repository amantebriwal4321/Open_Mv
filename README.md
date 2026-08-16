# Open_MV — Chilli Stem Orientation Detection

Machine-vision scripts for an **OpenMV Cam H7 Plus** used on a chilli
de-stemming machine.

Dried chillies travel down a channel and stop against a mechanical stopper.
Every chilli has to reach the cutter facing the **same way**, so the ones that
arrive the wrong way round must be turned 180°. The camera answers a single
question and signals a PLC:

> Did this chilli arrive **stem first**, or **body first**?

| Result | Output pin | LED |
|---|---|---|
| Stem arrived first | **P0** high (3.3 V) | blue, blinking |
| Chilli body arrived first | **P1** high (3.3 V) | green, blinking |
| Rotate 180° command | **P2** high | — |

> **Wiring note:** OpenMV pins source 3.3 V at roughly 25 mA. They are
> *signals*. Drive a relay module, MOSFET or PLC input with them — never a
> solenoid or pneumatic cylinder directly.

## The approach

Two ideas make this work where earlier attempts failed:

**1. Find the chilli by darkness, not by colour.**
A chilli is always much darker than the bright steel channel, whether it is
bright red, maroon or nearly black. The brightness limit is recomputed from
every frame, so it adapts as the lighting changes. Fixed colour ranges kept
breaking when the light made a chilli look brown rather than red.

**2. Tell the ends apart by *relative* redness.**
The code never asks "is this pixel red?". It measures the redness of the
chilli's own pixels at both ends and asks **which end of this chilli is
redder**. The stalk and calyx are always paler than the body, whatever the
absolute values happen to be — so the comparison holds up under poor lighting.

It also refuses to guess. If the chilli has not reached the stopper, or the two
ends genuinely look alike, it reports that instead of inventing an answer.

## Files

Scripts are listed in the order they were developed; the last one is current.

| File | What it does |
|---|---|
| `chili_stem_detect.py` | First approach — segment by redness, decide the stem end from shape cues |
| `main.py` | Factory version using background subtraction against the empty tray |
| `chili_bench_test.py` | Loose desk tester that prints *why* a frame was rejected |
| `chili_leftright_gpio.py` | Adds the GPIO output stage and a one-decision-per-chilli state machine |
| `chili_leftright_v2.py` | Adds smoothing so the decision cannot flicker frame to frame |
| `chili_factory_multi.py` | Tracks each chilli separately; single-subject discipline, shape gates |
| **`chili_stopper_factory.py`** | **Current.** Camera at the stopper: finds the chilli at any angle and compares its two ends |

## Setting it up

All tuning lives in the config block at the top of
`chili_stopper_factory.py` — there is no hidden or compiled logic.

1. Set `CALIBRATE = True` and `DEBUG = True`, then run from the OpenMV IDE.
2. Adjust `CHANNEL_ROI` so the magenta box covers the channel, and set
   `STOPPER_SIDE` so the **cyan box lands on the end touching the stopper**.
   Getting this backwards inverts every answer with no error shown, so check it
   on screen.
3. Tighten `MIN_LEN` / `MAX_LEN` to the pixel length of your real chillies.
4. Two-orientation test: stem first should print a clearly **positive** score,
   body first a clearly **negative** one.
5. Set `STOPPER_GAP_MAX_PX` to about `40` for the machine (a looser value is
   only for bench testing without a real stopper).
6. Set `CALIBRATE = False` and `DEBUG = False`, verify P0/P1 with a multimeter.

## Deploying to run without a PC

In the OpenMV IDE: **Tools → Save open script to OpenMV Cam (as main.py)**,
safely eject the camera drive, then reset. The camera runs the script on power
up with no computer attached. Power it from 5 V (USB supply or the VIN pin).

## Hardware

- OpenMV Cam H7 Plus (OV5640 sensor)
- Even, diffused lighting — glare on the steel channel is the single biggest
  cause of unreliable readings
- Relay module or PLC input on P0 / P1 / P2, with a common ground

## Notes

Company documents, machine CAD, factory photographs and the vendor's compiled
modules are deliberately excluded from this repository — see `.gitignore`.

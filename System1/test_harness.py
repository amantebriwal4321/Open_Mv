"""
test_harness.py — Accuracy testing for the chilli stem detection system.

Runs all three approaches + ensemble on a folder of labelled images
and produces a detailed accuracy report.

Image naming convention:
    chilli_001_LEFT.jpg   → stem is on the left
    chilli_002_RIGHT.jpg  → stem is on the right

Usage:
    python test_harness.py --folder test_images
    python test_harness.py --folder test_images --report report.csv
"""

import os
import sys
import csv
import time
import argparse
import cv2
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from preprocessor import preprocess
from detectors import (
    approach_colour,
    approach_pixel_density,
    approach_skeleton,
    ensemble_vote,
)


def extract_label(filename):
    """Extract ground-truth stem side from filename.

    Expects 'LEFT' or 'RIGHT' (case insensitive)
    somewhere in the filename.

    Args:
        filename: image filename.

    Returns:
        'LEFT', 'RIGHT', or None if not found.
    """
    upper = filename.upper()
    if "LEFT" in upper:
        return "LEFT"
    elif "RIGHT" in upper:
        return "RIGHT"
    return None


def run_test(folder, report_path="test_report.csv"):
    """Run accuracy test on all labelled images in a folder.

    Args:
        folder: path to image directory.
        report_path: where to write the CSV report.
    """
    extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")
    files = sorted([
        f for f in os.listdir(folder)
        if f.lower().endswith(extensions)
    ])

    if not files:
        print(f"[ERROR] No images found in {folder}")
        return

    # Counters
    total = 0
    labelled = 0
    correct = {"ensemble": 0, "approach1": 0, "approach2": 0, "approach3": 0}
    tested  = {"ensemble": 0, "approach1": 0, "approach2": 0, "approach3": 0}
    no_chilli = 0
    times = []

    rows = []

    print(f"[TEST] Processing {len(files)} images from {folder}\n")
    print(f"{'File':<35} {'Label':<7} {'A1':<10} {'A2':<10} {'A3':<10} {'Ens':<10} {'Conf':>6} {'ms':>6}")
    print("-" * 95)

    for fname in files:
        total += 1
        path = os.path.join(folder, fname)
        frame = cv2.imread(path)

        if frame is None:
            print(f"  [SKIP] Cannot read: {fname}")
            continue

        label = extract_label(fname)

        t0 = time.perf_counter()
        data = preprocess(frame)

        if data is None or not data["chilli_present"]:
            no_chilli += 1
            print(f"  {fname:<35} {'N/A':<7} {'---':<10} {'---':<10} {'---':<10} {'NO CHILLI':<10}")
            continue

        processed = data["processed"]
        hsv = data["hsv"]
        red_mask = data["red_mask"]
        gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)

        a1 = approach_colour(hsv, red_mask)
        a2 = approach_pixel_density(red_mask)
        a3 = approach_skeleton(gray)
        ens = ensemble_vote([a1, a2, a3])

        t1 = time.perf_counter()
        ms = (t1 - t0) * 1000
        times.append(ms)

        a1_str = f"{a1['side']:>5} {a1['confidence']:4.0f}%"
        a2_str = f"{a2['side']:>5} {a2['confidence']:4.0f}%"
        a3_str = f"{a3['side']:>5} {a3['confidence']:4.0f}%"
        ens_str = f"{ens['final_side']:>5} {ens['final_confidence']:4.0f}%"

        # Check against label
        if label:
            labelled += 1
            for key, result in [
                ("approach1", a1), ("approach2", a2),
                ("approach3", a3),
            ]:
                tested[key] += 1
                if result["side"] == label:
                    correct[key] += 1

            tested["ensemble"] += 1
            if ens["final_side"] == label:
                correct["ensemble"] += 1

            match = "✓" if ens["final_side"] == label else "✗"
        else:
            match = "?"

        print(f"  {fname:<35} {(label or '?'):<7} {a1_str:<10} {a2_str:<10} {a3_str:<10} {ens_str:<10} {match}")

        rows.append({
            "file": fname,
            "label": label or "",
            "a1_side": a1["side"],
            "a1_conf": a1["confidence"],
            "a2_side": a2["side"],
            "a2_conf": a2["confidence"],
            "a3_side": a3["side"],
            "a3_conf": a3["confidence"],
            "ensemble_side": ens["final_side"],
            "ensemble_conf": ens["final_confidence"],
            "deciding": ens["deciding_approach"],
            "correct": (ens["final_side"] == label) if label else None,
            "processing_ms": ms,
        })

    # ── Summary ──
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total images:      {total}")
    print(f"Labelled images:   {labelled}")
    print(f"No chilli found:   {no_chilli}")

    if labelled > 0:
        print(f"\nAccuracy:")
        for key in ["approach1", "approach2", "approach3", "ensemble"]:
            n = tested[key]
            c = correct[key]
            acc = (c / n * 100) if n > 0 else 0
            name = {"approach1": "Colour", "approach2": "Density",
                    "approach3": "Skeleton", "ensemble": "ENSEMBLE"}[key]
            print(f"  {name:<12}: {c}/{n} = {acc:.1f}%")

    if times:
        print(f"\nProcessing time:")
        print(f"  Average: {np.mean(times):.1f} ms")
        print(f"  Min:     {np.min(times):.1f} ms")
        print(f"  Max:     {np.max(times):.1f} ms")
        print(f"  Median:  {np.median(times):.1f} ms")

    # ── Write CSV report ──
    with open(report_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "file", "label", "a1_side", "a1_conf", "a2_side", "a2_conf",
            "a3_side", "a3_conf", "ensemble_side", "ensemble_conf",
            "deciding", "correct", "processing_ms",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDetailed report saved to: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test chilli detection accuracy")
    parser.add_argument("--folder", required=True, help="Folder with labelled test images")
    parser.add_argument("--report", default="test_report.csv", help="Output CSV path")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"[ERROR] Folder not found: {args.folder}")
        sys.exit(1)

    run_test(args.folder, args.report)

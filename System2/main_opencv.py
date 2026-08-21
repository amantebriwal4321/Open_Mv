"""
main_opencv.py — Chilli Stem Detection System (System 2 - Advanced OpenCV Version)

Main loop with:
  - Live camera feed + trackbar controls
  - Advanced detectors (Color + Centroid Shift + Orientation-Aware Density)
  - Rolling buffer decision smoothing
  - 4-window visualisation (including Centroid Shift vector debug)
  - CSV logging + uncertain image saving
  - Simulated IO signal output
"""

import cv2
import numpy as np
import csv
import os
import time
import argparse
from datetime import datetime
from collections import deque

import config as cfg
from preprocessor import preprocess
from detectors import (
    approach_colour,
    approach_centroid_shift,
    approach_orientation_density,
    ensemble_vote,
)


# ═══════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════

def init_logging():
    """Create the CSV log file and uncertain-image directory."""
    os.makedirs(cfg.UNCERTAIN_IMAGE_DIR, exist_ok=True)
    if not os.path.exists(cfg.LOG_CSV_PATH):
        with open(cfg.LOG_CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "stem_side", "confidence",
                "deciding_approach", "approach1_side", "approach1_conf",
                "approach2_side", "approach2_conf",
                "approach3_side", "approach3_conf",
                "processing_ms", "signal_sent", "image_saved",
            ])


def log_result(data):
    """Append one detection result to the CSV log."""
    with open(cfg.LOG_CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            data.get("timestamp", ""),
            data.get("stem_side", ""),
            f"{data.get('confidence', 0):.1f}",
            data.get("deciding_approach", ""),
            data.get("a1_side", ""),
            f"{data.get('a1_conf', 0):.1f}",
            data.get("a2_side", ""),
            f"{data.get('a2_conf', 0):.1f}",
            data.get("a3_side", ""),
            f"{data.get('a3_conf', 0):.1f}",
            f"{data.get('processing_ms', 0):.1f}",
            data.get("signal_sent", False),
            data.get("image_saved", ""),
        ])


def save_uncertain_image(frame, confidence, stem_side):
    """Save frame when confidence is low for later review."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"uncertain_{ts}_conf{confidence:.0f}_{stem_side}.jpg"
    path = os.path.join(cfg.UNCERTAIN_IMAGE_DIR, fname)
    cv2.imwrite(path, frame)
    return fname


# ═══════════════════════════════════════
# IO SIGNAL (simulated for laptop)
# ═══════════════════════════════════════

def send_io_signal(stem_side, confidence):
    """Simulate 24VDC digital IO signal."""
    conf_category = "GREEN" if confidence >= cfg.CONFIDENCE_GREEN else \
                    "YELLOW" if confidence >= cfg.CONFIDENCE_YELLOW else "RED"

    if stem_side == "LEFT" and confidence >= cfg.ENSEMBLE_MED_CONF:
        print(f"  [IO] Pin0=HIGH  Pin1=LOW   | STEM LEFT  | "
              f"Conf={confidence:.1f}% [{conf_category}]")
        return True
    elif stem_side == "RIGHT" and confidence >= cfg.ENSEMBLE_MED_CONF:
        print(f"  [IO] Pin0=LOW   Pin1=HIGH  | STEM RIGHT | "
              f"Conf={confidence:.1f}% [{conf_category}]")
        return True
    else:
        print(f"  [IO] Pin0=LOW   Pin1=LOW   | UNCERTAIN  | "
              f"Conf={confidence:.1f}% [{conf_category}]")
        return False


# ═══════════════════════════════════════
# TRACKBAR SETUP
# ═══════════════════════════════════════

TRACKBAR_WIN = "Trackbars"


def create_trackbars():
    """Create OpenCV trackbar window with all adjustable parameters."""
    cv2.namedWindow(TRACKBAR_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(TRACKBAR_WIN, 400, 600)

    # Red detection range 1
    cv2.createTrackbar("R1 H Min", TRACKBAR_WIN, cfg.RED_H1_MIN, 180, lambda x: None)
    cv2.createTrackbar("R1 H Max", TRACKBAR_WIN, cfg.RED_H1_MAX, 180, lambda x: None)
    # Red detection range 2
    cv2.createTrackbar("R2 H Min", TRACKBAR_WIN, cfg.RED_H2_MIN, 180, lambda x: None)
    cv2.createTrackbar("R2 H Max", TRACKBAR_WIN, cfg.RED_H2_MAX, 180, lambda x: None)
    cv2.createTrackbar("Red S Min", TRACKBAR_WIN, cfg.RED_S_MIN, 255, lambda x: None)
    cv2.createTrackbar("Red V Min", TRACKBAR_WIN, cfg.RED_V_MIN, 255, lambda x: None)

    # Green stem detection
    cv2.createTrackbar("Grn H Min", TRACKBAR_WIN, cfg.GREEN_H_MIN, 180, lambda x: None)
    cv2.createTrackbar("Grn H Max", TRACKBAR_WIN, cfg.GREEN_H_MAX, 180, lambda x: None)
    cv2.createTrackbar("Grn S Min", TRACKBAR_WIN, cfg.GREEN_S_MIN, 255, lambda x: None)

    # Brown stem detection
    cv2.createTrackbar("Brn H Min", TRACKBAR_WIN, cfg.BROWN_H_MIN, 180, lambda x: None)
    cv2.createTrackbar("Brn H Max", TRACKBAR_WIN, cfg.BROWN_H_MAX, 180, lambda x: None)
    cv2.createTrackbar("Brn S Min", TRACKBAR_WIN, cfg.BROWN_S_MIN, 255, lambda x: None)

    # Processing
    cv2.createTrackbar("Min Area", TRACKBAR_WIN, cfg.MIN_CHILLI_AREA, 20000, lambda x: None)
    cv2.createTrackbar("Conf Thr", TRACKBAR_WIN, cfg.ENSEMBLE_MED_CONF, 100, lambda x: None)
    cv2.createTrackbar("Blur K", TRACKBAR_WIN, cfg.BLUR_KERNEL_SIZE, 15, lambda x: None)
    cv2.createTrackbar("Morph K", TRACKBAR_WIN, cfg.MORPH_KERNEL_SIZE, 15, lambda x: None)


def read_trackbars():
    """Read current trackbar values and update config module in-place."""
    try:
        cfg.RED_H1_MIN = cv2.getTrackbarPos("R1 H Min", TRACKBAR_WIN)
        cfg.RED_H1_MAX = cv2.getTrackbarPos("R1 H Max", TRACKBAR_WIN)
        cfg.RED_H2_MIN = cv2.getTrackbarPos("R2 H Min", TRACKBAR_WIN)
        cfg.RED_H2_MAX = cv2.getTrackbarPos("R2 H Max", TRACKBAR_WIN)
        cfg.RED_S_MIN = cv2.getTrackbarPos("Red S Min", TRACKBAR_WIN)
        cfg.RED_V_MIN = cv2.getTrackbarPos("Red V Min", TRACKBAR_WIN)
        
        cfg.GREEN_H_MIN = cv2.getTrackbarPos("Grn H Min", TRACKBAR_WIN)
        cfg.GREEN_H_MAX = cv2.getTrackbarPos("Grn H Max", TRACKBAR_WIN)
        cfg.GREEN_S_MIN = cv2.getTrackbarPos("Grn S Min", TRACKBAR_WIN)

        cfg.BROWN_H_MIN = cv2.getTrackbarPos("Brn H Min", TRACKBAR_WIN)
        cfg.BROWN_H_MAX = cv2.getTrackbarPos("Brn H Max", TRACKBAR_WIN)
        cfg.BROWN_S_MIN = cv2.getTrackbarPos("Brn S Min", TRACKBAR_WIN)

        cfg.MIN_CHILLI_AREA = cv2.getTrackbarPos("Min Area", TRACKBAR_WIN)
        cfg.ENSEMBLE_MED_CONF = cv2.getTrackbarPos("Conf Thr", TRACKBAR_WIN)

        blur_k = cv2.getTrackbarPos("Blur K", TRACKBAR_WIN)
        cfg.BLUR_KERNEL_SIZE = blur_k if blur_k % 2 == 1 else blur_k + 1

        morph_k = cv2.getTrackbarPos("Morph K", TRACKBAR_WIN)
        cfg.MORPH_KERNEL_SIZE = max(morph_k, 1)
    except cv2.error:
        pass  # trackbar window not yet ready


# ═══════════════════════════════════════
# VISUALISATION
# ═══════════════════════════════════════

def draw_visualisation(frame, results, processing_ms):
    """Draw detection overlays on the main frame."""
    display = frame.copy()
    final = results.get("ensemble", {})
    a1 = results.get("approach1", {})

    side = final.get("final_side", "N/A")
    conf = final.get("final_confidence", 0)
    deciding = final.get("deciding_approach", -1)

    approach_names = {0: "Colour", 1: "Centroid Shift", 2: "Density", -1: "None"}

    # Bounding box from approach 3
    a3 = results.get("approach3", {})
    bbox = a3.get("bbox")
    if bbox:
        x, y, w, h = bbox
        cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 255), 2)

    # Stem marker (red circle from color approach if active)
    stem_pt = a1.get("stem_point")
    if stem_pt:
        cv2.circle(display, stem_pt, 10, (0, 0, 255), -1)
        cv2.putText(display, "STEM", (stem_pt[0] - 20, stem_pt[1] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

    # Colour code for confidence
    if conf >= cfg.CONFIDENCE_GREEN:
        colour = (0, 255, 0)
    elif conf >= cfg.CONFIDENCE_YELLOW:
        colour = (0, 255, 255)
    else:
        colour = (0, 0, 255)

    # Info overlay
    lines = [
        f"Stem: {side}",
        f"Confidence: {conf:.1f}%",
        f"Method: {approach_names.get(deciding, 'N/A')}",
        f"Time: {processing_ms:.1f}ms",
    ]
    y_pos = 30
    for line in lines:
        cv2.putText(display, line, (10, y_pos),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
        y_pos += 30

    # Direction arrow
    h_frame, w_frame = display.shape[:2]
    arrow_y = h_frame // 2
    if side == "LEFT":
        cv2.arrowedLine(display, (w_frame // 2, arrow_y),
                        (50, arrow_y), colour, 3, tipLength=0.3)
    elif side == "RIGHT":
        cv2.arrowedLine(display, (w_frame // 2, arrow_y),
                        (w_frame - 50, arrow_y), colour, 3, tipLength=0.3)

    return display


def build_mask_view(red_mask, stem_mask):
    """Combine red and stem masks into a color visualization."""
    h, w = red_mask.shape[:2]
    vis = np.zeros((h, w, 3), dtype=np.uint8)
    vis[red_mask > 0] = (0, 0, 200)      # red channel for chilli
    vis[stem_mask > 0] = (0, 200, 0)     # green channel for stem
    return vis


def build_centroid_debug_view(processed, a2):
    """Display geometric center vs centroid mass shift vector."""
    vis = processed.copy()
    gx, gy = a2.get("gx", 0), a2.get("gy", 0)
    cx, cy = a2.get("cx", 0), a2.get("cy", 0)

    if gx > 0 and gy > 0:
        # Bounding box geometric center (Blue)
        cv2.circle(vis, (gx, gy), 6, (255, 0, 0), -1)
        cv2.putText(vis, "Geom Ctr", (gx + 10, gy - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)

        # Centroid / Center of Mass (Red)
        cv2.circle(vis, (cx, cy), 6, (0, 0, 255), -1)
        cv2.putText(vis, "Centroid", (cx + 10, cy + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        # Draw connecting displacement vector line
        cv2.line(vis, (gx, gy), (cx, cy), (0, 255, 255), 2)

    return vis


class StatsTracker:
    """Live statistics dashboard for the detection system."""

    def __init__(self, history_size=100):
        self.total = 0
        self.signals_sent = 0
        self.uncertain = 0
        self.approach_usage = {0: 0, 1: 0, 2: 0}
        self.confidences = deque(maxlen=history_size)
        self.times = deque(maxlen=history_size)
        self.last_decisions = deque(maxlen=10)
        self.left_count = 0
        self.right_count = 0

    def update(self, result):
        """Record one detection cycle."""
        self.total += 1
        ensemble = result.get("ensemble", {})
        conf = ensemble.get("final_confidence", 0)
        side = ensemble.get("final_side", "UNCERTAIN")
        deciding = ensemble.get("deciding_approach", -1)
        proc_ms = result.get("processing_ms", 0)

        self.confidences.append(conf)
        self.times.append(proc_ms)
        self.last_decisions.append((side, conf, deciding))

        if side == "LEFT":
            self.left_count += 1
        elif side == "RIGHT":
            self.right_count += 1

        if conf >= cfg.ENSEMBLE_MED_CONF and side != "UNCERTAIN":
            self.signals_sent += 1
        else:
            self.uncertain += 1

        if deciding >= 0:
            self.approach_usage[deciding] = self.approach_usage.get(deciding, 0) + 1

    def draw_dashboard(self, width=400, height=400):
        """Render stats as a BGR image."""
        dash = np.zeros((height, width, 3), dtype=np.uint8)
        dash[:] = (30, 30, 30)  # dark background

        y = 30
        colour = (200, 200, 200)
        font = cv2.FONT_HERSHEY_SIMPLEX

        cv2.putText(dash, "=== SYSTEM 2 DASHBOARD ===", (10, y), font, 0.6, (0, 200, 255), 1)
        y += 35

        cv2.putText(dash, f"Total Processed: {self.total}", (10, y), font, 0.5, colour, 1)
        y += 25
        cv2.putText(dash, f"Signals Sent:    {self.signals_sent}", (10, y), font, 0.5, (0, 255, 0), 1)
        y += 25
        cv2.putText(dash, f"Uncertain:       {self.uncertain}", (10, y), font, 0.5, (0, 0, 255), 1)
        y += 25
        cv2.putText(dash, f"Left: {self.left_count}  |  Right: {self.right_count}", (10, y), font, 0.5, colour, 1)
        y += 35

        # Average confidence and time
        avg_conf = np.mean(self.confidences) if self.confidences else 0
        avg_time = np.mean(self.times) if self.times else 0
        cv2.putText(dash, f"Avg Confidence: {avg_conf:.1f}%", (10, y), font, 0.5, colour, 1)
        y += 25
        cv2.putText(dash, f"Avg Time:       {avg_time:.1f}ms", (10, y), font, 0.5, colour, 1)
        y += 35

        # Approach usage
        cv2.putText(dash, "Approach Usage:", (10, y), font, 0.5, (0, 200, 255), 1)
        y += 25
        names = {0: "Colour", 1: "Centroid Shift", 2: "Density"}
        for i in range(3):
            pct = (self.approach_usage.get(i, 0) / max(self.total, 1)) * 100
            bar_len = int(pct * 1.5)
            cv2.rectangle(dash, (140, y - 12), (140 + bar_len, y + 2), (0, 180, 0), -1)
            cv2.putText(dash, f"  {names[i]}: {pct:.0f}%", (10, y), font, 0.45, colour, 1)
            y += 22

        # Confidence distribution
        y += 15
        cv2.putText(dash, "Confidence Dist:", (10, y), font, 0.5, (0, 200, 255), 1)
        y += 5
        if self.confidences:
            hist_h = 60
            hist_w = width - 40
            bins = [0] * 10
            for c in self.confidences:
                idx = min(int(c / 10), 9)
                bins[idx] += 1
            max_bin = max(bins) if max(bins) > 0 else 1
            bar_w = hist_w // 10
            for i, count in enumerate(bins):
                bar_h = int((count / max_bin) * hist_h)
                x1 = 20 + i * bar_w
                y1 = y + hist_h - bar_h + 10
                y2 = y + hist_h + 10
                c = (0, 255, 0) if i >= 8 else (0, 255, 255) if i >= 6 else (0, 0, 255)
                cv2.rectangle(dash, (x1, y1), (x1 + bar_w - 2, y2), c, -1)
        y += 90

        # Last 10 decisions
        cv2.putText(dash, "Last 10:", (10, y), font, 0.5, (0, 200, 255), 1)
        y += 22
        for side, conf, dec in list(self.last_decisions)[-10:]:
            c = (0, 255, 0) if conf >= cfg.CONFIDENCE_GREEN else \
                (0, 255, 255) if conf >= cfg.CONFIDENCE_YELLOW else (0, 0, 255)
            cv2.putText(dash, f"  {side:>9s}  {conf:5.1f}%", (10, y), font, 0.4, c, 1)
            y += 18

        return dash


# ═══════════════════════════════════════
# MAIN DETECTION PIPELINE
# ═══════════════════════════════════════

def run_detection(frame):
    """Execute the full System 2 detection pipeline on one frame."""
    t_start = time.perf_counter()

    # Preprocess
    data = preprocess(frame)
    if data is None:
        return None

    if not data["chilli_present"]:
        return {"chilli_present": False, "processing_ms": 0}

    processed = data["processed"]
    hsv = data["hsv"]
    red_mask = data["red_mask"]

    results = {"chilli_present": True, "processed": processed}

    # --- Approach 1: Color ---
    a1 = approach_colour(hsv, red_mask)
    results["approach1"] = a1

    # --- Approach 2: Centroid Shift ---
    a2 = approach_centroid_shift(red_mask)
    results["approach2"] = a2

    # --- Approach 3: Orientation Density ---
    a3 = approach_orientation_density(red_mask)
    results["approach3"] = a3

    # --- Ensemble ---
    ensemble = ensemble_vote([a1, a2, a3])
    results["ensemble"] = ensemble

    t_end = time.perf_counter()
    results["processing_ms"] = (t_end - t_start) * 1000.0
    results["red_mask"] = red_mask

    return results


# ═══════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Chilli Stem Detection System 2 (Advanced)"
    )
    parser.add_argument("--image", type=str, help="Path to a single image")
    parser.add_argument("--folder", type=str, help="Path to folder of images")
    parser.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX,
                        help="Camera index (default 0)")
    args = parser.parse_args()

    init_logging()
    stats = StatsTracker()

    # Buffer for decision smoothing
    decision_buffer = deque(maxlen=cfg.ROLLING_WINDOW_SIZE)

    # ── Single image mode ──
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print(f"[ERROR] Cannot read image: {args.image}")
            return
        results = run_detection(frame)
        if results and results.get("chilli_present"):
            ens = results["ensemble"]
            send_io_signal(ens["final_side"], ens["final_confidence"])
            display = draw_visualisation(
                results["processed"], results, results["processing_ms"]
            )
            cv2.imshow("Detection", display)
            cv2.waitKey(0)
        else:
            print("[INFO] No chilli detected in image.")
        cv2.destroyAllWindows()
        return

    # ── Batch folder mode ──
    if args.folder:
        if not os.path.isdir(args.folder):
            print(f"[ERROR] Folder not found: {args.folder}")
            return
        extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff")
        images = sorted([
            f for f in os.listdir(args.folder)
            if f.lower().endswith(extensions)
        ])
        print(f"[INFO] Processing {len(images)} images from {args.folder}")
        for fname in images:
            path = os.path.join(args.folder, fname)
            frame = cv2.imread(path)
            if frame is None:
                continue
            results = run_detection(frame)
            if results and results.get("chilli_present"):
                ens = results["ensemble"]
                print(f"  {fname}: ", end="")
                sent = send_io_signal(ens["final_side"], ens["final_confidence"])
                log_result({
                    "timestamp": datetime.now().isoformat(),
                    "stem_side": ens["final_side"],
                    "confidence": ens["final_confidence"],
                    "deciding_approach": ens["deciding_approach"],
                    "a1_side": results["approach1"]["side"],
                    "a1_conf": results["approach1"]["confidence"],
                    "a2_side": results["approach2"]["side"],
                    "a2_conf": results["approach2"]["confidence"],
                    "a3_side": results["approach3"]["side"],
                    "a3_conf": results["approach3"]["confidence"],
                    "processing_ms": results["processing_ms"],
                    "signal_sent": sent,
                    "image_saved": "",
                })
                stats.update(results)
            else:
                print(f"  {fname}: No chilli detected")
        print(f"\n[SUMMARY] Processed {stats.total} chillies")
        print(f"  Signals sent: {stats.signals_sent}")
        print(f"  Uncertain:    {stats.uncertain}")
        return

    # ── Live camera mode ──
    print(f"[INFO] Opening camera index {args.camera} ...")
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera. Check connection and index.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.FRAME_HEIGHT)

    create_trackbars()
    print("[INFO] System 2 running. Press 'q' to quit, 's' to save frame.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame grab failed. Retrying...")
            continue

        # Update config from trackbars
        read_trackbars()

        # Run detection
        results = run_detection(frame)

        if results is None:
            continue

        if not results.get("chilli_present"):
            cv2.putText(frame, "No Chilli Detected", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imshow("Detection", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            continue

        processed = results["processed"]
        ens = results["ensemble"]
        proc_ms = results["processing_ms"]

        # Decision smoothing buffer
        decision_buffer.append(ens["final_side"])
        left_votes = decision_buffer.count("LEFT")
        right_votes = decision_buffer.count("RIGHT")

        if left_votes > right_votes:
            smoothed_side = "LEFT"
        elif right_votes > left_votes:
            smoothed_side = "RIGHT"
        else:
            smoothed_side = "UNCERTAIN"

        # Overwrite vote outcome for logging/signaling
        ens["final_side"] = smoothed_side

        # IO Signal
        sent = send_io_signal(ens["final_side"], ens["final_confidence"])

        # Save uncertain images
        saved_file = ""
        if ens["final_confidence"] < cfg.CONFIDENCE_YELLOW:
            saved_file = save_uncertain_image(
                processed, ens["final_confidence"], ens["final_side"]
            )

        # Log
        log_result({
            "timestamp": datetime.now().isoformat(),
            "stem_side": ens["final_side"],
            "confidence": ens["final_confidence"],
            "deciding_approach": ens["deciding_approach"],
            "a1_side": results["approach1"]["side"],
            "a1_conf": results["approach1"]["confidence"],
            "a2_side": results["approach2"]["side"],
            "a2_conf": results["approach2"]["confidence"],
            "a3_side": results["approach3"]["side"],
            "a3_conf": results["approach3"]["confidence"],
            "processing_ms": proc_ms,
            "signal_sent": sent,
            "image_saved": saved_file,
        })

        # Update stats
        stats.update(results)

        # ── Window 1: Main detection view ──
        main_view = draw_visualisation(processed, results, proc_ms)
        cv2.imshow("Detection", main_view)

        # ── Window 2: Mask view ──
        stem_mask = results["approach1"].get("stem_mask")
        red_mask = results.get("red_mask")
        if red_mask is not None and stem_mask is not None:
            mask_view = build_mask_view(red_mask, stem_mask)
            cv2.imshow("Masks", mask_view)

        # ── Window 3: Centroid Debug ──
        ctr_view = build_centroid_debug_view(processed, results["approach2"])
        cv2.imshow("Centroid Shift Debug", ctr_view)

        # ── Window 4: Stats dashboard ──
        dash = stats.draw_dashboard()
        cv2.imshow("Stats", dash)

        # Key handling
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(f"manual_save_{ts}.jpg", processed)
            print(f"[INFO] Frame saved: manual_save_{ts}.jpg")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[FINAL SUMMARY - SYSTEM 2]")
    print(f"  Total chillies: {stats.total}")
    print(f"  Signals sent:   {stats.signals_sent}")
    print(f"  Uncertain:      {stats.uncertain}")
    print(f"  Left:           {stats.left_count}")
    print(f"  Right:          {stats.right_count}")


if __name__ == "__main__":
    main()

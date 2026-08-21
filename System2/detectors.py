"""
detectors.py — Three advanced detection approaches + ensemble voting.

Approach 1: Color-based detection (Green + Yellow + Brown)
Approach 2: Mass Centroid Shift (New orientation-invariant geometric approach)
Approach 3: Orientation-aware Pixel Density (Upgraded density check)
Ensemble:   Weighted voting across all three
"""

import cv2
import numpy as np
import config as cfg


# ═══════════════════════════════════════
# APPROACH 1 — Color Detection
# ═══════════════════════════════════════

def approach_colour(hsv, red_mask):
    """Detect stem side by locating green, yellow, or brown stem pixels.

    Args:
        hsv:      HSV image of the cropped chilli region.
        red_mask: Binary mask of red (chilli body) pixels.

    Returns:
        dict with result details.
    """
    h, w = hsv.shape[:2]

    # Find the largest chilli contour to establish the chilli's geometric center
    contours, _ = cv2.findContours(
        red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "stem_point": None,
            "stem_mask": np.zeros_like(red_mask),
        }

    largest = max(contours, key=cv2.contourArea)
    rx, ry, rw, rh = cv2.boundingRect(largest)
    gx = rx + rw / 2.0
    gy = ry + rh / 2.0

    # Green mask
    lower_green = np.array([cfg.GREEN_H_MIN, cfg.GREEN_S_MIN, cfg.GREEN_V_MIN])
    upper_green = np.array([cfg.GREEN_H_MAX, 255, 255])
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    # Yellow / dry-stem mask
    lower_yellow = np.array([cfg.YELLOW_H_MIN, cfg.YELLOW_S_MIN, cfg.YELLOW_V_MIN])
    upper_yellow = np.array([cfg.YELLOW_H_MAX, 255, 255])
    yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # Brown / woody-stem mask
    lower_brown = np.array([cfg.BROWN_H_MIN, cfg.BROWN_S_MIN, cfg.BROWN_V_MIN])
    upper_brown = np.array([cfg.BROWN_H_MAX, 255, 255])
    brown_mask = cv2.inRange(hsv, lower_brown, upper_brown)

    # Combine stem masks
    stem_mask = cv2.bitwise_or(green_mask, yellow_mask)
    stem_mask = cv2.bitwise_or(stem_mask, brown_mask)

    # Morphological cleaning
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (cfg.MORPH_KERNEL_SIZE, cfg.MORPH_KERNEL_SIZE),
    )
    stem_mask = cv2.morphologyEx(stem_mask, cv2.MORPH_OPEN, kernel)
    stem_mask = cv2.morphologyEx(stem_mask, cv2.MORPH_CLOSE, kernel)

    # Constrain stem mask to only pixels immediately adjacent to/overlapping the chilli body
    # to completely ignore bezel/background color noise.
    margin = max(80, int(max(rw, rh) * 0.85))
    stem_search_region = np.zeros_like(red_mask)
    y1 = max(0, int(ry - margin))
    y2 = min(h, int(ry + rh + margin))
    x1 = max(0, int(rx - margin))
    x2 = min(w, int(rx + rw + margin))
    stem_search_region[y1:y2, x1:x2] = 255
    stem_mask = cv2.bitwise_and(stem_mask, stem_search_region)

    # SUBTRACT the red mask from the stem mask so highlights/glare INSIDE the body are ignored
    stem_mask = cv2.bitwise_and(stem_mask, cv2.bitwise_not(red_mask))

    stem_pixels_total = cv2.countNonZero(stem_mask)
    if stem_pixels_total < cfg.MIN_STEM_PIXELS_FOR_COLOR:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "stem_point": None,
            "stem_mask": stem_mask,
        }

    # Find connected components/contours of stem pixels
    stem_contours, _ = cv2.findContours(
        stem_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not stem_contours:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "stem_point": None,
            "stem_mask": stem_mask,
        }

    # Sort stem contours by area (largest first)
    stem_contours = sorted(stem_contours, key=cv2.contourArea, reverse=True)
    
    valid_contour = None
    margin_x = max(15, int(rw * 0.22))
    margin_y = max(15, int(rh * 0.22))
    cx, cy = int(gx), int(gy)
    stem_pixels = 0

    for c in stem_contours:
        moments = cv2.moments(c)
        if moments["m00"] > 0:
            temp_cx = int(moments["m10"] / moments["m00"])
            temp_cy = int(moments["m01"] / moments["m00"])
        else:
            continue

        # Stem must lie at the ends of the chilli body (horizontal: left/right; vertical: top/bottom)
        if rw >= rh:
            if temp_cx < rx + margin_x or temp_cx > rx + rw - margin_x:
                valid_contour = c
                cx, cy = temp_cx, temp_cy
                stem_pixels = int(moments["m00"])
                break
        else:
            if temp_cy < ry + margin_y or temp_cy > ry + rh - margin_y:
                valid_contour = c
                cx, cy = temp_cx, temp_cy
                stem_pixels = int(moments["m00"])
                break

    if valid_contour is None or stem_pixels < cfg.MIN_STEM_PIXELS_FOR_COLOR:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "stem_point": None,
            "stem_mask": stem_mask,
        }

    # Confidence = ratio of stem pixels to total chilli pixels
    chilli_pixels = cv2.countNonZero(red_mask)
    total = stem_pixels + chilli_pixels if chilli_pixels > 0 else 1
    confidence = (stem_pixels / total) * 1000.0  # Scale appropriately
    confidence = min(confidence, 100.0)

    # Determine side relative to the chilli's own center (translation-invariant along the X-axis)
    # Dead zone: if stem is too close to center horizontally, it's pointing straight up/down → UNCERTAIN
    dead_zone = max(5, int(rw * cfg.DEAD_ZONE_RATIO))
    if abs(cx - gx) < dead_zone:
        return {
            "side": "UNCERTAIN",
            "confidence": confidence,
            "stem_point": (cx, cy),
            "stem_mask": stem_mask,
        }
    side = "LEFT" if cx < gx else "RIGHT"

    return {
        "side": side,
        "confidence": confidence,
        "stem_point": (cx, cy),
        "stem_mask": stem_mask,
    }


# ═══════════════════════════════════════
# APPROACH 2 — Mass Centroid Shift
# ═══════════════════════════════════════

def approach_centroid_shift(red_mask):
    """Detect stem side by analyzing the shift of the centroid relative to the geometric center.

    The stem end of a chilli is bulkier and wider, which shifts the center of mass (centroid)
    towards that end compared to the geometric center of the bounding box.

    Args:
        red_mask: Binary mask of red pixels.

    Returns:
        dict with result details.
    """
    contours, _ = cv2.findContours(
        red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "gx": 0, "gy": 0,
            "cx": 0, "cy": 0,
        }

    largest = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)

    # Geometric center of the bounding box
    gx = x + w / 2.0
    gy = y + h / 2.0

    # Center of mass (centroid)
    moments = cv2.moments(largest)
    if moments["m00"] <= 0:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "gx": gx, "gy": gy,
            "cx": gx, "cy": gy,
        }

    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]

    # Determine side relative to the chilli's own center (translation-invariant along the X-axis)
    side = "LEFT" if cx < gx else "RIGHT"
    shift = abs(cx - gx)
    max_possible_shift = w / 2.0 if w > 0 else 1.0

    # Calculate confidence based on shift ratio
    if max_possible_shift > 0:
        # Scale factor (shift is usually small fraction, e.g. 5-20% of length, so amplify it)
        confidence = min((shift / max_possible_shift) * 350.0, 100.0)
    else:
        confidence = 0.0

    return {
        "side": side,
        "confidence": confidence,
        "gx": int(gx), "gy": int(gy),
        "cx": int(cx), "cy": int(cy),
    }


# ═══════════════════════════════════════
# APPROACH 3 — Orientation-Aware Density
# ═══════════════════════════════════════

def approach_orientation_density(red_mask):
    """Detect stem side by comparing pixel density in quarters along the major axis.

    Args:
        red_mask: Binary mask of red pixels.

    Returns:
        dict with result details.
    """
    contours, _ = cv2.findContours(
        red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return {
            "side": "UNCERTAIN", "confidence": 0.0,
            "bbox": None, "orientation": None,
            "left_count": 0, "right_count": 0,
        }

    largest = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)

    # Always split horizontally along the X-axis (left vs right quarters) to detect curvature
    orientation = "HORIZONTAL" if w >= h else "VERTICAL"
    left_region = red_mask[y:y + h, x:x + w // 4]
    right_region = red_mask[y:y + h, x + 3 * w // 4:x + w]

    left_count = cv2.countNonZero(left_region)
    right_count = cv2.countNonZero(right_region)

    total = left_count + right_count
    if total == 0:
        return {
            "side": "UNCERTAIN", "confidence": 0.0,
            "bbox": (x, y, w, h), "orientation": orientation,
            "left_count": 0, "right_count": 0,
        }

    diff = abs(left_count - right_count)
    confidence = (diff / total) * 100.0

    # More pixels = wider = stem side
    side = "LEFT" if left_count > right_count else "RIGHT"

    return {
        "side": side,
        "confidence": confidence,
        "bbox": (x, y, w, h),
        "orientation": orientation,
        "left_count": left_count,
        "right_count": right_count,
    }


# ═══════════════════════════════════════
# ENSEMBLE VOTING
# ═══════════════════════════════════════

def ensemble_vote(results):
    """Weighted voting across all three approaches.
    Prioritizes Color detector (direct stem physical location) if valid.
    """
    c_res = results[0]
    cs_res = results[1]
    d_res = results[2]

    # Rule 1: If the stem color is directly detected, use it as the absolute decision
    if c_res["side"] in ("LEFT", "RIGHT") and c_res["confidence"] > 0:
        return {
            "final_side": c_res["side"],
            "final_confidence": c_res["confidence"],
            "deciding_approach": 0, # Colour
            "votes": [
                (c_res["side"], c_res["confidence"], cfg.WEIGHT_COLOUR),
                (cs_res["side"], cs_res["confidence"], cfg.WEIGHT_CENTROID_SHIFT),
                (d_res["side"], d_res["confidence"], cfg.WEIGHT_DENSITY)
            ]
        }

    # Rule 2: Fallback to geometric shape (Centroid Shift + Density) if color is uncertain
    weights = [cfg.WEIGHT_CENTROID_SHIFT / 0.60, cfg.WEIGHT_DENSITY / 0.60]
    votes = [
        (cs_res["side"], cs_res["confidence"], weights[0]),
        (d_res["side"], d_res["confidence"], weights[1])
    ]

    score_left = 0.0
    score_right = 0.0
    total_weight = 0.0

    for side, conf, w in votes:
        if side == "LEFT":
            score_left += conf * w
        elif side == "RIGHT":
            score_right += conf * w
        total_weight += w

    if total_weight == 0:
        return {
            "final_side": "UNCERTAIN",
            "final_confidence": 0.0,
            "deciding_approach": -1,
            "votes": votes,
        }

    if score_left > score_right:
        final_side = "LEFT"
    elif score_right > score_left:
        final_side = "RIGHT"
    else:
        final_side = "UNCERTAIN"

    overall_conf = sum(c * w for _, c, w in votes) / total_weight
    deciding = 1 if cs_res["confidence"] * weights[0] >= d_res["confidence"] * weights[1] else 2

    return {
        "final_side": final_side,
        "final_confidence": overall_conf,
        "deciding_approach": deciding,
        "votes": votes,
    }


"""
detectors.py — Three detection approaches + ensemble voting.

Approach 1: Colour-based stem detection (primary, fastest)
Approach 2: Pixel density comparison  (secondary)
Approach 3: Skeleton fork analysis    (tertiary, slowest)
Ensemble:   Weighted voting across all three
"""

import cv2
import numpy as np
import config as cfg

try:
    from skimage.morphology import skeletonize
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False
    print("[WARN] scikit-image not installed — Approach 3 (skeleton) disabled.")


# ═══════════════════════════════════════
# APPROACH 1 — Colour Detection
# ═══════════════════════════════════════

def approach_colour(hsv, red_mask):
    """Detect stem side by locating green/yellow stem pixels.

    Steps:
        1. Build green + yellow masks in HSV.
        2. Morphological clean-up.
        3. Find centroid of stem pixels.
        4. Compare centroid X to image centre.

    Args:
        hsv:      HSV image of the cropped chilli region.
        red_mask: Binary mask of red (chilli body) pixels.

    Returns:
        dict with keys:
            'side'       : 'LEFT', 'RIGHT', or 'UNCERTAIN'
            'confidence' : float 0-100
            'stem_point' : (x, y) centroid of stem pixels or None
            'stem_mask'  : combined green+yellow mask
    """
    h, w = hsv.shape[:2]
    centre_x = w // 2

    # Green mask
    lower_green = np.array([cfg.GREEN_H_MIN, cfg.GREEN_S_MIN, cfg.GREEN_V_MIN])
    upper_green = np.array([cfg.GREEN_H_MAX, 255, 255])
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    # Yellow / dry-stem mask
    lower_yellow = np.array([cfg.YELLOW_H_MIN, cfg.YELLOW_S_MIN, cfg.YELLOW_V_MIN])
    upper_yellow = np.array([cfg.YELLOW_H_MAX, 255, 255])
    yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # Combine stem masks
    stem_mask = cv2.bitwise_or(green_mask, yellow_mask)

    # Morphological cleaning
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (cfg.MORPH_KERNEL_SIZE, cfg.MORPH_KERNEL_SIZE),
    )
    stem_mask = cv2.morphologyEx(stem_mask, cv2.MORPH_OPEN, kernel)
    stem_mask = cv2.morphologyEx(stem_mask, cv2.MORPH_CLOSE, kernel)

    stem_pixels = cv2.countNonZero(stem_mask)
    chilli_pixels = cv2.countNonZero(red_mask)

    # No stem pixels found → uncertain
    if stem_pixels < 10:
        return {
            "side": "UNCERTAIN",
            "confidence": 0.0,
            "stem_point": None,
            "stem_mask": stem_mask,
        }

    # Confidence = ratio of stem pixels to total chilli pixels
    total = stem_pixels + chilli_pixels if chilli_pixels > 0 else 1
    confidence = (stem_pixels / total) * 100.0
    # Cap at 100
    confidence = min(confidence, 100.0)

    # Find centroid of stem pixels
    moments = cv2.moments(stem_mask)
    if moments["m00"] > 0:
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
    else:
        cx, cy = centre_x, h // 2

    side = "LEFT" if cx < centre_x else "RIGHT"

    return {
        "side": side,
        "confidence": confidence,
        "stem_point": (cx, cy),
        "stem_mask": stem_mask,
    }


# ═══════════════════════════════════════
# APPROACH 2 — Pixel Density
# ═══════════════════════════════════════

def approach_pixel_density(red_mask):
    """Detect stem side by comparing pixel density in quarters.

    The stem end of a chilli is wider (more pixels)
    than the tapered tip end.

    Steps:
        1. Find bounding box of chilli.
        2. Determine orientation (horizontal vs vertical).
        3. Compare pixel counts in opposing quarters.

    Args:
        red_mask: Binary mask of red pixels.

    Returns:
        dict with keys:
            'side'       : 'LEFT', 'RIGHT', or 'UNCERTAIN'
            'confidence' : float 0-100
            'bbox'       : (x, y, w, h) bounding box
            'orientation': 'HORIZONTAL' or 'VERTICAL'
            'left_count' : pixel count in left/top quarter
            'right_count': pixel count in right/bottom quarter
    """
    # Find bounding box of all red pixels
    contours, _ = cv2.findContours(
        red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return {
            "side": "UNCERTAIN", "confidence": 0.0,
            "bbox": None, "orientation": None,
            "left_count": 0, "right_count": 0,
        }

    # Use the largest contour
    largest = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)

    # Dynamic orientation check
    if w >= h:
        orientation = "HORIZONTAL"
        left_region = red_mask[y:y + h, x:x + w // 4]
        right_region = red_mask[y:y + h, x + 3 * w // 4:x + w]
    else:
        orientation = "VERTICAL"
        left_region = red_mask[y:y + h // 4, x:x + w]          # top quarter
        right_region = red_mask[y + 3 * h // 4:y + h, x:x + w] # bottom quarter

    left_count = cv2.countNonZero(left_region)
    right_count = cv2.countNonZero(right_region)

    total = left_count + right_count
    if total == 0:
        return {
            "side": "UNCERTAIN", "confidence": 0.0,
            "bbox": (x, y, w, h), "orientation": orientation,
            "left_count": 0, "right_count": 0,
        }

    # More pixels = wider = stem side
    diff = abs(left_count - right_count)
    confidence = (diff / total) * 100.0

    if orientation == "HORIZONTAL":
        side = "LEFT" if left_count > right_count else "RIGHT"
    else:
        # For vertical: top = left signal, bottom = right signal
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
# APPROACH 3 — Skeleton Fork Detection
# ═══════════════════════════════════════

def _classify_skeleton_pixels(skeleton):
    """Classify each skeleton pixel by its neighbour count.

    Args:
        skeleton: Binary skeleton image (uint8, 0 or 255).

    Returns:
        endpoints   : list of (x, y) with 1 neighbour
        junctions   : list of (x, y) with 3+ neighbours
    """
    # Normalise to 0/1
    skel_binary = (skeleton > 0).astype(np.uint8)

    # Count neighbours using convolution
    kernel = np.array([[1, 1, 1],
                       [1, 0, 1],
                       [1, 1, 1]], dtype=np.uint8)
    neighbour_count = cv2.filter2D(skel_binary, -1, kernel)

    # Only consider actual skeleton pixels
    endpoints = []
    junctions = []
    ys, xs = np.where(skel_binary == 1)
    for px, py in zip(xs, ys):
        n = neighbour_count[py, px]
        if n == 1:
            endpoints.append((px, py))
        elif n >= 3:
            junctions.append((px, py))

    return endpoints, junctions


def _nearest_junction_distance(point, junctions):
    """Euclidean distance from a point to the nearest junction."""
    if not junctions:
        return float("inf")
    junctions_arr = np.array(junctions)
    dists = np.sqrt(np.sum((junctions_arr - np.array(point)) ** 2, axis=1))
    return float(np.min(dists))


def approach_skeleton(gray):
    """Detect stem side by analysing the skeleton structure.

    Steps:
        1. Blur → adaptive threshold → morphological close.
        2. Skeletonise.
        3. Find endpoints and junctions.
        4. Endpoint closest to a junction = stem end.

    Args:
        gray: Grayscale image of the chilli region.

    Returns:
        dict with keys:
            'side'       : 'LEFT', 'RIGHT', or 'UNCERTAIN'
            'confidence' : float 0-100
            'skeleton'   : skeleton image for visualisation
            'endpoints'  : list of (x, y)
            'junctions'  : list of (x, y)
            'stem_point' : (x, y) of detected stem endpoint
    """
    result_base = {
        "side": "UNCERTAIN", "confidence": 0.0,
        "skeleton": None, "endpoints": [],
        "junctions": [], "stem_point": None,
    }

    if not SKIMAGE_AVAILABLE:
        return result_base

    h, w = gray.shape[:2]
    centre_x = w // 2

    # Gaussian blur to smooth wrinkle noise
    blurred = cv2.GaussianBlur(
        gray, (cfg.BLUR_KERNEL_SIZE, cfg.BLUR_KERNEL_SIZE), 0
    )

    # Adaptive threshold
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        cfg.ADAPTIVE_BLOCK_SIZE,
        cfg.ADAPTIVE_C,
    )

    # Morphological closing to smooth edges
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (cfg.MORPH_KERNEL_SIZE, cfg.MORPH_KERNEL_SIZE),
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Skeletonise (scikit-image expects bool array)
    skel_bool = skeletonize(binary > 0)
    skeleton = (skel_bool.astype(np.uint8)) * 255

    # Classify pixels
    endpoints, junctions = _classify_skeleton_pixels(skeleton)

    if not endpoints:
        result_base["skeleton"] = skeleton
        return result_base

    # For each endpoint, calculate distance to nearest junction
    scored = []
    for ep in endpoints:
        dist = _nearest_junction_distance(ep, junctions)
        scored.append((ep, dist))

    # Filter fake branches: ignore endpoints very close together
    # (branch length < MIN_BRANCH_LENGTH and near a junction)
    valid = [(ep, d) for ep, d in scored if d >= cfg.MIN_BRANCH_LENGTH or d == float("inf")]
    if not valid:
        valid = scored  # fallback to all

    # Stem endpoint = closest to a junction (short distance)
    # Tip endpoint  = farthest from any junction
    valid.sort(key=lambda x: x[1])
    stem_ep = valid[0][0]

    # Confidence based on separation between stem and tip distances
    if len(valid) >= 2:
        tip_ep = valid[-1][0]
        max_dist = valid[-1][1]
        min_dist = valid[0][1]
        if max_dist > 0 and max_dist != float("inf"):
            confidence = ((max_dist - min_dist) / max_dist) * 100.0
        else:
            confidence = 50.0
    else:
        confidence = 40.0

    side = "LEFT" if stem_ep[0] < centre_x else "RIGHT"

    return {
        "side": side,
        "confidence": min(confidence, 100.0),
        "skeleton": skeleton,
        "endpoints": endpoints,
        "junctions": junctions,
        "stem_point": stem_ep,
    }


# ═══════════════════════════════════════
# ENSEMBLE VOTING
# ═══════════════════════════════════════

def ensemble_vote(results):
    """Weighted voting across all three approaches.

    Args:
        results: list of dicts from each approach, each having
                 'side' and 'confidence'.

    Returns:
        dict with keys:
            'final_side'       : 'LEFT', 'RIGHT', or 'UNCERTAIN'
            'final_confidence' : float 0-100
            'deciding_approach': int (0, 1, or 2) or -1
            'votes'            : list of (side, confidence, weight)
    """
    weights = [cfg.WEIGHT_COLOUR, cfg.WEIGHT_DENSITY, cfg.WEIGHT_SKELETON]
    votes = []
    for i, r in enumerate(results):
        votes.append((r["side"], r["confidence"], weights[i]))

    # Weighted score for each side
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

    # Weighted average confidence
    weighted_conf = (score_left + score_right) / total_weight if total_weight else 0

    if score_left > score_right:
        final_side = "LEFT"
        margin = score_left - score_right
    elif score_right > score_left:
        final_side = "RIGHT"
        margin = score_right - score_left
    else:
        final_side = "UNCERTAIN"
        margin = 0

    # Overall confidence = weighted average of all confidences
    overall_conf = sum(c * w for _, c, w in votes) / total_weight

    # Determine which approach contributed most to the winning side
    deciding = -1
    best_contrib = -1
    for i, (side, conf, w) in enumerate(votes):
        if side == final_side:
            contrib = conf * w
            if contrib > best_contrib:
                best_contrib = contrib
                deciding = i

    return {
        "final_side": final_side,
        "final_confidence": overall_conf,
        "deciding_approach": deciding,
        "votes": votes,
    }

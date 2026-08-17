"""
preprocessor.py — Preprocessing pipeline for System 2.

Runs BEFORE any detection approach:
  1. Noise reduction
  2. CLAHE contrast enhancement
  3. Reflection masking
  4. ROI cropping
  5. Frame validation (is a chilli present?)
"""

import cv2
import numpy as np
import config as cfg


def reduce_noise(frame):
    """Remove camera sensor noise using non-local means denoising."""
    return cv2.fastNlMeansDenoisingColored(
        frame,
        None,
        cfg.DENOISE_H,
        cfg.DENOISE_H_COLOR,
        cfg.DENOISE_TEMPLATE_WINDOW,
        cfg.DENOISE_SEARCH_WINDOW,
    )


def enhance_contrast(frame):
    """Apply CLAHE to the L channel of LAB colour space."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=cfg.CLAHE_CLIP_LIMIT,
        tileGridSize=cfg.CLAHE_TILE_SIZE,
    )
    l_channel = clahe.apply(l_channel)
    lab = cv2.merge([l_channel, a_channel, b_channel])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def mask_reflections(frame):
    """Detect and mask bright metallic reflections."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, reflection_mask = cv2.threshold(
        gray, cfg.REFLECTION_THRESHOLD, 255, cv2.THRESH_BINARY
    )
    # In-paint over reflections with surrounding texture
    result = cv2.inpaint(frame, reflection_mask, inpaintRadius=3,
                         flags=cv2.INPAINT_TELEA)
    return result, reflection_mask


def crop_roi(frame):
    """Crop frame to the V-channel region of interest."""
    h, w = frame.shape[:2]
    x1 = int(w * cfg.ROI_X_START)
    x2 = int(w * cfg.ROI_X_END)
    y1 = int(h * cfg.ROI_Y_START)
    y2 = int(h * cfg.ROI_Y_END)
    return frame[y1:y2, x1:x2].copy(), (x1, y1)


def detect_chilli_present(hsv, min_area=None):
    """Check whether enough red pixels exist to indicate a chilli."""
    if min_area is None:
        min_area = cfg.MIN_CHILLI_AREA

    # Dual-range red detection
    lower_red1 = np.array([cfg.RED_H1_MIN, cfg.RED_S_MIN, cfg.RED_V_MIN])
    upper_red1 = np.array([cfg.RED_H1_MAX, 255, 255])
    lower_red2 = np.array([cfg.RED_H2_MIN, cfg.RED_S_MIN, cfg.RED_V_MIN])
    upper_red2 = np.array([cfg.RED_H2_MAX, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    red_mask = cv2.bitwise_or(mask1, mask2)

    # Morphological cleaning
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (cfg.MORPH_KERNEL_SIZE, cfg.MORPH_KERNEL_SIZE),
    )
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)

    pixel_count = cv2.countNonZero(red_mask)
    return pixel_count >= min_area, red_mask


def preprocess(frame):
    """Full preprocessing pipeline."""
    if frame is None or frame.size == 0:
        return None

    # 1. ROI crop first (reduces work for later steps)
    cropped, roi_offset = crop_roi(frame)

    # 2. Noise reduction
    denoised = reduce_noise(cropped)

    # 3. Contrast enhancement
    enhanced = enhance_contrast(denoised)

    # 4. Reflection handling
    clean, refl_mask = mask_reflections(enhanced)

    # 5. Convert to HSV for detection
    hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)

    # 6. Frame validation
    present, red_mask = detect_chilli_present(hsv)

    return {
        "processed": clean,
        "hsv": hsv,
        "red_mask": red_mask,
        "chilli_present": present,
        "roi_offset": roi_offset,
        "reflection_mask": refl_mask,
    }

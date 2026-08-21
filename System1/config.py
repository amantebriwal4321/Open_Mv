"""
config.py — Named constants and tunable parameters
for the Chilli Stem Detection System.

No magic numbers anywhere in the codebase;
every threshold lives here and can be adjusted
via trackbars at runtime.
"""

# ─────────────────────────────────────
# CAMERA
# ─────────────────────────────────────
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# ─────────────────────────────────────
# HSV RANGES — RED CHILLI (dual range)
# ─────────────────────────────────────
RED_H1_MIN = 0
RED_H1_MAX = 10
RED_H2_MIN = 160
RED_H2_MAX = 180
RED_S_MIN = 70
RED_V_MIN = 50

# ─────────────────────────────────────
# HSV RANGES — GREEN STEM
# ─────────────────────────────────────
GREEN_H_MIN = 35
GREEN_H_MAX = 85
GREEN_S_MIN = 40
GREEN_V_MIN = 40

# ─────────────────────────────────────
# HSV RANGES — YELLOW / DRY STEM
# ─────────────────────────────────────
YELLOW_H_MIN = 25
YELLOW_H_MAX = 35
YELLOW_S_MIN = 40
YELLOW_V_MIN = 40

# ─────────────────────────────────────
# PREPROCESSING
# ─────────────────────────────────────
DENOISE_H = 10                # denoising filter strength
DENOISE_H_COLOR = 10
DENOISE_TEMPLATE_WINDOW = 7
DENOISE_SEARCH_WINDOW = 21

CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_SIZE = (8, 8)

REFLECTION_THRESHOLD = 240    # pixel value above = glare
BLUR_KERNEL_SIZE = 5
MORPH_KERNEL_SIZE = 5

# ─────────────────────────────────────
# DETECTION THRESHOLDS
# ─────────────────────────────────────
MIN_CHILLI_AREA = 3000        # minimum red-pixel area to count as a chilli
COLOUR_CONFIDENCE_THRESHOLD = 75   # Approach 1
DENSITY_CONFIDENCE_THRESHOLD = 70  # Approach 2

# ─────────────────────────────────────
# SKELETON PARAMETERS
# ─────────────────────────────────────
ADAPTIVE_BLOCK_SIZE = 11
ADAPTIVE_C = 2
MIN_BRANCH_LENGTH = 10        # branches shorter than this = noise

# ─────────────────────────────────────
# ENSEMBLE WEIGHTS
# ─────────────────────────────────────
WEIGHT_COLOUR = 0.40
WEIGHT_DENSITY = 0.35
WEIGHT_SKELETON = 0.25

ENSEMBLE_HIGH_CONF = 80       # act confidently
ENSEMBLE_MED_CONF = 60        # act but log
# below 60 → skip and save image

# ─────────────────────────────────────
# IO SIGNAL
# ─────────────────────────────────────
SIGNAL_DURATION_MS = 500      # pulse length for OpenMV

# ─────────────────────────────────────
# LOGGING
# ─────────────────────────────────────
LOG_CSV_PATH = "detection_log.csv"
UNCERTAIN_IMAGE_DIR = "uncertain_images"
CONFIDENCE_GREEN = 85
CONFIDENCE_YELLOW = 65
# below 65 = red

# ─────────────────────────────────────
# ROI (Region Of Interest) — fraction of frame
# Adjust these to crop to your V-channel
# ─────────────────────────────────────
ROI_X_START = 0.1   # 10% from left
ROI_X_END = 0.9     # 90% from left
ROI_Y_START = 0.1
ROI_Y_END = 0.9

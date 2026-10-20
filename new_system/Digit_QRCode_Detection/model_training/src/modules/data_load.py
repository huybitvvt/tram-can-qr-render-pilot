# ==========================================================================
# PURPOSE: LOAD DATASET
# ==========================================================================
# IMPORTS & MODULE LOADING
# ==========================================================================
import os

# ==========================================================================
# PARAMETERS
# ==========================================================================
ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

TRAIN_PATH = os.path.join(ROOT_PATH, "ssd/train/")
TEST_PATH = os.path.join(ROOT_PATH, "ssd/test/")
VAL_PATH = os.path.join(ROOT_PATH, "ssd/val/")

# ==========================================================================
# MAIN EXECUTION ENTRYPOINT
# ==========================================================================
print(os.path.exists(TRAIN_PATH))

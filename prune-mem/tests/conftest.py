import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_TMP = ROOT / ".tmp" / "pytest-temp"

TEST_TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEST_TMP)
os.environ["TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
os.environ["TMPDIR"] = str(TEST_TMP)

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

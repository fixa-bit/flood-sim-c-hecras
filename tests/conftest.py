"""Keep this project's temporary test files on the project drive."""
import os
from pathlib import Path
import tempfile

TEST_TEMP = Path(__file__).resolve().parents[1] / "workspace" / "temp" / "python-tests"
TEST_TEMP.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(TEST_TEMP)
os.environ["TMP"] = str(TEST_TEMP)
tempfile.tempdir = str(TEST_TEMP)

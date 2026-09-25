import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RADAR_DATA_DIR", tempfile.mkdtemp(prefix="radar-test-"))
os.environ["RADAR_RUNNER"] = "local"
for key in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REPO", "SMTP_USER", "SMTP_PASSWORD"):
    os.environ.pop(key, None)

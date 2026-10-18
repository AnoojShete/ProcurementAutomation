"""PaddleOCR must import cleanly in its own process, as _paddle_worker.py
does. With mismatched zlib copies loaded (torchvision/paddle bundle their
own) the import dies in chardet with "inconsistent stream state", and
every image upload silently extracts zero words. The Dockerfile's
LD_PRELOAD=libz.so.1 prevents that; run via scripts/test-service.sh so the
test sees the image's environment."""
import importlib.util
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(importlib.util.find_spec("paddleocr") is None, reason="paddleocr not installed")
def test_paddleocr_imports_in_subprocess():
    proc = subprocess.run(
        [sys.executable, "-c", "from paddleocr import PaddleOCR"],
        capture_output=True, text=True, timeout=120, env=os.environ.copy(),
    )
    assert proc.returncode == 0, proc.stderr[-1500:]

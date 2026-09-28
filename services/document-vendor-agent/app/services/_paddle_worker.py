"""PaddleOCR subprocess worker — isolated from the main process.

PaddleOCR's C-level inference backend (paddle_infer::Predictor, oneDNN)
can SIGABRT/SIGSEGV the process on certain platform/version combinations —
none of these are catchable from Python since they're OS-level signals,
not Python exceptions. Running PaddleOCR in a subprocess means a crash
kills the child process, not the API/worker process.

Protocol:
  stdin:  raw image bytes (the entire file content)
  stdout: extracted text (UTF-8), one line per OCR result line
  stderr: error messages (logged by parent on non-zero exit)
  exit 0: success (stdout contains text)
  exit 1: PaddleOCR not available / import failed
  exit 2: OCR processing error

Called only for image files (PNG/JPEG/TIFF). PDFs go through Docling
in the main process.
"""
import io
import sys


def _run():
    """Read image bytes from stdin, OCR with PaddleOCR, print text to stdout."""
    image_bytes = sys.stdin.buffer.read()
    if not image_bytes:
        sys.exit(2)

    try:
        from paddleocr import PaddleOCR  # noqa
    except ImportError:
        # PaddleOCR not installed
        sys.exit(1)

    try:
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)

        # use_angle_cls=True handles rotated text; lang='en' for IT invoices.
        # show_log=False keeps stdout clean (only extracted text goes there).
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = ocr.ocr(img_array, cls=True)

        lines = []
        if result:
            for block in result:
                if block:
                    for line in block:
                        if line and len(line) >= 2:
                            text_info = line[1]
                            if text_info and len(text_info) >= 1:
                                text = text_info[0]
                                if text:
                                    lines.append(text)

        print("\n".join(lines), end="")
        sys.exit(0)

    except Exception as e:
        print(f"PaddleOCR error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _run()

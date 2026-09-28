"""Text extraction in its own process (see ocr.extract_text_isolated).

Parsing untrusted PDFs is the one step whose cost the uploader controls: a
file can be crafted (or simply be unusual) so that pdfminer/Docling spend
minutes on it. Python can't stop a running thread, so the extraction runs
here, in a child process the worker can kill when the time limit is up.

Protocol:
  argv:   filename content_type
  stdin:  the file's bytes
  stdout: one JSON object {text, method, file_type, text_quality, words_with_boxes}
  exit 0 on success, 1 on an extraction error (message on stderr)
"""
import json
import sys


def main() -> None:
    filename, content_type = sys.argv[1], sys.argv[2]
    data = sys.stdin.buffer.read()
    from app.services.ocr import extract_text
    result = extract_text(data, filename, content_type)
    json.dump({
        "text": result.text,
        "method": result.method,
        "file_type": result.file_type,
        "text_quality": result.text_quality,
        "words_with_boxes": result.words_with_boxes or [],
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # reported to the parent, which fails the document cleanly
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

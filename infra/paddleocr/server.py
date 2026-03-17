"""Lightweight HTTP server wrapping PaddleOCR for PDF → Mathpix markdown.

Accepts PDF files via POST, returns Mathpix-style markdown with
$...$ and $$...$$ math delimiters.
"""

import io
import os
import re
import tempfile

from flask import Flask, jsonify, request

app = Flask(__name__)

# Lazy-load OCR engine on first request
_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        import os
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    return _ocr


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/convert", methods=["POST"])
def convert():
    """Convert a PDF to Mathpix-style markdown.

    Accepts: multipart/form-data with a 'file' field containing the PDF.
    Returns: JSON with 'markdown' field.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    pdf_file = request.files["file"]

    # Save to temp file (PaddleOCR needs a file path)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        import traceback
        import fitz  # PyMuPDF — comes with paddleocr deps

        ocr = get_ocr()
        print(f"Processing PDF: {pdf_file.filename}", flush=True)

        # Process page by page to avoid OOM on large PDFs
        doc = fitz.open(tmp_path)
        all_pages_text = []

        for page_idx in range(len(doc)):
            print(f"  Page {page_idx + 1}/{len(doc)}...", flush=True)
            # Render page to image
            pix = doc[page_idx].get_pixmap(dpi=200)
            img_path = tmp_path + f"_page{page_idx}.png"
            pix.save(img_path)

            # OCR the single page image
            page_result = ocr.predict(img_path)
            page_text = _predict_to_markdown(page_result)
            all_pages_text.append(page_text)

            # Clean up page image
            os.unlink(img_path)

        doc.close()
        result_text = "\n\n---\n\n".join(all_pages_text)
        result_text = _detect_and_wrap_math(result_text)
        print(f"OCR complete: {len(result_text)} chars", flush=True)

        return jsonify({"markdown": result_text})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)


def _predict_to_markdown(result) -> str:
    """Convert PaddleOCR predict result to Mathpix-style markdown.

    The predict API returns an iterator of page results.
    Each page result has rec_texts, rec_scores, etc.
    """
    pages = []

    try:
        for page_idx, page_result in enumerate(result):
            lines = []

            # Try different result formats
            if hasattr(page_result, 'rec_texts'):
                lines = list(page_result.rec_texts)
            elif isinstance(page_result, dict) and 'rec_texts' in page_result:
                lines = page_result['rec_texts']
            elif isinstance(page_result, (list, tuple)):
                for item in page_result:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                        lines.append(text)
                    elif isinstance(item, str):
                        lines.append(item)

            page_text = "\n".join(str(l) for l in lines)
            page_text = _detect_and_wrap_math(page_text)

            if page_idx > 0:
                pages.append("\n---\n")
            pages.append(page_text)
    except Exception as e:
        # Fallback: try to stringify the result
        return str(result)

    return "\n\n".join(pages)


def _ocr_to_markdown(result: list) -> str:
    """Legacy: Convert PaddleOCR ocr() result format."""
    pages = []

    for page_idx, page in enumerate(result):
        if not page:
            continue

        lines = []
        for item in page:
            if not item or len(item) < 2:
                continue
            text = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
            lines.append(text)

        page_text = "\n".join(lines)
        page_text = _detect_and_wrap_math(page_text)

        if page_idx > 0:
            pages.append("\n---\n")
        pages.append(page_text)

    return "\n\n".join(pages)


def _detect_and_wrap_math(text: str) -> str:
    """Detect mathematical expressions and wrap in $ delimiters.

    Heuristic-based: looks for lines with high density of math symbols
    that aren't already wrapped.
    """
    math_chars = set("∀∃∈∉⊂⊃∪∩∧∨¬→←↔⇒⇐⇔∑∏∫≤≥≠≈∞∂∇λμσΩαβγδεζηθκπρτφψω")
    lines = text.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue

        # Count math-like characters
        math_count = sum(1 for c in stripped if c in math_chars or c in "{}^_\\")
        ratio = math_count / max(len(stripped), 1)

        # If line looks like a math expression and isn't already wrapped
        if ratio > 0.15 and not stripped.startswith("$"):
            result.append(f"$${stripped}$$")
        else:
            result.append(line)

    return "\n".join(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

"""PDF converter — uses PaddleOCR service for PDF → Mathpix markdown.

Sends PDFs to the PaddleOCR Docker sidecar which runs PaddleOCR on
Python 3.13 (PaddleOCR lacks 3.14 wheels). Returns Mathpix-style
markdown with $...$ and $$...$$ math delimiters for equations.
"""

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PADDLEOCR_URL = os.getenv("PADDLEOCR_URL", "http://localhost:8080")


def convert_pdf(file_path: Path) -> str:
    """Convert a PDF file to Mathpix markdown via the PaddleOCR service.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Mathpix-style markdown with math delimiters.
    """
    try:
        with open(file_path, "rb") as f:
            response = httpx.post(
                f"{PADDLEOCR_URL}/convert",
                files={"file": (file_path.name, f, "application/pdf")},
                timeout=300.0,  # PDFs can take a while
            )
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            logger.warning("PaddleOCR error for %s: %s", file_path.name, data["error"])
            return ""

        return data.get("markdown", "")

    except httpx.ConnectError:
        logger.error(
            "Cannot connect to PaddleOCR service at %s. "
            "Start it with: vibe-node infra up (or docker compose up paddleocr -d)",
            PADDLEOCR_URL,
        )
        return ""
    except Exception as e:
        logger.warning("PDF conversion failed for %s: %s", file_path.name, e)
        return ""

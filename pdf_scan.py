"""Safely rasterize uploaded multi-page PDF scans one page at a time.

The image returned for each page is an OpenCV BGR ndarray, which can be
passed directly to scan_utils.split_sheet(). Works with PDF scans containing
images as well as PDF printouts made by the website.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
import pypdfium2 as pdfium

from scan_utils import ScanError

# 180 DPI renders an A4 page at ~1488 x 2105 pixels, enough to distinguish
# the small black corner marks without allocating enormous image buffers.
PDF_RENDER_DPI = 180
PDF_MAX_RENDER_PIXELS = 22_000_000
PDF_MAX_RENDER_DIMENSION = 6000


def count_pdf_pages(path) -> int:
    """Validate that the PDF is readable and return its page count."""
    try:
        with pdfium.PdfDocument(str(path)) as document:
            count = len(document)
            if count == 0:
                raise ScanError("The PDF has no pages.")
            return count
    except ScanError:
        raise
    except Exception as exc:
        raise ScanError(
            "Could not open this PDF. Make sure it isn't password-protected or damaged."
        ) from exc


def iter_pdf_pages(path):
    """Yield each PDF page as BGR ndarray; keep only one page rendered at a time."""
    try:
        with pdfium.PdfDocument(str(path)) as document:
            for page_index in range(len(document)):
                page = document[page_index]
                try:
                    width_pt, height_pt = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width_pt, height_pt)):
                        raise ScanError("PDF page has invalid dimensions.")
                    scale = min(
                        PDF_RENDER_DPI / 72.0,
                        PDF_MAX_RENDER_DIMENSION / max(width_pt, height_pt),
                        math.sqrt(PDF_MAX_RENDER_PIXELS / (width_pt * height_pt)),
                    )
                    if min(width_pt, height_pt) * scale < 500:
                        raise ScanError("PDF page is too small to read its corner marks.")
                    bitmap = page.render(scale=scale)
                    try:
                        # Color order must match OpenCV's BGR expectations.
                        rgb_image = np.asarray(bitmap.to_pil().convert("RGB"))
                        bgr_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
                    finally:
                        bitmap.close()
                except ScanError:
                    raise
                except Exception as exc:
                    raise ScanError(f"Could not render PDF page {page_index + 1}.") from exc
                finally:
                    page.close()
                yield bgr_image
    except ScanError:
        raise
    except Exception as exc:
        raise ScanError("Could not read the PDF pages.") from exc

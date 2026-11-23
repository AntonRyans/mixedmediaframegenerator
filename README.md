# Frame Extractor — flexible Scan (including multi-page PDFs)

This is a complete project update based on the previous **1 GB video upload + PDF Scan** version. The three tabs remain: **Extract**, **Print**, and **Scan**.

## What's fixed

The old Scan tool rejected a page when it could not find four corner squares. In **Auto** mode (the default), it now tries, in order:

1. **Four square markers** — precise perspective correction.
2. **Page outline** — locate the outer paper quadrilateral and correct perspective, even when printed corner squares are missing or covered.
3. **Three markers** — estimate alignment with an affine transform when the page edge is not clearly visible (less precise).
4. **Full page** — when all detections fail, treat the full image as the printed sheet rather than fail. For a PDF, this maps the full PDF page.

A ZIP containing up to nine recovered frames per sheet is downloaded, plus **`scan_report.txt`**, which describes how each page was aligned. When fallback was used, the Scan tab displays the number of affected pages. **Full-image fallback can mis-crop images that include a lot of background or are significantly perspective-skewed: check results.** It cannot recover portions that were physically cut off from the photo.

## New alignment options in Scan

- **Auto (recommended, flexible):** all the fallbacks above.
- **Paper edges / whole page:** ignore black markers. Good for scans with covered or missing squares.
- **Full image only:** for already tightly cropped scans. Avoid when there is a wide border/background around the sheet.
- **Four markers only:** strict, original precise mode; rejects pages without all four markers.

Supports **PNG, JPG, WebP, PDF (multi-page)**. Keep one 3×3 sheet per PDF page. A4 and US Letter paper options and auto/portrait/landscape settings are preserved. Other pages in the PDF remain in page order.

## Which files to update

| File | Where | Action |
| --- | --- | --- |
| `scan_utils.py` | Flask backend (Render) | **Replace** — robust fallback geometry |
| `app.py` | Flask backend (Render) | **Replace** — alignment selection, report and fallback headers |
| `scan.js` | Website frontend (GitHub Pages) | **Replace** — display fallback warnings |
| `index.html` | Website frontend (GitHub Pages) | **Replace** — alignment selector and help text |
| `pdf_scan.py` | Flask backend | Keep existing (included) — PDF rasterization |
| `requirements.txt` | Flask backend | Keep existing (included) |
| `print.js`, `style.css`, `app.js`, `zip.js` | Website frontend | Keep existing (included) |
| `config.js` | Website frontend | **Keep your LIVE deployed backend URL** (example in ZIP points to localhost) |

If your GitHub Pages site and Render backend use one GitHub repository, replace all modified files at the repository root (if that is where your existing files are). Then commit and push. No new Python packages are required beyond those of the PDF version.

## Render deployment

The backend service must have `app.py`, `scan_utils.py`, `pdf_scan.py`, and `requirements.txt` in the same folder, and start with `gunicorn app:app --workers 1 --threads 2 --timeout 1200 --bind 0.0.0.0:$PORT` (or your existing working start command). Set `MAX_UPLOAD_MB=1024` for the previous 1 GiB video upload cap.

For testing locally:

```bash
pip install -r requirements.txt
python app.py
```

**Note:** The 1 GiB limit is Flask-side and does not guarantee successful 1 GiB uploads on a resource-constrained Render service. PDFs and images are also subject to the existing Scan page-count / per-image limits and the total request limit.

## What to do if a frame is misaligned

Start with **Auto**. If a page was poorly detected, retry in **Paper edges / whole page**, or **Full image only** when your scan is already cropped to the paper margins. Choose the correct A4/Letter size. For a skewed photo, take a photo with all four paper edges clearly visible, ideally against a contrasting table.

No test of your particular `mixed_media_test_017.png` was possible because that image was not supplied in this turn. Tests were performed on representative marked sheets with missing squares, perspective-distorted images, and two PDF pages.

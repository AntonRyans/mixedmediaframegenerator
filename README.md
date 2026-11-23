# Frame Extractor — Scan Tab Edition

Video → Extract frames → Print 3x3 sheets → Draw on paper → Scan/photo → ZIP of recovered frames.

## Replace / add these files

**Backend (Render)**
- Replace your existing `app(1).py` with `app.py` (rename to `app.py` in the repo).
- **Add** `scan_utils.py` next to `app.py`.
- Update `requirements.txt` (OpenCV and NumPy are required).

**Frontend (GitHub Pages)**
- Replace `index.html`, `print.js`, and `style.css`.
- **Add** `scan.js` next to `app.js`, `print.js`, `style.css`, and `index.html`.
- Keep `app.js` and `zip.js`; they work unchanged.
- In `config.js`, set `API_URL` to the deployed Render backend URL (no trailing slash). For local testing, use `http://127.0.0.1:5000`.

## Local setup

```sh
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser. This backend now also serves the frontend for local tests; GitHub Pages is still supported for the frontend.

## Using Scan

1. Extract frames from a video, then open **Print**.
2. Load those frames, select **A4** or **US Letter**, and choose an orientation.
3. Print new sheets at **100% scale**, **no margins**, with **background graphics enabled**. Each printed page has 4 black registration squares.
4. Draw on the sheets, keeping their registration squares visible.
5. Photograph/scan every page, upright, with all four squares visible and without cropping the sheet edges. Use JPG/PNG/WebP (not PDF). Name the scans in page order, e.g. `sheet_01.jpg`, `sheet_02.jpg`.
6. In **Scan**, select the matching paper size, select all scanned sheets, and specify the number of actual frames on the **last** page (default 9). Use **Auto** orientation for normally upright scanned sheets.
7. Click **Recover frames from sheets**. The website downloads a `scanned_frames.zip` containing `frame_00001.png`, etc. A shortcut can send those images back to **Print**.

## How registration works

- `print.js` adds four corner marks to every sheet.
- `style.css` places the corner marks and each frame in fixed millimetre positions.
- `scan_utils.py` uses OpenCV to identify the squares, correct perspective and crop the nine frame regions, omitting frame outlines and caption areas.
- `app.py` accepts `POST /scan` with `multipart/form-data` fields `images` (multiple), `paper`, `orientation`, `last_page_frames`, and `format`.

The layout constants in `scan_utils.py` must stay synchronized with `style.css`. In particular, changes to paper padding, grid gap, marker positions, label height, or frame padding require updates to the scanner coordinates.

**Limitations:** This is for *new printed sheets with four markers*. Older printouts without markers, heavily cropped images, unreadable photos, and PDF uploads are unsupported. The system does not preserve metadata for the source video or frame filenames; output frames are sequentially renumbered in order of the uploaded scanned-page filenames. Frames may include white letterboxing if the source video aspect ratio differs from the printed frame box. Pages that have been photographed sideways should be rotated upright before uploading.

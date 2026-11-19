# Frame Extractor

A small web app: upload a video clip, get its frames back as images in a zip.

- **Backend:** Python, Flask, OpenCV
- **Frontend:** plain HTML, CSS and a little JavaScript (upload progress, download)

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Deploy to Render (free)

GitHub Pages can't run Python, so the whole app (backend and pages) is served from Render.

1. Push this folder to a GitHub repo.
2. In Render, choose **New > Blueprint**, connect the repo, and apply. Render reads `render.yaml`.
   (Or **New > Web Service** and set: build `pip install -r requirements.txt`,
   start `gunicorn app:app --workers 1 --threads 2 --timeout 300 --bind 0.0.0.0:$PORT`.)
3. When the deploy finishes you get a `https://frame-extractor-xxxx.onrender.com` URL.

Free-tier things to know:

- The service **sleeps after ~15 minutes idle**; the next visit takes up to a minute to wake it.
- It has 512 MB RAM and a small share of CPU, so long or high-resolution clips are slow.
  Defaults are 100 MB upload / 1000 frames. Change them in the Render dashboard under
  Environment (`MAX_UPLOAD_MB`, `MAX_FRAMES`) without touching code.
- Disk is temporary, which is fine: uploads and zips are deleted as soon as the download ends.

## Options

- **Every Nth frame** (1 = every single frame) or **frames per second** of video
- **PNG** (lossless) or **JPG** (smaller)

## Settings

| Setting | Default | Where |
|---|---|---|
| `MAX_UPLOAD_MB` | 100 | environment variable |
| `MAX_FRAMES` | 1000 images per clip | environment variable |
| `ALLOWED_EXTENSIONS` | mp4, mov, avi, mkv, webm, m4v, wmv, flv | top of `app.py` |

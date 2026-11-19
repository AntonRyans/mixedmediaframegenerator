import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.utils import secure_filename

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from flask_cors import CORS

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/extract": {
            "origins": [
                "https://antonryans.github.io"
            ],
            "methods": ["POST"]
        }
    }
)

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
MAX_FRAMES = int(os.environ.get("MAX_FRAMES", "1000"))

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv",
    ".webm", ".m4v", ".wmv", ".flv"
}

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

class ExtractionError(Exception):
    """Raised for problems we want to show to the user."""


def extract_frames_to_zip(video_path, zip_path, mode, value, image_format):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ExtractionError("Couldn't open that file as a video.")

    try:
        if mode == "fps":
            source_fps = cap.get(cv2.CAP_PROP_FPS) or 0
            step = max(1, round(source_fps / value)) if source_fps > 0 else 1
        else:
            step = max(1, int(value))

        if image_format == "jpg":
            ext, params = ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95]
        else:
            ext, params = ".png", []

        saved = 0
        index = 0
        hit_cap = False

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if index % step == 0:
                    encoded_ok, buf = cv2.imencode(ext, frame, params)
                    if not encoded_ok:
                        raise ExtractionError("Failed to encode a frame.")
                    saved += 1
                    zf.writestr(f"frame_{saved:05d}{ext}", buf.tobytes())
                    if saved >= MAX_FRAMES:
                        hit_cap = True
                        break
                index += 1
    finally:
        cap.release()

    if saved == 0:
        raise ExtractionError("No frames could be read from that video.")
    return saved, hit_cap


@app.get("/")
def index():
    return render_template("index.html", max_mb=MAX_UPLOAD_MB, max_frames=MAX_FRAMES)


@app.post("/extract")
def extract():
    upload = request.files.get("video")
    if upload is None or upload.filename == "":
        return jsonify(error="Please choose a video file."), 400

    safe_name = secure_filename(upload.filename) or "video"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return jsonify(error=f"Unsupported file type. Allowed: {allowed}"), 400

    mode = request.form.get("mode", "every")
    if mode not in {"every", "fps"}:
        return jsonify(error="Invalid extraction mode."), 400

    try:
        value = float(request.form.get("value", "1"))
    except ValueError:
        return jsonify(error="Extraction value must be a number."), 400
    if value <= 0 or value > 10000:
        return jsonify(error="Extraction value must be greater than 0."), 400

    image_format = request.form.get("format", "png")
    if image_format not in {"png", "jpg"}:
        return jsonify(error="Invalid image format."), 400

    workdir = tempfile.mkdtemp(prefix="frames_")

    def cleanup():
        shutil.rmtree(workdir, ignore_errors=True)

    try:
        video_path = os.path.join(workdir, "input" + suffix)
        upload.save(video_path)
        zip_path = os.path.join(workdir, "frames.zip")
        saved, hit_cap = extract_frames_to_zip(
            video_path, zip_path, mode, value, image_format
        )
    except ExtractionError as exc:
        cleanup()
        return jsonify(error=str(exc)), 422
    except Exception:
        cleanup()
        app.logger.exception("Unexpected error while extracting frames")
        return jsonify(error="Something went wrong while processing the video."), 500

    download_name = f"{Path(safe_name).stem}_frames.zip"

    def stream_zip():
        try:
            with open(zip_path, "rb") as fh:
                while chunk := fh.read(64 * 1024):
                    yield chunk
        finally:
            cleanup()

    response = Response(stream_zip(), mimetype="application/zip")
    response.headers.set("Content-Disposition", "attachment", filename=download_name)
    response.headers["Content-Length"] = str(os.path.getsize(zip_path))
    response.headers["X-Frame-Count"] = str(saved)
    response.headers["X-Frame-Cap-Hit"] = "1" if hit_cap else "0"
    response.headers["Access-Control-Expose-Headers"] = "X-Frame-Count, X-Frame-Cap-Hit"
    return response


@app.errorhandler(413)
def too_large(_err):
    return jsonify(error=f"That file is too large. The limit is {MAX_UPLOAD_MB} MB."), 413


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)

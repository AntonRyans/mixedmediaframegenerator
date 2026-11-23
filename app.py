import os
from contextlib import closing
import shutil
import tempfile
import zipfile
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from scan_utils import ScanError, split_sheet, METHOD_MESSAGES
from pdf_scan import count_pdf_pages, iter_pdf_pages

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/(extract|scan|limits)": {
            "origins": ["https://antonryans.github.io", r"http://localhost:\d+", r"http://127\.0\.0\.1:\d+"],
            "methods": ["GET", "POST"]
        }
    }
)

# 1024 MiB = 1 GiB (maximum size of one video file).
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "1024"))
MAX_VIDEO_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# The multipart/form-data HTTP request contains additional boundaries and fields.
# Leave 1 MiB for those fields without increasing the file-size allowance.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
MAX_FRAMES = int(os.environ.get("MAX_FRAMES", "1000"))
MAX_SCAN_PAGES = 110  # PDFs can contain multiple printed sheets.
MAX_SCAN_IMAGE_MB = 25
MAX_SCAN_PDF_MB = MAX_UPLOAD_MB  # PDFs may be up to the 1 GiB request limit.

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv",
    ".webm", ".m4v", ".wmv", ".flv"
}

app.config["MAX_CONTENT_LENGTH"] = MAX_VIDEO_BYTES + MULTIPART_OVERHEAD_BYTES

class ExtractionError(Exception):
    """Raised for problems we want to show to the user."""


def save_video_with_limit(upload, destination):
    """Save in bounded-size chunks; never read the whole video into RAM."""
    total = 0
    with open(destination, "wb") as output:
        while chunk := upload.stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_VIDEO_BYTES:
                raise ExtractionError(
                    f"Video exceeds the {MAX_UPLOAD_MB} MB ({MAX_UPLOAD_MB / 1024:g} GB) limit."
                )
            output.write(chunk)
    if not total:
        raise ExtractionError("The uploaded video is empty.")


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


@app.get("/limits")
def limits():
    return jsonify(
        max_mb=MAX_UPLOAD_MB,
        max_frames=MAX_FRAMES,
        max_scan_pages=MAX_SCAN_PAGES,
        max_scan_pdf_mb=MAX_SCAN_PDF_MB,
        max_scan_image_mb=MAX_SCAN_IMAGE_MB,
    )


@app.get("/")
def index():
    return send_from_directory(Path(__file__).resolve().parent, "index.html")


@app.get("/<asset>")
def frontend_asset(asset):
    if asset not in {"app.js", "config.js", "print.js", "scan.js", "zip.js", "style.css"}:
        return jsonify(error="Not found"), 404
    return send_from_directory(Path(__file__).resolve().parent, asset)


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
        save_video_with_limit(upload, video_path)
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


def save_scan_upload(upload, destination, max_bytes, filename):
    """Copy uploaded PDFs/images to disk without loading whole files into RAM."""
    size = 0
    with open(destination, "wb") as output:
        while chunk := upload.stream.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise ScanError(
                    f"{filename}: file exceeds the {max_bytes // (1024 * 1024)} MB limit."
                )
            output.write(chunk)
    if size == 0:
        raise ScanError(f"{filename}: file is empty.")


@app.post("/scan")
def scan():
    """Accept JPG/PNG/WebP or PDFs, and return frames from all sheet pages."""
    uploads = request.files.getlist("images")
    if not uploads or any(not upload.filename for upload in uploads):
        return jsonify(error="Choose one or more PDFs or scanned sheet images."), 400
    if len(uploads) > MAX_SCAN_PAGES:
        return jsonify(error=f"Select at most {MAX_SCAN_PAGES} files at once."), 400

    paper = request.form.get("paper", "a4")
    orientation = request.form.get("orientation", "auto")
    image_format = request.form.get("format", "png")
    alignment = request.form.get("alignment", "auto")
    if alignment not in {"auto", "markers", "page", "full"}:
        return jsonify(error="Invalid alignment mode."), 400
    try:
        last_count = int(request.form.get("last_page_frames", "9"))
    except ValueError:
        return jsonify(error="Last-sheet frame count must be an integer from 1 to 9."), 400
    if not 1 <= last_count <= 9:
        return jsonify(error="Last-sheet frame count must be from 1 to 9."), 400
    if paper not in {"a4", "letter"} or orientation not in {"auto", "portrait", "landscape"}:
        return jsonify(error="Choose a valid paper size and orientation."), 400
    if image_format not in {"png", "jpg"}:
        return jsonify(error="Choose PNG or JPG for the extracted frames."), 400

    import re
    def natural_key(upload):
        return [int(part) if part.isdigit() else part.lower()
                for part in re.split(r"(\d+)", upload.filename)]
    uploads.sort(key=natural_key)

    extension = ".jpg" if image_format == "jpg" else ".png"
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if image_format == "jpg" else []
    workdir = tempfile.mkdtemp(prefix="scanned_frames_")
    output_zip = os.path.join(workdir, "scanned_frames.zip")
    saved = 0
    cap_hit = False
    fallback_count = 0
    scan_report = []
    try:
        # First stage files to disk and count PDF pages. This ensures the
        # last_page_frames option applies to the final PDF page (not the PDF
        # as a whole), even if the user mixes PDFs with image uploads.
        staged = []
        total_pages = 0
        for file_index, uploaded in enumerate(uploads):
            name = secure_filename(uploaded.filename) or f"sheet_{file_index + 1}"
            suffix = Path(name).suffix.lower()
            if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
                raise ScanError(f"{name}: select PDF, JPG, PNG or WebP files.")
            is_pdf = suffix == ".pdf"
            max_mb = MAX_SCAN_PDF_MB if is_pdf else MAX_SCAN_IMAGE_MB
            path = os.path.join(workdir, f"input_{file_index:03d}{suffix}")
            save_scan_upload(uploaded, path, max_mb * 1024 * 1024, name)
            if is_pdf:
                try:
                    page_count = count_pdf_pages(path)
                except ScanError as exc:
                    raise ScanError(f"{name}: {exc}") from exc
            else:
                page_count = 1
            total_pages += page_count
            if total_pages > MAX_SCAN_PAGES:
                raise ScanError(
                    f"Too many scanned pages ({total_pages}). Maximum is {MAX_SCAN_PAGES} "
                    "pages across all PDFs and photos."
                )
            staged.append((name, path, is_pdf, page_count))

        page_number = 0
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_STORED) as archive:
            for name, path, is_pdf, page_count in staged:
                if is_pdf:
                    # close() is important if we stop early at MAX_FRAMES.
                    pages = iter_pdf_pages(path)
                else:
                    with open(path, "rb") as file:
                        image_bytes = file.read()
                    pages = iter((image_bytes,))
                with closing(pages):
                    for local_page_index, page_image in enumerate(pages, 1):
                        page_number += 1
                        label = f"{name}, page {local_page_index}" if is_pdf else name
                        try:
                            frames, method = split_sheet(
                                page_image, paper, orientation, alignment=alignment,
                                source_is_pdf=is_pdf, return_method=True
                            )
                            scan_report.append(f"{label}: {METHOD_MESSAGES[method]}")
                            if method != "four_markers":
                                fallback_count += 1
                        except ScanError as exc:
                            raise ScanError(f"{label}: {exc}") from exc
                        count = last_count if page_number == total_pages else 9
                        for frame in frames[:count]:
                            if saved >= MAX_FRAMES:
                                cap_hit = True
                                break
                            ok, encoded = cv2.imencode(extension, frame, params)
                            if not ok:
                                raise ScanError(f"Could not encode a frame from {label}.")
                            saved += 1
                            archive.writestr(f"frame_{saved:05d}{extension}", encoded.tobytes())
                        if cap_hit:
                            break
                if cap_hit:
                    break
            archive.writestr(
                "scan_report.txt",
                "Frame Extractor - Scan alignment report\n"
                "=======================================\n"
                f"Fallback pages: {fallback_count}\n"
                "Check the extracted frames whenever automatic alignment was used.\n\n"
                + "\n".join(scan_report) + "\n"
            )

    except ScanError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(error=str(exc)), 422
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        app.logger.exception("Unexpected error while processing scanned PDFs/images")
        return jsonify(error="Something went wrong while scanning the sheets."), 500

    def stream_zip():
        try:
            with open(output_zip, "rb") as handle:
                while chunk := handle.read(64 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    response = Response(stream_zip(), mimetype="application/zip")
    response.headers.set("Content-Disposition", "attachment", filename="scanned_frames.zip")
    response.headers["Content-Length"] = str(os.path.getsize(output_zip))
    response.headers["X-Frame-Count"] = str(saved)
    response.headers["X-Frame-Cap-Hit"] = "1" if cap_hit else "0"
    response.headers["X-Scan-Fallback-Pages"] = str(fallback_count)
    response.headers["Access-Control-Expose-Headers"] = "X-Frame-Count, X-Frame-Cap-Hit, X-Scan-Fallback-Pages"
    return response


@app.errorhandler(413)
def too_large(_err):
    return jsonify(error=f"That file is too large. The limit is {MAX_UPLOAD_MB} MB."), 413


@app.get("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)

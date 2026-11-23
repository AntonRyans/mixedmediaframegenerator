"""Recover the nine drawing cells from a marked, printed frame sheet.

The dimensions here must match the print CSS in style.css and the corner
registration marks added in print.js.  Keep the mm constants in sync.
"""
from __future__ import annotations

from itertools import product

import cv2
import numpy as np

PAPERS_MM = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
MARKER_CENTER_MM = 10.0   # 5 mm squares, 7.5 mm in from each paper edge
PAGE_PADDING_X_MM = 13.0
PAGE_PADDING_Y_MM = 16.0
GRID_GAP_MM = 4.0
IMAGE_INSET_MM = 1.25  # inside the printed frame border + 1 mm white padding
LABEL_RESERVE_MM = 5.0  # reserved below each printed image, with/without a name
OUT_PX_PER_MM = 6.0


class ScanError(ValueError):
    pass


def _marker_candidates(image):
    """Find compact, filled, dark quadrilaterals in the scan/photo."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 41, 15
    )
    candidates = []
    min_area = height * width * 0.000012
    max_area = height * width * 0.0035
    for binary in (otsu, adaptive):
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(contour)
            aspect = bw / max(bh, 1)
            if not 0.45 <= aspect <= 2.15:
                continue
            if area / (bw * bh) < 0.58:
                continue
            perimeter = cv2.arcLength(contour, True)
            corners = cv2.approxPolyDP(contour, 0.065 * perimeter, True)
            if len(corners) != 4 or not cv2.isContourConvex(corners):
                continue
            # The squares are solid. Ignore thin box outlines and most drawings.
            contour_mask = np.zeros((bh, bw), dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour - [bx, by]], -1, 255, -1)
            pixels = gray[by:by + bh, bx:bx + bw]
            if cv2.mean(pixels, mask=contour_mask)[0] > 130:
                continue
            cx = bx + bw / 2.0
            cy = by + bh / 2.0
            if any(abs(cx - c[0]) < 4 and abs(cy - c[1]) < 4 for c in candidates):
                continue
            candidates.append((cx, cy, float(area)))
    return candidates


def _find_four_markers(image):
    h, w = image.shape[:2]
    found = _marker_candidates(image)
    if len(found) < 4:
        raise ScanError(
            "Could not find all four black corner squares. Include the full "
            "printed sheet, with the markers visible, in a well-lit photo or scan."
        )
    # Photos should show most of the paper. The registration squares are
    # deliberately outside the 3x3 grid and closest to each page corner.
    locations = ((0, 0), (w, 0), (w, h), (0, h))  # TL, TR, BR, BL
    quadrants = []
    for i, (corner_x, corner_y) in enumerate(locations):
        candidates = [c for c in found
                      if (c[0] < w * 0.42 if i in (0, 3) else c[0] > w * 0.58)
                      and (c[1] < h * 0.42 if i in (0, 1) else c[1] > h * 0.58)]
        candidates.sort(key=lambda c: ((c[0] - corner_x) / w) ** 2 +
                          ((c[1] - corner_y) / h) ** 2)
        quadrants.append(candidates[:7])
    if any(not group for group in quadrants):
        raise ScanError(
            "Corner markers not found on every side. Crop the photo close to "
            "the paper and make sure none of the four squares are cut off."
        )
    best_score, best_points = float("inf"), None
    for combo in product(*quadrants):
        areas = [c[2] for c in combo]
        if min(areas) <= 0 or max(areas) / min(areas) > 5.0:
            continue
        pts = np.array([(c[0], c[1]) for c in combo], dtype=np.float32)
        # Require a large, convex paper-shaped quadrilateral.
        if not cv2.isContourConvex(pts.reshape((-1, 1, 2))):
            continue
        if abs(cv2.contourArea(pts)) < w * h * 0.17:
            continue
        score = sum(((c[0] - x) / w) ** 2 + ((c[1] - y) / h) ** 2
                    for c, (x, y) in zip(combo, locations))
        score += 0.018 * np.log(max(areas) / min(areas))
        if score < best_score:
            best_score, best_points = score, pts
    if best_points is None:
        raise ScanError(
            "The four corner marks could not be matched. Try a flatter scan "
            "or a sharper photo showing the entire page."
        )
    return best_points


def split_sheet(image_bytes: bytes, paper: str = "a4", orientation: str = "auto"):
    """Return exactly nine BGR images, ordered left-to-right / top-to-bottom."""
    if paper not in PAPERS_MM or orientation not in ("auto", "portrait", "landscape"):
        raise ScanError("Invalid scan paper or orientation option.")
    raw = np.frombuffer(image_bytes, dtype=np.uint8)
    full_image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if full_image is None:
        raise ScanError("Could not read this image. Choose a JPG, PNG, or WebP scan.")
    orig_h, orig_w = full_image.shape[:2]
    if orig_h * orig_w > 45_000_000:
        raise ScanError("Scan resolution is too large. Resize to 45 megapixels or less.")
    # Finding small printed marks is more reliable at a predictable resolution.
    detect_scale = min(1.0, 2600.0 / max(orig_h, orig_w))
    if detect_scale < 1:
        work_image = cv2.resize(full_image, None, fx=detect_scale, fy=detect_scale,
                                interpolation=cv2.INTER_AREA)
    else:
        work_image = full_image
    marks = _find_four_markers(work_image)
    # Use the same coordinate space for all detection and warping.
    tl, tr, br, bl = marks
    apparent_width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    apparent_height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    if orientation == "auto":
        is_landscape = apparent_width > apparent_height
    else:
        is_landscape = orientation == "landscape"
    pw, ph = PAPERS_MM[paper]
    if is_landscape:
        pw, ph = ph, pw
    scale = OUT_PX_PER_MM
    dst = np.array([
        [MARKER_CENTER_MM, MARKER_CENTER_MM],
        [pw - MARKER_CENTER_MM, MARKER_CENTER_MM],
        [pw - MARKER_CENTER_MM, ph - MARKER_CENTER_MM],
        [MARKER_CENTER_MM, ph - MARKER_CENTER_MM],
    ], dtype=np.float32) * scale
    transform = cv2.getPerspectiveTransform(marks, dst)
    aligned = cv2.warpPerspective(
        work_image, transform,
        (round(pw * scale), round(ph * scale)),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    cell_w = (pw - 2 * PAGE_PADDING_X_MM - 2 * GRID_GAP_MM) / 3
    cell_h = (ph - 2 * PAGE_PADDING_Y_MM - 2 * GRID_GAP_MM) / 3
    output = []
    for r in range(3):
        for c in range(3):
            x = PAGE_PADDING_X_MM + c * (cell_w + GRID_GAP_MM)
            y = PAGE_PADDING_Y_MM + r * (cell_h + GRID_GAP_MM)
            left = round((x + IMAGE_INSET_MM) * scale)
            right = round((x + cell_w - IMAGE_INSET_MM) * scale)
            top = round((y + IMAGE_INSET_MM) * scale)
            bottom = round((y + cell_h - IMAGE_INSET_MM - LABEL_RESERVE_MM) * scale)
            crop = aligned[top:bottom, left:right]
            if crop.size == 0:
                raise ScanError("A frame crop was empty. Check the paper settings.")
            output.append(crop)
    return output

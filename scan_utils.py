"""Recover frames from printed 3x3 sheets, tolerating imperfect scans.

Try exact four printed markers, then the page outline, then three markers
(affine estimate), and finally the full image. In the last case the image
is assumed to be a tightly cropped scan; callers MUST warn users.

The mm constants must match style.css / print.js.
"""
from __future__ import annotations

from itertools import product

import cv2
import numpy as np

PAPERS_MM = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
MARKER_CENTER_MM = 10.0
PAGE_PADDING_X_MM = 13.0
PAGE_PADDING_Y_MM = 16.0
GRID_GAP_MM = 4.0
IMAGE_INSET_MM = 1.25
LABEL_RESERVE_MM = 5.0
OUT_PX_PER_MM = 6.0

# Reported back to the UI, and also included in the output ZIP's README.
METHOD_MESSAGES = {
    "four_markers": "Aligned using all four corner squares (highest accuracy).",
    "page_outline": "Corner squares were unreliable; used the detected paper edges.",
    "three_markers": "Only three corner squares were usable; estimated alignment. Check crops.",
    "whole_image": "No reliable marks or page edges; treated the full image as the sheet. Check crops and try a tighter photo if needed.",
    "pdf_page": "No reliable marks; used the full PDF page (suitable for one-sheet-per-page PDFs).",
    "full_image_selected": "Used full-image alignment as requested. Check crops if there is background around the paper.",
}


class ScanError(ValueError):
    pass


def _decode_image(image_bytes: bytes | np.ndarray) -> np.ndarray:
    if isinstance(image_bytes, np.ndarray):
        image = image_bytes
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ScanError("Rendered PDF page has an unsupported pixel format.")
    else:
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ScanError("Could not read the image. Choose a JPG, PNG, WebP or PDF file.")
    h, w = image.shape[:2]
    if w < 350 or h < 350:
        raise ScanError("Scan is too small. Use at least 350 pixels along each side.")
    if h * w > 45_000_000:
        raise ScanError("Scan resolution is too large (maximum 45 megapixels).")
    return image


def _marker_candidates(image):
    """Find dark, compact, filled squares; images are downsized before here."""
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
            if not min_area <= area <= max_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(contour)
            if not 0.45 <= bw / max(bh, 1) <= 2.15:
                continue
            if area / max(bw * bh, 1) < 0.58:
                continue
            perimeter = cv2.arcLength(contour, True)
            corners = cv2.approxPolyDP(contour, 0.065 * perimeter, True)
            if len(corners) != 4 or not cv2.isContourConvex(corners):
                continue
            mask = np.zeros((bh, bw), dtype=np.uint8)
            cv2.drawContours(mask, [contour - [bx, by]], -1, 255, -1)
            if cv2.mean(gray[by:by + bh, bx:bx + bw], mask=mask)[0] > 130:
                continue
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            if any(abs(cx - c[0]) < 5 and abs(cy - c[1]) < 5 for c in candidates):
                continue
            candidates.append((cx, cy, float(area)))
    return candidates


def _marker_groups(image):
    h, w = image.shape[:2]
    candidates = _marker_candidates(image)
    corners = ((0, 0), (w, 0), (w, h), (0, h))
    groups = []
    for i, (corner_x, corner_y) in enumerate(corners):
        matches = [c for c in candidates
                   if (c[0] < w * .45 if i in (0, 3) else c[0] > w * .55)
                   and (c[1] < h * .45 if i in (0, 1) else c[1] > h * .55)]
        matches.sort(key=lambda c: ((c[0] - corner_x) / w) ** 2
                     + ((c[1] - corner_y) / h) ** 2)
        groups.append(matches[:6])
    return groups, corners


def _four_markers(image):
    h, w = image.shape[:2]
    groups, corners = _marker_groups(image)
    if any(not g for g in groups):
        return None
    best_score, best_pts = float("inf"), None
    for combo in product(*groups):
        areas = [c[2] for c in combo]
        if min(areas) <= 0 or max(areas) / min(areas) > 5:
            continue
        pts = np.array([(c[0], c[1]) for c in combo], np.float32)
        if not cv2.isContourConvex(pts.reshape(-1, 1, 2)):
            continue
        if abs(cv2.contourArea(pts)) < w * h * 0.17:
            continue
        score = sum(((c[0] - x) / w) ** 2 + ((c[1] - y) / h) ** 2
                    for c, (x, y) in zip(combo, corners))
        score += .018 * np.log(max(areas) / min(areas))
        if score < best_score:
            best_score, best_pts = score, pts
    return best_pts


def _order_corners(pts):
    """Return top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]
    return np.roll(ordered, -int(np.argmin(ordered.sum(axis=1))), axis=0)


def _page_outline(image):
    """Find a large paper-shaped quadrilateral against a contrasting background.

    Never assume a tiny inner frame border is the page boundary.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    canny = cv2.Canny(blur, 35, 115)
    canny = cv2.morphologyEx(canny, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    proposals = []
    for mask in (canny, bright):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            for epsilon in (.015, .025, .04):
                poly = cv2.approxPolyDP(contour, perimeter * epsilon, True)
                if len(poly) != 4 or not cv2.isContourConvex(poly):
                    continue
                points = _order_corners(poly)
                area_ratio = cv2.contourArea(points) / (w * h)
                if area_ratio < .32 or area_ratio > .997:
                    continue
                sides = [np.linalg.norm(points[(j + 1) % 4] - points[j]) for j in range(4)]
                if min(sides) < min(w, h) * .22:
                    continue
                # Reject a very skinny parallelogram or bogus bow-tie shape.
                if max(sides) / max(min(sides), 1) > 4.0:
                    continue
                # Prefer larger page candidates, especially outer edges.
                proposals.append((area_ratio, points))
                break
    if not proposals:
        return None
    proposals.sort(key=lambda p: p[0], reverse=True)
    return proposals[0][1]


def _three_markers(image):
    """Find three consistent corner markers; remaining corner is not required.

    Can only estimate an affine transform, so this is lower accuracy than a
    four-corner perspective correction.
    """
    h, w = image.shape[:2]
    groups, corners = _marker_groups(image)
    # Grid captions, drawings and border corners also look like tiny squares.
    # Only trust reasonably sized, near-the-page-corner candidates for a
    # three-marker fallback; otherwise whole-page alignment is safer.
    min_area = w * h * .00007
    for i, group in enumerate(groups):
        cx, cy = corners[i]
        groups[i] = [c for c in group
                     if c[2] >= min_area
                     and abs(c[0] - cx) / w < .24
                     and abs(c[1] - cy) / h < .19]
    best_score, best = float("inf"), None
    for missing in range(4):
        ids = [i for i in range(4) if i != missing]
        if any(not groups[i] for i in ids):
            continue
        for combo in product(*(groups[i] for i in ids)):
            areas = [c[2] for c in combo]
            if max(areas) / max(min(areas), .001) > 3.5:
                continue
            src = np.array([c[:2] for c in combo], np.float32)
            # Must cover a substantial area and not be almost collinear.
            if cv2.contourArea(src) < w * h * .09:
                continue
            score = sum(((c[0] - corners[i][0]) / w) ** 2
                        + ((c[1] - corners[i][1]) / h) ** 2
                        for c, i in zip(combo, ids))
            score += .02 * np.log(max(areas) / min(areas))
            if score < best_score:
                best_score, best = score, (ids, src)
    return best


def _size_for(paper, orientation, horizontal, vertical):
    landscape = horizontal > vertical if orientation == "auto" else orientation == "landscape"
    pw, ph = PAPERS_MM[paper]
    return (ph, pw) if landscape else (pw, ph)


def _warp_from_four(image, points, paper, orientation, marker_points=False):
    tl, tr, br, bl = points
    aw = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    ah = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    pw, ph = _size_for(paper, orientation, aw, ah)
    m = MARKER_CENTER_MM if marker_points else 0
    output_points = np.array([
        [m, m], [pw - m, m], [pw - m, ph - m], [m, ph - m]
    ], np.float32) * OUT_PX_PER_MM
    transform = cv2.getPerspectiveTransform(points, output_points)
    aligned = cv2.warpPerspective(
        image, transform, (round(pw * OUT_PX_PER_MM), round(ph * OUT_PX_PER_MM)),
        flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255)
    )
    return aligned, pw, ph


def _warp_from_three(image, found, paper, orientation):
    ids, src = found
    dist = {tuple(sorted((i, j))): float(np.linalg.norm(a - b))
            for i, a in zip(ids, src) for j, b in zip(ids, src) if i < j}
    # Adjacent sides where possible, otherwise use the diagonal / known ratio.
    widths = [dist[p] for p in ((0, 1), (2, 3)) if p in dist]
    heights = [dist[p] for p in ((0, 3), (1, 2)) if p in dist]
    aw = widths[0] if widths else image.shape[1]
    ah = heights[0] if heights else image.shape[0]
    pw, ph = _size_for(paper, orientation, aw, ah)
    m = MARKER_CENTER_MM
    dst4 = np.array([[m, m], [pw - m, m], [pw - m, ph - m], [m, ph - m]], np.float32)
    dest = dst4[ids] * OUT_PX_PER_MM
    affine = cv2.getAffineTransform(src, dest)
    aligned = cv2.warpAffine(
        image, affine, (round(pw * OUT_PX_PER_MM), round(ph * OUT_PX_PER_MM)),
        flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255)
    )
    return aligned, pw, ph


def _crop_grid(aligned, pw, ph):
    scale = OUT_PX_PER_MM
    cell_w = (pw - 2 * PAGE_PADDING_X_MM - 2 * GRID_GAP_MM) / 3
    cell_h = (ph - 2 * PAGE_PADDING_Y_MM - 2 * GRID_GAP_MM) / 3
    frames = []
    for row in range(3):
        for col in range(3):
            x = PAGE_PADDING_X_MM + col * (cell_w + GRID_GAP_MM)
            y = PAGE_PADDING_Y_MM + row * (cell_h + GRID_GAP_MM)
            left = round((x + IMAGE_INSET_MM) * scale)
            right = round((x + cell_w - IMAGE_INSET_MM) * scale)
            top = round((y + IMAGE_INSET_MM) * scale)
            bottom = round((y + cell_h - IMAGE_INSET_MM - LABEL_RESERVE_MM) * scale)
            crop = aligned[top:bottom, left:right]
            if not crop.size:
                raise ScanError("A frame crop was empty; check paper size and orientation.")
            frames.append(crop)
    return frames


def split_sheet(image_bytes: bytes | np.ndarray, paper: str = "a4",
                orientation: str = "auto", alignment: str = "auto",
                source_is_pdf: bool = False, return_method: bool = False):
    """Split 3x3 printed sheet into nine BGR images in reading order.

    alignment: auto (adaptive), markers (strict), page (no markers required),
               full (treat whole image as the printed page).
    PDF auto fallback prefers using full PDF page over photo-boundary guessing.
    """
    if paper not in PAPERS_MM or orientation not in {"auto", "portrait", "landscape"}:
        raise ScanError("Invalid paper size or orientation.")
    if alignment not in {"auto", "markers", "page", "full"}:
        raise ScanError("Invalid scan alignment mode.")
    image = _decode_image(image_bytes)
    h, w = image.shape[:2]
    scale = min(1.0, 2600.0 / max(h, w))
    work = cv2.resize(image, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_AREA) if scale < 1 else image
    wh, ww = work.shape[:2]

    aligned, pw, ph, method = None, None, None, None
    if alignment in {"auto", "markers"}:
        four = _four_markers(work)
        if four is not None:
            aligned, pw, ph = _warp_from_four(work, four, paper, orientation, True)
            method = "four_markers"
        elif alignment == "markers":
            raise ScanError("Four marker alignment was requested, but all four squares could not be matched. Try Auto alignment instead.")

    if aligned is None and alignment in {"auto", "page"}:
        # Fully rasterized PDFs include the whole sheet by definition; edges of
        # the rendered page are more reliable than inner drawn boxes.
        if source_is_pdf:
            points = np.array([[0, 0], [ww - 1, 0], [ww - 1, wh - 1], [0, wh - 1]], np.float32)
            aligned, pw, ph = _warp_from_four(work, points, paper, orientation)
            method = "pdf_page"
        else:
            page = _page_outline(work)
            if page is not None:
                aligned, pw, ph = _warp_from_four(work, page, paper, orientation)
                method = "page_outline"

    if aligned is None and alignment == "auto" and not source_is_pdf:
        three = _three_markers(work)
        if three is not None:
            aligned, pw, ph = _warp_from_three(work, three, paper, orientation)
            method = "three_markers"

    if aligned is None:
        points = np.array([[0, 0], [ww - 1, 0], [ww - 1, wh - 1], [0, wh - 1]], np.float32)
        aligned, pw, ph = _warp_from_four(work, points, paper, orientation)
        method = "full_image_selected" if alignment == "full" else "whole_image"

    frames = _crop_grid(aligned, pw, ph)
    return (frames, method) if return_method else frames

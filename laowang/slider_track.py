from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

TRACK_MIN_DURATION_MS = 1001
TRACK_MIN_MOVE_DURATION_MS = 1100
TRACK_MAX_DURATION_MS = 1999
TRACK_Y_JITTER_MIN = 1
TRACK_Y_JITTER_MAX = 5
DEFAULT_START_X = 547
DEFAULT_START_Y = 425
TEXTURE_MATCH_MIN_SCORE = 0.55
MERGED_DIFF_WIDTH_FACTOR = 1.25
COLOR_MATCH_MIN_SCORE = 0.65
COLOR_MATCH_MAX_SQDIFF = 0.08


@dataclass(frozen=True)
class SliderResult:
    move_x: int
    start_x: int
    start_y: int
    piece_x: int
    target_x: int
    target_y: int
    score: float
    points: list[dict[str, int]]
    deltas: list[dict[str, int]]


def calc_slider_track(
    image_path: str | Path,
    *,
    start_x: int = DEFAULT_START_X,
    start_y: int = DEFAULT_START_Y,
    seed: int | None = None,
    debug_dir: str | Path | None = None,
) -> SliderResult:
    """
    读取三段式滑块图，计算黑底卡片相对真实缺口的水平移动轨迹。

    适用图片结构：
    1. 上半部分：带真假缺口的背景图
    2. 中间：黑色背景，里面有可水平移动的卡片
    3. 下半部分：原始背景图或接近原始背景图
    

    返回：
    - move_x: 卡片需要向右移动的像素数
    - start_x/start_y: 拖拽动作的屏幕起始坐标
    - points: 绝对轨迹点，格式为 {x, y, t}
    - deltas: 相邻点增量，格式为 {dx, dy, dt}，适合拖拽接口

    依赖：
    pip install opencv-python numpy
    """
    image_path = Path(image_path)
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"图片读取失败: {image_path}")
    h, w = img.shape[:2]
    print(f"image size: {w}x{h} (width x height)")

    top_img, slider_band, bottom_img, _band_y0 = _split_three_bands(img)
    piece_crop, piece_mask, piece_bbox = _extract_piece(slider_band)

    piece_x = piece_bbox[0]
    target_x, target_y, score = _find_target_by_background_diff(
        top_img,
        bottom_img,
        piece_crop,
        piece_mask,
    )
    move_x = int(round(target_x - piece_x))
    if move_x < 0:
        # 保底退回到上方缺口图匹配，避免下方原图纹理把位置带偏。
        alt_x, alt_y, alt_score = _match_piece_texture(piece_crop, piece_mask, top_img)
        if alt_score > score:
            target_x, target_y, score = alt_x, alt_y, alt_score
            move_x = int(round(target_x - piece_x))

    points = make_horizontal_track(move_x, start_x=start_x, start_y=start_y, seed=seed)
    deltas = _points_to_deltas(points)

    if debug_dir is not None:
        _save_debug(
            Path(debug_dir),
            top_img,
            slider_band,
            bottom_img,
            piece_crop,
            piece_mask,
            piece_bbox,
            target_x,
            target_y,
        )

    return SliderResult(
        move_x=move_x,
        start_x=int(start_x),
        start_y=int(start_y),
        piece_x=piece_x,
        target_x=int(target_x),
        target_y=int(target_y),
        score=float(score),
        points=points,
        deltas=deltas,
    )


def make_horizontal_track(
    distance: int,
    *,
    start_x: int = 0,
    start_y: int = 0,
    seed: int | None = None,
    y_jitter_min: int = TRACK_Y_JITTER_MIN,
    y_jitter_max: int = TRACK_Y_JITTER_MAX,
) -> list[dict[str, int]]:
    """生成水平拖拽轨迹，Y 轴围绕起点做小幅波动，返回 [{x, y, t}]。"""
    rng = random.Random(seed)
    total = int(round(distance))
    direction = 1 if total >= 0 else -1
    dist = abs(total)
    y_jitter_min = max(0, int(y_jitter_min))
    y_jitter_max = max(y_jitter_min, int(y_jitter_max))

    if dist == 0:
        return [{"x": start_x, "y": start_y, "t": 0}]

    steps = max(14, min(42, dist // 3 + 12))
    tail_pause = rng.randint(40, 90)
    duration = rng.randint(TRACK_MIN_MOVE_DURATION_MS, TRACK_MAX_DURATION_MS - tail_pause)

    points: list[dict[str, int]] = [{"x": start_x, "y": start_y, "t": 0}]
    last_x = 0
    y_offset = 0

    for i in range(1, steps + 1):
        p = i / steps
        eased = 1 - (1 - p) ** 3
        x = int(round(dist * eased))
        if x <= last_x:
            x = min(dist, last_x + 1)
        if x > dist:
            x = dist

        t = int(round(duration * p + rng.randint(-8, 8)))
        t = max(t, points[-1]["t"] + 8)
        y_offset = _next_y_offset(rng, y_offset, y_jitter_min, y_jitter_max)
        points.append({"x": start_x + direction * x, "y": start_y + y_offset, "t": t})
        last_x = x
        if last_x >= dist:
            break

    if points[-1]["x"] != start_x + total:
        y_offset = _next_y_offset(rng, y_offset, y_jitter_min, y_jitter_max)
        points.append({
            "x": start_x + total,
            "y": start_y + y_offset,
            "t": min(TRACK_MAX_DURATION_MS - tail_pause, duration + rng.randint(20, 45)),
        })
    else:
        last = points[-1]
        points[-1] = {"x": last["x"], "y": last["y"], "t": last["t"]}

    final_t = min(TRACK_MAX_DURATION_MS, max(TRACK_MIN_DURATION_MS, points[-1]["t"] + tail_pause))
    y_offset = _next_y_offset(rng, y_offset, y_jitter_min, y_jitter_max)
    points.append({"x": start_x + total, "y": start_y + y_offset, "t": final_t})
    return points


def _next_y_offset(
    rng: random.Random,
    current: int,
    jitter_min: int,
    jitter_max: int,
) -> int:
    if jitter_max <= 0:
        return 0

    offset = current + rng.randint(-2, 2)
    offset = max(-jitter_max, min(jitter_max, offset))
    if abs(offset) >= jitter_min:
        return offset

    sign = -1 if current < 0 else 1
    if current == 0:
        sign = rng.choice((-1, 1))
    return sign * jitter_min


def _split_three_bands(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    black_ratio = (gray < 25).mean(axis=1)
    rows = np.where(black_ratio > 0.68)[0]
    if rows.size == 0:
        raise ValueError("未检测到中间黑色滑块区域")

    runs: list[tuple[int, int]] = []
    start = int(rows[0])
    prev = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row == prev + 1:
            prev = row
            continue
        runs.append((start, prev + 1))
        start = prev = row
    runs.append((start, prev + 1))

    y0, y1 = max(runs, key=lambda r: r[1] - r[0])
    if y1 - y0 < 20:
        raise ValueError("黑色滑块区域高度异常")

    top = img[:y0].copy()
    slider = img[y0:y1].copy()
    bottom = img[y1:].copy()
    if top.size == 0 or bottom.size == 0:
        raise ValueError("图片不是预期的上图/黑底/下图三段结构")

    return top, slider, bottom, y0


def _extract_piece(slider_band: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    gray = cv2.cvtColor(slider_band, cv2.COLOR_BGR2GRAY)
    non_black = (gray > 35).astype(np.uint8) * 255

    kernel = np.ones((3, 3), np.uint8)
    non_black = cv2.morphologyEx(non_black, cv2.MORPH_CLOSE, kernel, iterations=2)
    non_black = cv2.dilate(non_black, kernel, iterations=1)

    contours, _ = cv2.findContours(non_black, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("未从黑色区域中检测到卡片")

    h, w = slider_band.shape[:2]
    candidates: list[tuple[int, tuple[int, int, int, int], Any]] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if bw < 12 or bh < 12:
            continue
        if bw > w * 0.55 or bh > h * 0.8:
            continue
        candidates.append((int(area), (x, y, bw, bh), contour))

    if not candidates:
        raise ValueError("卡片轮廓尺寸异常，无法定位")

    _, bbox, _ = max(candidates, key=lambda item: item[0])
    x, y, bw, bh = bbox
    pad = 2
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + bw + pad)
    y1 = min(h, y + bh + pad)

    crop = slider_band[y0:y1, x0:x1].copy()
    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = (crop_gray > 35).astype(np.uint8) * 255

    # 去掉常见的绿色描边，只保留卡片内部纹理去匹配背景。
    b, g, r = cv2.split(crop)
    green = ((g > 80) & (g > r * 1.25) & (g > b * 1.25)).astype(np.uint8) * 255
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(green))
    mask = cv2.erode(mask, kernel, iterations=1)

    if cv2.countNonZero(mask) < 80:
        # 如果卡片内部过暗，退回到包含描边的轮廓掩码。
        mask = (crop_gray > 25).astype(np.uint8) * 255

    return crop, mask, (x0, y0, x1 - x0, y1 - y0)


def _match_piece_texture(
    piece_crop: np.ndarray,
    piece_mask: np.ndarray,
    background: np.ndarray,
) -> tuple[int, int, float]:
    bg = background
    th, tw = piece_crop.shape[:2]
    bh, bw = bg.shape[:2]
    if bh < th or bw < tw:
        scale = max(th / bh, tw / bw) + 0.01
        bg = cv2.resize(bg, (int(bw * scale), int(bh * scale)), interpolation=cv2.INTER_LINEAR)

    piece_gray = cv2.cvtColor(piece_crop, cv2.COLOR_BGR2GRAY)
    bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)

    piece_edge = cv2.Canny(piece_gray, 40, 120)
    bg_edge = cv2.Canny(bg_gray, 40, 120)
    edge_mask = cv2.bitwise_and(piece_mask, (piece_edge > 0).astype(np.uint8) * 255)
    if cv2.countNonZero(edge_mask) < 50:
        edge_mask = piece_mask

    result = cv2.matchTemplate(bg_edge, piece_edge, cv2.TM_CCORR_NORMED, mask=edge_mask)
    finite = np.isfinite(result)
    if not finite.any():
        raise ValueError("模板匹配结果无有效分数")
    # OpenCV 的 masked TM_CCORR_NORMED 在空边缘窗口上可能产生 inf/nan，不能让它参与取最大值。
    result = result.copy()
    result[~finite] = -1.0
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return int(max_loc[0]), int(max_loc[1]), float(max_val)


def _make_piece_color_mask(piece_crop: np.ndarray, fallback_mask: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(piece_crop, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(piece_crop)
    green = ((g > 80) & (g > r * 1.25) & (g > b * 1.25))
    mask = ((gray > 55) & ~green).astype(np.uint8) * 255
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=1)
    if cv2.countNonZero(mask) < 80:
        return fallback_mask
    return mask


def _match_piece_color(
    piece_crop: np.ndarray,
    piece_mask: np.ndarray,
    background: np.ndarray,
) -> tuple[int, int, float, float]:
    color_mask = _make_piece_color_mask(piece_crop, piece_mask)
    result = cv2.matchTemplate(
        background,
        piece_crop,
        cv2.TM_CCOEFF_NORMED,
        mask=color_mask,
    )
    finite = np.isfinite(result)
    if not finite.any():
        return 0, 0, -1.0, 1.0
    result = result.copy()
    result[~finite] = -1.0
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    sqdiff = cv2.matchTemplate(
        background,
        piece_crop,
        cv2.TM_SQDIFF_NORMED,
        mask=color_mask,
    )
    finite = np.isfinite(sqdiff)
    if finite.any():
        sqdiff = sqdiff.copy()
        sqdiff[~finite] = 1.0
        min_val = float(sqdiff[max_loc[1], max_loc[0]])
    else:
        min_val = 1.0

    return int(max_loc[0]), int(max_loc[1]), float(max_val), min_val


def _find_target_by_background_diff(
    top_img: np.ndarray,
    bottom_img: np.ndarray,
    piece_crop: np.ndarray,
    piece_mask: np.ndarray,
) -> tuple[int, int, float]:
    """通过上方缺口图和下方原图的差异定位真实缺口。"""
    top = top_img
    bottom = bottom_img
    if top.shape[:2] != bottom.shape[:2]:
        bottom = cv2.resize(
            bottom,
            (top.shape[1], top.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )

    color_x, color_y, color_score, color_sqdiff = _match_piece_color(
        piece_crop,
        piece_mask,
        bottom,
    )
    color_is_reliable = _is_reliable_color_match(color_score, color_sqdiff)
    texture_x, texture_y, texture_score = _match_piece_texture(piece_crop, piece_mask, bottom)
    reference_x = color_x if color_is_reliable else texture_x

    diff = cv2.absdiff(top, bottom)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    otsu_threshold, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )
    kernel = np.ones((3, 3), np.uint8)
    ph, pw = piece_crop.shape[:2]
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    thresholds = [int(round(otsu_threshold)), 18, 25, 35]
    for threshold in dict.fromkeys(max(8, threshold) for threshold in thresholds):
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        for close_iterations in (0, 1):
            candidate_map = binary.copy()
            if close_iterations:
                candidate_map = cv2.morphologyEx(
                    candidate_map,
                    cv2.MORPH_CLOSE,
                    kernel,
                    iterations=close_iterations,
                )
            candidate_map = cv2.morphologyEx(candidate_map, cv2.MORPH_OPEN, kernel, iterations=1)

            contours, _ = cv2.findContours(
                candidate_map,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = cv2.contourArea(contour)
                if w < pw * 0.35 or h < ph * 0.35:
                    continue
                if w > pw * 2.25 or h > ph * 2.0:
                    continue

                roi = candidate_map[y:y + h, x:x + w]
                density = cv2.countNonZero(roi) / float(w * h)
                size_penalty = abs(w - pw) / max(pw, 1) + abs(h - ph) / max(ph, 1)
                texture_penalty = abs(x - reference_x) / max(top.shape[1], 1)
                score = (
                    density
                    + min(area / max(pw * ph, 1), 2.0)
                    - size_penalty * 0.25
                    - texture_penalty * 1.5
                )
                candidates.append((float(score), (x, y, w, h)))

    if not candidates:
        if color_is_reliable:
            return int(color_x), int(color_y), float(color_score)
        return int(texture_x), int(texture_y), float(texture_score)

    score, (x, y, w, h) = max(candidates, key=lambda item: item[0])
    if _should_prefer_color_match(
        diff_bbox=(x, y, w, h),
        color_x=color_x,
        color_y=color_y,
        color_score=color_score,
        color_sqdiff=color_sqdiff,
        piece_height=ph,
    ):
        return int(color_x), int(color_y), float(color_score)

    if _should_prefer_texture_match(
        diff_bbox=(x, y, w, h),
        texture_x=texture_x,
        texture_y=texture_y,
        texture_score=texture_score,
        piece_width=pw,
        piece_height=ph,
    ):
        return int(texture_x), int(texture_y), float(texture_score)

    return int(x), int(y), float(score)


def _is_reliable_color_match(color_score: float, color_sqdiff: float) -> bool:
    return color_score >= COLOR_MATCH_MIN_SCORE and color_sqdiff <= COLOR_MATCH_MAX_SQDIFF


def _should_prefer_color_match(
    *,
    diff_bbox: tuple[int, int, int, int],
    color_x: int,
    color_y: int,
    color_score: float,
    color_sqdiff: float,
    piece_height: int,
) -> bool:
    if not _is_reliable_color_match(color_score, color_sqdiff):
        return False

    x, y, w, h = diff_bbox
    x_margin = max(6, int(w * 0.12))
    texture_inside_diff = x - x_margin <= color_x <= x + w
    y_close = abs(color_y - y) <= max(12, int(piece_height * 0.5))
    return texture_inside_diff and y_close


def _should_prefer_texture_match(
    *,
    diff_bbox: tuple[int, int, int, int],
    texture_x: int,
    texture_y: int,
    texture_score: float,
    piece_width: int,
    piece_height: int,
) -> bool:
    """差分框可能包含阴影/轮廓，过宽时用拼图纹理坐标修正真实落点。"""
    if texture_score < TEXTURE_MATCH_MIN_SCORE:
        return False

    x, y, w, h = diff_bbox
    if w <= piece_width * MERGED_DIFF_WIDTH_FACTOR:
        return False

    texture_inside_diff = x <= texture_x <= x + w
    y_close = abs(texture_y - y) <= max(8, int(piece_height * 0.45))
    return texture_inside_diff and y_close


def _points_to_deltas(points: list[dict[str, int]]) -> list[dict[str, int]]:
    deltas: list[dict[str, int]] = []
    for prev, cur in zip(points, points[1:]):
        deltas.append({
            "dx": cur["x"] - prev["x"],
            "dy": cur["y"] - prev["y"],
            "dt": cur["t"] - prev["t"],
        })
    return deltas


def _save_debug(
    debug_dir: Path,
    top_img: np.ndarray,
    slider_band: np.ndarray,
    bottom_img: np.ndarray,
    piece_crop: np.ndarray,
    piece_mask: np.ndarray,
    piece_bbox: tuple[int, int, int, int],
    target_x: int,
    target_y: int,
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "01_top.jpg"), top_img)
    cv2.imwrite(str(debug_dir / "02_slider_band.jpg"), slider_band)
    cv2.imwrite(str(debug_dir / "03_bottom.jpg"), bottom_img)
    cv2.imwrite(str(debug_dir / "04_piece.jpg"), piece_crop)
    cv2.imwrite(str(debug_dir / "05_piece_mask.jpg"), piece_mask)

    marked = top_img.copy()
    ph, pw = piece_crop.shape[:2]
    cv2.rectangle(marked, (target_x, target_y), (target_x + pw, target_y + ph), (0, 0, 255), 2)
    cv2.imwrite(str(debug_dir / "06_target_on_top.jpg"), marked)

    marked_bottom = bottom_img.copy()
    cv2.rectangle(
        marked_bottom,
        (target_x, target_y),
        (target_x + pw, target_y + ph),
        (0, 0, 255),
        2,
    )
    cv2.imwrite(str(debug_dir / "06_target_on_bottom_reference.jpg"), marked_bottom)

    marked_slider = slider_band.copy()
    x, y, w, h = piece_bbox
    cv2.rectangle(marked_slider, (x, y), (x + w, y + h), (0, 0, 255), 2)
    cv2.imwrite(str(debug_dir / "07_piece_bbox.jpg"), marked_slider)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--debug-dir")
    parser.add_argument("--start-x", type=int, default=DEFAULT_START_X)
    parser.add_argument("--start-y", type=int, default=DEFAULT_START_Y)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    result = calc_slider_track(
        args.image,
        start_x=args.start_x,
        start_y=args.start_y,
        seed=args.seed,
        debug_dir=args.debug_dir,
    )
    print(
        {
            "move_x": result.move_x,
            "start_x": result.start_x,
            "start_y": result.start_y,
            "piece_x": result.piece_x,
            "target_x": result.target_x,
            "target_y": result.target_y,
            "score": round(result.score, 4),
            "points": result.points,
            "deltas": result.deltas,
        }
    )

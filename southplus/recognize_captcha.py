#!/usr/bin/env python3
import argparse
from collections import Counter
import re
import sys
from pathlib import Path


DEFAULT_IMAGE = Path(__file__).with_name("captcha.jpg")


def normalize_result(text, numeric_only=True):
    text = (text or "").strip()
    if numeric_only:
        return re.sub(r"\D+", "", text)
    return re.sub(r"[^0-9A-Za-z]+", "", text)


def build_ddddocr(beta=False):
    try:
        import ddddocr
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖 ddddocr，请先执行：python3 -m pip install -r southplus/requirements-captcha.txt"
        ) from exc

    return ddddocr.DdddOcr(show_ad=False, beta=beta)


def recognize_with_ddddocr(image_path):
    ocr = build_ddddocr()
    return recognize_whole_image(ocr, image_path)


def recognize_whole_image(ocr, image_path):
    return ocr.classification(image_path.read_bytes())


def iter_whole_preprocess_variants(image_path):
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"图片读取失败: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    _, saturation, value = cv2.split(hsv)

    yield "scaled", cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    dark_mask = cv2.inRange(gray, 0, 150)
    dark = np.full_like(gray, 255)
    dark[dark_mask > 0] = 0
    yield "dark", cv2.resize(cv2.cvtColor(dark, cv2.COLOR_GRAY2BGR), None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    color_mask = (((saturation > 65) & (value < 250)) | (gray < 145)).astype(np.uint8) * 255
    color = np.full_like(image, 255)
    color[color_mask > 0] = image[color_mask > 0]
    yield "color", cv2.resize(color, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def recognize_whole_fallbacks(ocr, image_path, numeric_only=True, beta_ocr=None):
    results = []
    for source_ocr, prefix in [(ocr, "std"), (beta_ocr, "beta")]:
        if source_ocr is None:
            continue
        for variant, image in iter_whole_preprocess_variants(image_path):
            raw = source_ocr.classification(encode_png(image))
            results.append(
                {
                    "engine": prefix,
                    "variant": variant,
                    "raw": raw,
                    "text": normalize_result(raw, numeric_only=numeric_only),
                }
            )
    return results


def encode_png(image):
    import cv2

    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("验证码图片编码失败")
    return buffer.tobytes()


SIMILAR_DIGIT_MAP = {
    "o": "0",
    "O": "0",
    "D": "0",
    "d": "0",
    "Q": "0",
    "l": "1",
    "I": "1",
    "i": "1",
    "|": "1",
    "一": "1",
    "z": "2",
    "Z": "2",
    "g": "9",
    "q": "9",
    "G": "6",
    "b": "6",
    "B": "8",
}


def normalize_candidate_char(raw):
    text = (raw or "").strip()
    digit = re.sub(r"\D+", "", text)
    if digit:
        return digit[0]
    for char in text:
        mapped = SIMILAR_DIGIT_MAP.get(char)
        if mapped:
            return mapped
    return ""


def merge_boxes(boxes):
    merged = []
    for box in sorted(boxes, key=lambda item: item["score"], reverse=True):
        x0, y0, x1, y1 = box["box"]
        area = max(1, (x1 - x0) * (y1 - y0))
        target = None
        for item in merged:
            sx0, sy0, sx1, sy1 = item["box"]
            sarea = max(1, (sx1 - sx0) * (sy1 - sy0))
            ix = max(0, min(x1, sx1) - max(x0, sx0))
            iy = max(0, min(y1, sy1) - max(y0, sy0))
            if ix * iy / min(area, sarea) > 0.55:
                target = item
                break
        if target is None:
            merged.append(dict(box))
            continue
        tx0, ty0, tx1, ty1 = target["box"]
        target["box"] = (min(tx0, x0), min(ty0, y0), max(tx1, x1), max(ty1, y1))
        target["score"] += box["score"]
        target["sources"].add(box["source"])
    return sorted(merged, key=lambda item: item["box"][0])


def find_large_char_boxes(image_path):
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"图片读取失败: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    masks = [
        ("dark", cv2.inRange(gray, 0, 125)),
        ("sat", cv2.inRange(hsv, np.array([0, 95, 0]), np.array([179, 255, 255]))),
        ("mid", cv2.inRange(hsv, np.array([0, 70, 0]), np.array([179, 255, 210]))),
    ]

    boxes = []
    for source, mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, w, h, area = [int(value) for value in stats[index]]
            density = area / max(1, w * h)
            if h < 17 or w < 5 or area < 70:
                continue
            if density < 0.20 or w > 35 or h > 45:
                continue
            boxes.append(
                {
                    "box": (x, y, x + w, y + h),
                    "score": area + h * 8 + min(w, 28) * 4,
                    "source": source,
                    "sources": {source},
                }
            )

    return image, merge_boxes(boxes)


def recognize_segmented_image(ocr, image_path, numeric_only=True):
    import cv2

    image, boxes = find_large_char_boxes(image_path)
    height, width = image.shape[:2]
    chars = []
    debug_boxes = []
    for item in boxes:
        x0, y0, x1, y1 = item["box"]
        pad = 4
        crop = image[max(0, y0 - pad) : min(height, y1 + pad), max(0, x0 - pad) : min(width, x1 + pad)]
        if crop.size == 0:
            continue
        crop = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        raw = ocr.classification(encode_png(crop))
        char = normalize_result(raw, numeric_only=numeric_only)
        debug_boxes.append({**item, "raw": raw, "char": char})
        if char:
            chars.append(char[:1])
    return "".join(chars), debug_boxes


def find_candidate_chars(ocr, image_path):
    import cv2
    import numpy as np

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"图片读取失败: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = []
    for saturation in [35, 50, 70, 90, 110]:
        masks.append(cv2.inRange(hsv, np.array([0, saturation, 0]), np.array([179, 255, 255])))
    for gray_max in [110, 140, 170, 200]:
        masks.append(cv2.inRange(gray, 0, gray_max))

    candidates = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            x, y, w, h, area = [int(value) for value in stats[index]]
            density = area / max(1, w * h)
            if not (3 <= w <= 50 and 5 <= h <= 50 and 12 <= area <= 650 and density >= 0.08):
                continue
            crop = image[max(0, y - 3) : min(60, y + h + 3), max(0, x - 3) : min(150, x + w + 3)]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
            raw = ocr.classification(encode_png(crop))
            char = normalize_candidate_char(raw)
            if not char:
                continue
            score = area + h * 5 + w * 2
            if raw.strip().isdigit():
                score += 40
            elif len(raw.strip()) > 1:
                score -= 30
            candidates.append({"box": (x, y, w, h), "raw": raw, "char": char, "score": score})

    selected = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        x, y, w, h = candidate["box"]
        area = max(1, w * h)
        duplicate = False
        for item in selected:
            ox, oy, ow, oh = item["box"]
            intersection = max(0, min(x + w, ox + ow) - max(x, ox)) * max(0, min(y + h, oy + oh) - max(y, oy))
            if intersection / min(area, max(1, ow * oh)) > 0.55:
                duplicate = True
                break
        if not duplicate:
            selected.append(candidate)
    return sorted(selected, key=lambda item: item["box"][0])


def recognize_candidate_image(ocr, image_path, expected_len=4):
    candidates = find_candidate_chars(ocr, image_path)
    if expected_len != 4:
        return "".join(item["char"] for item in candidates[:expected_len]), candidates

    centers = [18, 55, 92, 129]
    chosen = []
    used = set()
    for center in centers:
        available = []
        for index, item in enumerate(candidates):
            if index in used:
                continue
            x, _, w, _ = item["box"]
            distance = abs((x + w / 2) - center)
            available.append((distance, -item["score"], index, item))
        if not available:
            continue
        _, _, index, item = min(available)
        used.add(index)
        chosen.append(item)
    return "".join(item["char"] for item in sorted(chosen, key=lambda item: item["box"][0])), candidates


def choose_fallback_result(fallbacks, expected_len, min_votes=1):
    if not expected_len:
        return ""
    exact = [item["text"] for item in fallbacks if len(item.get("text", "")) == expected_len]
    if not exact:
        return ""
    most_common = Counter(exact).most_common(1)
    if not most_common:
        return ""
    if min_votes <= 1:
        return most_common[0][0] if len(most_common) == 1 or most_common[0][1] > most_common[1][1] else exact[0]
    if most_common[0][1] < min_votes:
        return ""
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        return ""
    return most_common[0][0]


def choose_result(whole, segmented, candidate="", expected_len=None, fallbacks=None):
    fallbacks = fallbacks or []
    if expected_len:
        if expected_len == 4 and len(whole) == 4 and len(candidate) == 4 and whole != candidate:
            if candidate == segmented[:4]:
                return candidate
            if len(segmented) == 3 and candidate[1:] == segmented and whole[1:] == segmented:
                return candidate
            if (
                len(segmented) == 3
                and candidate[0] + candidate[1] + candidate[3] == segmented
                and whole[0] + whole[1] + whole[3] == segmented
            ):
                return candidate
        consensus_fallback = choose_fallback_result(fallbacks, expected_len, min_votes=3)
        fallback = choose_fallback_result(fallbacks, expected_len)
        if consensus_fallback:
            return consensus_fallback
        if len(whole) == expected_len:
            return whole
        if len(candidate) == expected_len:
            return candidate
        if len(segmented) == expected_len:
            return segmented
        if fallback:
            return fallback
    if not segmented:
        return whole
    if not whole:
        return segmented
    if 2 <= len(segmented) <= 4 and len(whole) > 4:
        return segmented
    if len(segmented) >= 3 and len(whole) <= 1:
        return segmented
    if len(candidate) > len(whole):
        return candidate
    return whole


def recognize_with_tesseract(image_path, numeric_only=True):
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("缺少依赖 pytesseract/Pillow") from exc

    whitelist = "0123456789" if numeric_only else "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    config = f"--psm 8 -c tessedit_char_whitelist={whitelist}"
    return pytesseract.image_to_string(Image.open(image_path), config=config)


def parse_args():
    parser = argparse.ArgumentParser(description="识别 South Plus 数字验证码图片。")
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE), help="验证码图片路径，默认 southplus/captcha.jpg")
    parser.add_argument(
        "--engine",
        choices=["ddddocr", "tesseract"],
        default="ddddocr",
        help="识别引擎，默认 ddddocr",
    )
    parser.add_argument(
        "--keep-alnum",
        action="store_true",
        help="保留英文和数字；默认只保留数字，适合 South Plus 这类数字验证码",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "whole", "segment", "candidate"],
        default="auto",
        help="识别模式：whole 整图，segment 大字符分割，candidate 候选组件，auto 自动选择；默认 auto",
    )
    parser.add_argument("--expected-len", type=int, default=0, help="验证码固定长度，例如 4；默认不强制")
    return parser.parse_args()


def main():
    args = parse_args()
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        print(f"图片不存在: {image_path}", file=sys.stderr)
        return 2

    numeric_only = not args.keep_alnum
    try:
        if args.engine == "ddddocr":
            ocr = build_ddddocr()
            raw = recognize_whole_image(ocr, image_path)
            whole = normalize_result(raw, numeric_only=numeric_only)
            if args.mode == "whole":
                result = whole
            else:
                segmented, _ = recognize_segmented_image(ocr, image_path, numeric_only=numeric_only)
                candidate, _ = recognize_candidate_image(ocr, image_path, expected_len=args.expected_len or 4)
                fallbacks = []
                if args.mode == "auto" and args.expected_len:
                    fallbacks = recognize_whole_fallbacks(
                        ocr,
                        image_path,
                        numeric_only=numeric_only,
                        beta_ocr=build_ddddocr(beta=True),
                    )
                if args.mode == "segment":
                    result = segmented
                elif args.mode == "candidate":
                    result = candidate
                else:
                    result = choose_result(whole, segmented, candidate=candidate, expected_len=args.expected_len, fallbacks=fallbacks)
        else:
            raw = recognize_with_tesseract(image_path, numeric_only=numeric_only)
            result = normalize_result(raw, numeric_only=numeric_only)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not result:
        print(f"未识别到有效字符，原始输出: {raw!r}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import csv
import http.cookiejar
import sys
import time
from pathlib import Path

from recognize_captcha import (
    build_ddddocr,
    choose_result,
    normalize_result,
    recognize_whole_fallbacks,
    recognize_candidate_image,
    recognize_segmented_image,
    recognize_whole_image,
)
from sp import build_opener, load_cookie_string, looks_like_cloudflare_block, request, save_captcha


LOGIN_URL = "https://south-plus.org/login.php"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("captcha_samples")
FIXED_CAPTCHA_LEN = 4


def build_ocr():
    return build_ddddocr()


def recognize_image(ocr, image_path, numeric_only=True, expected_len=FIXED_CAPTCHA_LEN, beta_ocr=None, cnn_model=None, cnn_meta=None):
    raw_whole = recognize_whole_image(ocr, image_path)
    whole = normalize_result(raw_whole, numeric_only=numeric_only)
    segmented, boxes = recognize_segmented_image(ocr, image_path, numeric_only=numeric_only)
    candidate, candidates = recognize_candidate_image(ocr, image_path, expected_len=expected_len or 4)
    fallbacks = []
    if expected_len:
        fallbacks = recognize_whole_fallbacks(ocr, image_path, numeric_only=numeric_only, beta_ocr=beta_ocr)
    result = choose_result(whole, segmented, candidate=candidate, expected_len=expected_len, fallbacks=fallbacks)
    cnn = ""
    if (
        expected_len == FIXED_CAPTCHA_LEN
        and len(result) != expected_len
        and cnn_model is not None
        and cnn_meta is not None
    ):
        from cnn_captcha import recognize_image_with_cnn

        cnn, _ = recognize_image_with_cnn(image_path, model=cnn_model, meta=cnn_meta)
        if len(cnn) == FIXED_CAPTCHA_LEN:
            result = cnn
    return raw_whole, whole, segmented, candidate, cnn, result, boxes, candidates


def create_contact_sheet(rows, output_dir):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    image_rows = [row for row in rows if (output_dir / row["file"]).exists()]
    if not image_rows:
        return None

    thumb_w, thumb_h = 150, 60
    label_h = 22
    cols = 5
    row_count = (len(image_rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, row_count * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/SFNSMono.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for offset, row in enumerate(image_rows):
        grid_y, grid_x = divmod(offset, cols)
        x = grid_x * thumb_w
        y = grid_y * (thumb_h + label_h)
        image = Image.open(output_dir / row["file"]).convert("RGB").resize((thumb_w, thumb_h))
        sheet.paste(image, (x, y))
        label = (
            f"{int(row['index']):02d}: {row['result'] or 'EMPTY'} "
            f"w:{row.get('whole', '')} s:{row.get('segment', '')} c:{row.get('candidate', '')}"
        )
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=(245, 245, 245))
        draw.text((x + 4, y + thumb_h + 4), label, fill=(0, 0, 0), font=font)

    sheet_path = output_dir / "contact_sheet.jpg"
    sheet.save(sheet_path, quality=95)
    return sheet_path


def parse_args():
    parser = argparse.ArgumentParser(description="批量下载 South Plus 验证码，并运行本地 OCR 脚本识别。")
    parser.add_argument("-n", "--count", type=int, default=50, help="下载数量，默认 50")
    parser.add_argument("--start-index", type=int, default=1, help="保存文件起始编号，默认 1")
    parser.add_argument("-o", "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="验证码保存目录")
    parser.add_argument("--results-file", help="结果 CSV 路径；不传则自动选择")
    parser.add_argument("--reuse-existing", action="store_true", help="复用目录中已有的 captcha_*.jpg，不重新下载")
    parser.add_argument("--download-only", action="store_true", help="只下载验证码图片，不运行 OCR")
    parser.add_argument("--cookie", help="可选，浏览器复制的 Cookie 字符串，例如 cf_clearance=...")
    parser.add_argument("--proxy", help="可选代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--ca-file", help="可选，自定义 CA 证书文件路径")
    parser.add_argument("--insecure", action="store_true", help="临时关闭 TLS 证书校验，仅用于本地调试")
    parser.add_argument("--delay", type=float, default=0.3, help="每次下载后的暂停秒数，默认 0.3")
    parser.add_argument(
        "--keep-alnum",
        action="store_true",
        help="保留英文和数字；默认只保留数字，适合 South Plus 这类数字验证码",
    )
    parser.add_argument("--expected-len", type=int, default=FIXED_CAPTCHA_LEN, help="验证码固定长度，默认 4；传 0 则不强制")
    parser.add_argument("--no-cnn-fallback", action="store_true", help="不使用已训练 CNN 模型做槽位补位")
    parser.add_argument("--cnn-model", default="southplus/captcha_char_cnn.pt", help="CNN 模型路径")
    parser.add_argument("--cnn-meta", default="southplus/captcha_char_cnn_meta.json", help="CNN 元数据路径")
    parser.add_argument("--no-contact-sheet", action="store_true", help="不生成带识别结果的拼图")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.count <= 0:
        print("下载数量必须大于 0", file=sys.stderr)
        return 2
    if args.start_index <= 0:
        print("起始编号必须大于 0", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    end_index = args.start_index + args.count - 1
    if args.results_file:
        csv_path = Path(args.results_file).expanduser().resolve()
    elif args.download_only:
        csv_path = output_dir / f"downloads_{args.start_index:03d}_{end_index:03d}.csv"
    else:
        csv_path = output_dir / "results.csv"

    opener = None
    if not args.reuse_existing:
        cookie_jar = http.cookiejar.CookieJar()
        load_cookie_string(cookie_jar, args.cookie)
        opener = build_opener(cookie_jar, args)

        status, headers, body = request(opener, LOGIN_URL)
        if looks_like_cloudflare_block(status, headers, body):
            print("登录页可能被 Cloudflare 拦截，请从浏览器复制 cf_clearance 后用 --cookie 传入。", file=sys.stderr)
            print(f"HTTP 状态: {status}", file=sys.stderr)
            return 2
        if status != 200:
            print(f"登录页请求失败: HTTP {status}", file=sys.stderr)
            return 2

    ocr = None
    beta_ocr = None
    cnn_model = None
    cnn_meta = None
    if not args.download_only:
        try:
            ocr = build_ocr()
            beta_ocr = build_ddddocr(beta=True) if args.expected_len else None
            if args.expected_len and not args.no_cnn_fallback:
                try:
                    from cnn_captcha import load_char_cnn

                    cnn_model, cnn_meta = load_char_cnn(args.cnn_model, args.cnn_meta)
                except Exception as exc:
                    print(f"CNN 补位未启用: {exc}", file=sys.stderr)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    rows = []
    numeric_only = not args.keep_alnum
    if args.reuse_existing:
        image_paths = sorted(output_dir.glob("captcha_*.jpg"))[: args.count]
        if not image_paths:
            print(f"目录中没有 captcha_*.jpg: {output_dir}", file=sys.stderr)
            return 2
        indexed_paths = [(args.start_index + offset, image_path) for offset, image_path in enumerate(image_paths)]
    else:
        indexed_paths = [
            (file_index, output_dir / f"captcha_{file_index:03d}.jpg")
            for file_index in range(args.start_index, args.start_index + args.count)
        ]

    total = len(indexed_paths)
    for progress, (file_index, image_path) in enumerate(indexed_paths, 1):
        try:
            if args.reuse_existing:
                captcha_url = ""
                content_type = ""
                size = image_path.stat().st_size
            else:
                captcha_url, content_type, size = save_captcha(opener, str(image_path))
            if args.download_only:
                rows.append(
                    {
                        "index": file_index,
                        "file": image_path.name,
                        "result": "",
                        "whole": "",
                        "segment": "",
                        "candidate": "",
                        "cnn": "",
                        "raw": "",
                        "boxes": "",
                        "candidates": "",
                        "ok": "1",
                        "content_type": content_type,
                        "size": size,
                        "url": captcha_url,
                    }
                )
                print(f"[{progress:03d}/{total:03d}] {image_path.name} 下载完成 ({size} bytes)")
                if args.delay > 0 and progress < total and not args.reuse_existing:
                    time.sleep(args.delay)
                continue
            raw, whole, segmented, candidate, cnn, result, boxes, candidates = recognize_image(
                ocr,
                image_path,
                numeric_only=numeric_only,
                expected_len=args.expected_len,
                beta_ocr=beta_ocr,
                cnn_model=cnn_model,
                cnn_meta=cnn_meta,
            )
            ok = bool(result)
            rows.append(
                {
                    "index": file_index,
                    "file": image_path.name,
                    "result": result,
                    "whole": whole,
                    "segment": segmented,
                    "candidate": candidate,
                    "cnn": cnn,
                    "raw": raw,
                    "boxes": len(boxes),
                    "candidates": len(candidates),
                    "ok": "1" if ok else "0",
                    "content_type": content_type,
                    "size": size,
                    "url": captcha_url,
                }
            )
            print(
                f"[{progress:03d}/{total:03d}] {image_path.name} -> {result or '(空)'} "
                f"(whole={whole or '-'}, segment={segmented or '-'}, candidate={candidate or '-'})"
            )
        except Exception as exc:
            rows.append(
                {
                    "index": file_index,
                    "file": image_path.name,
                    "result": "",
                    "whole": "",
                    "segment": "",
                    "candidate": "",
                    "cnn": "",
                    "raw": "",
                    "boxes": "",
                    "candidates": "",
                    "ok": "0",
                    "content_type": "",
                    "size": "",
                    "url": "",
                    "error": str(exc),
                }
            )
            print(f"[{progress:03d}/{total:03d}] 下载或识别失败: {exc}", file=sys.stderr)
        if args.delay > 0 and progress < total and not args.reuse_existing:
            time.sleep(args.delay)

    fieldnames = [
        "index",
        "file",
        "result",
        "whole",
        "segment",
        "candidate",
        "cnn",
        "raw",
        "boxes",
        "candidates",
        "ok",
        "content_type",
        "size",
        "url",
        "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sheet_path = None
    if not args.no_contact_sheet and not args.download_only:
        sheet_path = create_contact_sheet(rows, output_dir)

    success_count = sum(1 for row in rows if row.get("ok") == "1")
    if args.download_only:
        print(f"完成: {success_count}/{total} 张下载成功")
    else:
        print(f"完成: {success_count}/{total} 张识别出非空结果")
    print(f"图片目录: {output_dir}")
    print(f"结果文件: {csv_path}")
    if sheet_path:
        print(f"复核拼图: {sheet_path}")
    return 0 if success_count == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

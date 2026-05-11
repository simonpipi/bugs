#!/usr/bin/env python3
import argparse
import csv
import http.cookiejar
import sys
import time
from pathlib import Path

from cnn_captcha import META_PATH, MODEL_PATH, load_char_cnn, recognize_image_with_cnn
from sp import build_opener, load_cookie_string, looks_like_cloudflare_block, request, save_captcha


LOGIN_URL = "https://south-plus.org/login.php"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("captcha_samples")


def create_contact_sheet(rows, output_dir):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    image_rows = [row for row in rows if row.get("ok") == "1" and (output_dir / row["file"]).exists()]
    if not image_rows:
        return None

    thumb_w, thumb_h = 150, 60
    label_h = 24
    cols = 5
    row_count = (len(image_rows) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, row_count * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/SFNSMono.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for offset, row in enumerate(image_rows):
        grid_y, grid_x = divmod(offset, cols)
        x = grid_x * thumb_w
        y = grid_y * (thumb_h + label_h)
        image = Image.open(output_dir / row["file"]).convert("RGB").resize((thumb_w, thumb_h))
        sheet.paste(image, (x, y))
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=(245, 245, 245))
        draw.text((x + 4, y + thumb_h + 5), f"{int(row['index']):02d}: {row['result']}", fill=(0, 0, 0), font=font)

    sheet_path = output_dir / "contact_sheet.jpg"
    sheet.save(sheet_path, quality=95)
    return sheet_path


def parse_args():
    parser = argparse.ArgumentParser(description="批量下载 South Plus 验证码，并使用当前 CNN 算法识别。")
    parser.add_argument("-n", "--count", type=int, default=50, help="下载数量，默认 50")
    parser.add_argument("--start-index", type=int, default=1, help="保存文件起始编号，默认 1")
    parser.add_argument("-o", "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="验证码保存目录")
    parser.add_argument("--results-file", help="结果 CSV 路径；不传则自动选择")
    parser.add_argument("--reuse-existing", action="store_true", help="复用目录中已有的 captcha_*.jpg，不重新下载")
    parser.add_argument("--download-only", action="store_true", help="只下载验证码图片，不运行 CNN 识别")
    parser.add_argument("--cookie", help="可选，浏览器复制的 Cookie 字符串，例如 cf_clearance=...")
    parser.add_argument("--proxy", help="可选代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--ca-file", help="可选，自定义 CA 证书文件路径")
    parser.add_argument("--insecure", action="store_true", help="临时关闭 TLS 证书校验，仅用于本地调试")
    parser.add_argument("--delay", type=float, default=0.3, help="每次下载后的暂停秒数，默认 0.3")
    parser.add_argument("--cnn-model", default=str(MODEL_PATH), help="CNN 模型路径")
    parser.add_argument("--cnn-meta", default=str(META_PATH), help="CNN 元数据路径")
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

    model = None
    meta = None
    if not args.download_only:
        model, meta = load_char_cnn(
            model_path=Path(args.cnn_model).expanduser().resolve(),
            meta_path=Path(args.cnn_meta).expanduser().resolve(),
        )

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

    rows = []
    total = len(indexed_paths)
    for progress, (file_index, image_path) in enumerate(indexed_paths, 1):
        try:
            if args.reuse_existing:
                captcha_url = ""
                content_type = ""
                size = image_path.stat().st_size
            else:
                captcha_url, content_type, size = save_captcha(opener, str(image_path))

            result = ""
            debug_text = ""
            if not args.download_only:
                result, debug = recognize_image_with_cnn(image_path, model=model, meta=meta)
                debug_text = "|".join(
                    f"{item['digit']}:{item['source']}:{item['score']:.3f}:{item['box']}"
                    for item in debug
                )

            rows.append(
                {
                    "index": file_index,
                    "file": image_path.name,
                    "result": result,
                    "debug": debug_text,
                    "ok": "1",
                    "content_type": content_type,
                    "size": size,
                    "url": captcha_url,
                    "error": "",
                }
            )
            if args.download_only:
                print(f"[{progress:03d}/{total:03d}] {image_path.name} 下载完成 ({size} bytes)")
            else:
                print(f"[{progress:03d}/{total:03d}] {image_path.name} -> {result}")
        except Exception as exc:
            rows.append(
                {
                    "index": file_index,
                    "file": image_path.name,
                    "result": "",
                    "debug": "",
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

    fieldnames = ["index", "file", "result", "debug", "ok", "content_type", "size", "url", "error"]
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sheet_path = None
    if not args.no_contact_sheet and not args.download_only:
        sheet_path = create_contact_sheet(rows, output_dir)

    success_count = sum(1 for row in rows if row.get("ok") == "1")
    print(f"完成: {success_count}/{total}")
    print(f"图片目录: {output_dir}")
    print(f"结果文件: {csv_path}")
    if sheet_path:
        print(f"复核拼图: {sheet_path}")
    return 0 if success_count == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

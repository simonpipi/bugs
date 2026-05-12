#!/usr/bin/env python3
import argparse
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from moxing_login import DEFAULT_HEADERS, load_cookies


BASE_URL = "https://moxing.lol/"
THREAD_URL = "https://moxing.lol/thread-737144-1-1.html"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_COOKIE_FILE = SCRIPT_DIR / "moxing_cookies.json"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "captchas"


class CaptchaDownloadError(RuntimeError):
    pass


def build_session(cookie_file: Path) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update({"Connection": "close"})
    load_cookies(session, cookie_file)
    return session


def ensure_entered_site(session: requests.Session, timeout: int) -> None:
    session.get(urljoin(BASE_URL, "?is_agree=1"), timeout=timeout)


def fetch_thread_html(session: requests.Session, thread_url: str, timeout: int) -> str:
    response = request_with_retry(
        session,
        thread_url,
        headers={"Referer": BASE_URL},
        timeout=timeout,
    )
    if "I am" in response.text and "21 years old" in response.text:
        raise CaptchaDownloadError("请求仍停留在年龄确认页，Cookie/同意状态未生效")
    return response.text


def extract_idhash(thread_html: str) -> str:
    match = re.search(r"updateseccode\('([^']+)'", thread_html)
    if not match:
        raise CaptchaDownloadError("未在目标页面找到 updateseccode(...) 验证码入口")
    return match.group(1)


def fetch_captcha_image_url(
    session: requests.Session,
    idhash: str,
    referer: str,
    timeout: int,
) -> str:
    update_url = urljoin(
        BASE_URL,
        (
            "misc.php?mod=seccode"
            f"&action=update&idhash={idhash}"
            f"&{random.random()}"
            "&modid=forum::viewthread"
        ),
    )
    response = request_with_retry(
        session,
        update_url,
        headers={"Referer": referer, "Accept": "application/javascript,*/*;q=0.8"},
        timeout=timeout,
    )
    if "Access Denied" in response.text:
        raise CaptchaDownloadError("验证码更新接口返回 Access Denied，idhash 可能已过期")

    match = re.search(r"misc\.php\?mod=seccode[^'\"<>\\]+", response.text)
    if not match:
        raise CaptchaDownloadError("验证码更新脚本中未找到图片地址")

    return urljoin(BASE_URL, match.group(0).replace("&amp;", "&"))


def download_image(
    session: requests.Session,
    image_url: str,
    referer: str,
    timeout: int,
) -> bytes:
    response = request_with_retry(
        session,
        image_url,
        headers={"Referer": referer, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        timeout=timeout,
    )
    content_type = response.headers.get("content-type", "")
    if "image/" not in content_type:
        body = response.text[:120].replace("\n", " ")
        raise CaptchaDownloadError(f"验证码图片接口未返回图片: {content_type} {body!r}")
    return response.content


def request_with_retry(
    session: requests.Session,
    url: str,
    *,
    headers: dict,
    timeout: int,
    retries: int = 4,
    delay: float = 0.8,
) -> requests.Response:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(delay * attempt)
    raise CaptchaDownloadError(f"请求失败: {url} ({last_error})")


def save_captchas(
    *,
    cookie_file: Path,
    output_dir: Path,
    count: int,
    thread_url: str,
    timeout: int,
    delay: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session(cookie_file)
    ensure_entered_site(session, timeout)

    thread_html = fetch_thread_html(session, thread_url, timeout)
    idhash = extract_idhash(thread_html)
    print(f"使用 idhash: {idhash}")

    saved = 0
    for index in range(1, count + 1):
        try:
            image_url = fetch_captcha_image_url(session, idhash, thread_url, timeout)
            image = download_image(session, image_url, thread_url, timeout)
        except CaptchaDownloadError:
            thread_html = fetch_thread_html(session, thread_url, timeout)
            idhash = extract_idhash(thread_html)
            image_url = fetch_captcha_image_url(session, idhash, thread_url, timeout)
            image = download_image(session, image_url, thread_url, timeout)

        path = output_dir / f"captcha_{index:03d}.gif"
        path.write_bytes(image)
        saved += 1
        print(f"[{saved:02d}/{count}] {path.name} {len(image)} bytes")
        if delay > 0 and index < count:
            time.sleep(delay)

    print(f"完成，已保存 {saved} 张验证码到: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 moxing.lol 帖子页 Discuz 验证码图片")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE), help="Cookie JSON 文件路径")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="验证码保存目录")
    parser.add_argument("--count", type=int, default=50, help="下载数量")
    parser.add_argument("--thread-url", default=THREAD_URL, help="触发验证码的帖子 URL")
    parser.add_argument("--timeout", type=int, default=20, help="请求超时时间")
    parser.add_argument("--delay", type=float, default=0.3, help="每张验证码之间的间隔秒数")
    args = parser.parse_args()

    try:
        save_captchas(
            cookie_file=Path(args.cookie_file).expanduser(),
            output_dir=Path(args.output_dir).expanduser(),
            count=args.count,
            thread_url=args.thread_url,
            timeout=args.timeout,
            delay=args.delay,
        )
    except Exception as exc:
        print(f"下载失败: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie
from pathlib import Path

from cnn_captcha import META_PATH, MODEL_PATH, load_char_cnn, recognize_image_with_cnn


BASE_URL = "https://south-plus.org"
LOGIN_URL = f"{BASE_URL}/login.php"
DEFAULT_CONFIG = Path(__file__).with_name("sp_config.json")


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) "
        "Gecko/20100101 Firefox/135.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.5",
    "Origin": BASE_URL,
    "Referer": LOGIN_URL,
    "Upgrade-Insecure-Requests": "1",
}


def make_cookie(name, value, domain="south-plus.org"):
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None},
        rfc2109=False,
    )


def load_cookie_string(cookie_jar, cookie_string):
    if not cookie_string:
        return
    for item in cookie_string.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if not name:
            continue
        domain = ".south-plus.org" if name == "cf_clearance" else "south-plus.org"
        cookie_jar.set_cookie(make_cookie(name, value, domain=domain))


def build_ssl_context(args):
    if args.insecure:
        return ssl._create_unverified_context()
    if args.ca_file:
        return ssl.create_default_context(cafile=args.ca_file)
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def build_opener(cookie_jar, args):
    handlers = [urllib.request.HTTPCookieProcessor(cookie_jar)]
    handlers.append(urllib.request.HTTPSHandler(context=build_ssl_context(args)))
    if args.proxy:
        handlers.append(urllib.request.ProxyHandler({"http": args.proxy, "https": args.proxy}))
    return urllib.request.build_opener(*handlers)


def request(opener, url, method="GET", data=None, headers=None):
    merged_headers = dict(HEADERS)
    if headers:
        merged_headers.update(headers)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        merged_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=merged_headers, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.getcode(), resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise RuntimeError(
                "TLS 证书校验失败。可先安装 certifi，或使用 --ca-file 指定 CA；"
                "如只是本地调试，可临时加 --insecure。"
            ) from exc
        raise


def looks_like_cloudflare_block(status, headers, body):
    text = body[:4000].decode("utf-8", errors="ignore").lower()
    header_keys = {k.lower() for k in headers.keys()}
    return (
        status in {403, 503}
        or "cf-mitigated" in header_keys
        or "just a moment" in text
        or "checking your browser" in text
        or "enable javascript and cookies" in text
    )


def save_captcha(opener, output_path):
    nowtime = int(time.time() * 1000)
    captcha_url = f"{BASE_URL}/ck.php?nowtime={nowtime}"
    headers = {
        "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
        "Referer": LOGIN_URL,
    }
    status, resp_headers, body = request(opener, captcha_url, headers=headers)
    if status != 200:
        raise RuntimeError(f"验证码请求失败: HTTP {status}")
    if not body:
        raise RuntimeError("验证码响应为空")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as fp:
        fp.write(body)
    return captcha_url, resp_headers.get("content-type", ""), len(body)


def submit_login(opener, args, gdcode):
    form = {
        "forward": "",
        "jumpurl": args.jumpurl,
        "step": "2",
        "gdcode": gdcode,
        "lgt": str(args.lgt),
        "pwuser": args.user,
        "pwpwd": args.password,
        "hideid": str(args.hideid),
        "cktime": str(args.cktime),
    }
    status, headers, body = request(opener, f"{LOGIN_URL}?", method="POST", data=form)
    html = body.decode("utf-8", errors="ignore")
    return status, headers, html


def load_config(path):
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with config_path.open(encoding="utf-8") as fp:
        config = json.load(fp)
    if not isinstance(config, dict):
        raise ValueError("配置文件根节点必须是 JSON object")
    return config, config_path


def config_get(config, *keys, default=None):
    current = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def apply_config(args, config):
    args.user = config_get(config, "account", "user") or config_get(config, "user")
    args.password = config_get(config, "account", "password") or config_get(config, "password")
    args.cookie = args.cookie if args.cookie is not None else config_get(config, "request", "cookie")
    args.proxy = args.proxy if args.proxy is not None else config_get(config, "request", "proxy")
    args.ca_file = args.ca_file if args.ca_file is not None else config_get(config, "request", "ca_file")
    args.insecure = bool(args.insecure or config_get(config, "request", "insecure", default=False))
    args.captcha_output = args.captcha_output or config_get(config, "captcha", "output", default="southplus/captcha.jpg")
    args.cnn_model = args.cnn_model or config_get(config, "captcha", "model", default=str(MODEL_PATH))
    args.cnn_meta = args.cnn_meta or config_get(config, "captcha", "meta", default=str(META_PATH))
    args.max_attempts = int(args.max_attempts if args.max_attempts is not None else config_get(config, "login", "max_attempts", default=5))
    args.retry_delay = float(args.retry_delay if args.retry_delay is not None else config_get(config, "login", "retry_delay", default=0.5))
    args.jumpurl = args.jumpurl or config_get(config, "login", "jumpurl", default="//south-plus.org/index.php")
    args.lgt = str(args.lgt or config_get(config, "login", "lgt", default="0"))
    args.hideid = str(args.hideid or config_get(config, "login", "hideid", default="0"))
    args.cktime = str(args.cktime or config_get(config, "login", "cktime", default="31536000"))
    args.save_html = args.save_html or config_get(config, "login", "save_html", default="southplus/login_result.html")
    return args


def extract_title(html):
    lower = html.lower()
    start = lower.find("<title>")
    end = lower.find("</title>", start)
    if start == -1 or end == -1:
        return ""
    return html[start + len("<title>") : end].strip()


def print_cookie_summary(cookie_jar):
    names = [cookie.name for cookie in cookie_jar]
    print("当前 Cookie:", ", ".join(names) if names else "(空)")


def detect_login_result(status, headers, html):
    if status in {301, 302, 303, 307, 308} and "login.php" not in headers.get("location", ""):
        return "success"
    if "认证码不正确或已过期" in html:
        return "captcha_error"
    if "用户名或密码错误" in html or "密码错误" in html:
        return "password_error"
    if "登录成功" in html or "顺利登录" in html:
        return "success"
    if "login.php" not in headers.get("location", "") and ("退出" in html or "用户中心" in html):
        return "success"
    return "unknown"


def save_login_html(path, html):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(html)


def recognize_captcha(image_path, model, meta):
    result, debug = recognize_image_with_cnn(image_path, model=model, meta=meta)
    debug_text = "|".join(
        f"{item['digit']}:{item['source']}:{item['score']:.3f}:{item['box']}"
        for item in debug
    )
    return result, debug_text


def validate_args(args):
    if not args.user or not args.password:
        raise ValueError("配置文件必须提供 account.user 和 account.password")
    if args.max_attempts < 0:
        raise ValueError("max_attempts 不能小于 0；如需不限次数请设置为 0")
    if args.lgt not in {"0", "1", "2"}:
        raise ValueError("login.lgt 必须是 0、1 或 2")
    if args.hideid not in {"0", "1"}:
        raise ValueError("login.hideid 必须是 0 或 1")
    if args.cktime not in {"31536000", "2592000", "86400", "3600", "0"}:
        raise ValueError("login.cktime 不在允许值范围内")


def parse_args():
    parser = argparse.ArgumentParser(
        description="South Plus 登录纯协议脚本：读取配置，自动识别验证码并按配置重试登录。"
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="登录配置 JSON 路径")
    parser.add_argument(
        "-c",
        "--cookie",
        help="可选，覆盖配置中的 Cookie 字符串，例如 'cf_clearance=...; eb9e6_lastvisit=...'",
    )
    parser.add_argument("--proxy", help="可选，覆盖配置中的代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--ca-file", help="可选，覆盖配置中的自定义 CA 证书文件路径")
    parser.add_argument("--insecure", action="store_true", help="覆盖配置，临时关闭 TLS 证书校验，仅用于本地调试")
    parser.add_argument("--captcha-output", help="验证码保存路径")
    parser.add_argument("--cnn-model", help="CNN 模型路径")
    parser.add_argument("--cnn-meta", help="CNN 元数据路径")
    parser.add_argument("--max-attempts", type=int, help="最大登录尝试次数；0 表示不限制")
    parser.add_argument("--retry-delay", type=float, help="登录失败后重试间隔秒数")
    parser.add_argument("--jumpurl")
    parser.add_argument("--lgt", choices=["0", "1", "2"], help="0 用户名，1 UID，2 Email")
    parser.add_argument("--hideid", choices=["0", "1"], help="0 不隐身，1 隐身")
    parser.add_argument(
        "--cktime",
        choices=["31536000", "2592000", "86400", "3600", "0"],
        help="登录 Cookie 有效期",
    )
    parser.add_argument("--save-html", help="保存登录响应 HTML")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        config, config_path = load_config(args.config)
        args = apply_config(args, config)
    except Exception as exc:
        print(f"读取配置失败: {exc}", file=sys.stderr)
        return 2

    try:
        validate_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cookie_jar = http.cookiejar.CookieJar()
    load_cookie_string(cookie_jar, args.cookie)
    opener = build_opener(cookie_jar, args)

    print(f"配置文件: {config_path}")
    print("[1/3] 请求登录页，建立会话")
    status, headers, body = request(opener, LOGIN_URL)
    if looks_like_cloudflare_block(status, headers, body):
        print("登录页可能被 Cloudflare 拦截。请从浏览器复制 cf_clearance 后用 --cookie 传入。")
        print(f"HTTP 状态: {status}")
        return 2
    if status != 200:
        print(f"登录页请求失败: HTTP {status}")
        return 2
    print_cookie_summary(cookie_jar)

    print("[2/3] 加载验证码识别模型")
    model, meta = load_char_cnn(
        model_path=Path(args.cnn_model).expanduser().resolve(),
        meta_path=Path(args.cnn_meta).expanduser().resolve(),
    )

    attempt = 0
    while args.max_attempts == 0 or attempt < args.max_attempts:
        attempt += 1
        total_text = "不限" if args.max_attempts == 0 else str(args.max_attempts)
        print(f"[3/3] 第 {attempt}/{total_text} 次获取验证码并提交登录")
        try:
            captcha_url, content_type, size = save_captcha(opener, args.captcha_output)
            gdcode, debug_text = recognize_captcha(Path(args.captcha_output).expanduser().resolve(), model, meta)
            if not gdcode:
                print("验证码识别为空，准备重试")
                continue
            print(f"验证码 URL: {captcha_url}")
            print(f"验证码已保存: {os.path.abspath(args.captcha_output)} ({content_type}, {size} bytes)")
            print(f"识别结果: {gdcode}")
            print(f"识别调试: {debug_text}")

            status, headers, html = submit_login(opener, args, gdcode)
            save_login_html(args.save_html, html)
            title = extract_title(html)
            result = detect_login_result(status, headers, html)
            print(f"HTTP 状态: {status}")
            print(f"响应标题: {title or '(未提取到 title)'}")
            print(f"响应 HTML: {os.path.abspath(args.save_html)}")
            print_cookie_summary(cookie_jar)
        except Exception as exc:
            print(f"本次登录尝试失败: {exc}")
            result = "unknown"

        if result == "success":
            print("结果: 登录成功。")
            return 0
        if result == "password_error":
            print("结果: 账号或密码错误，停止重试。")
            return 1
        if result == "captcha_error":
            print("结果: 验证码错误或已过期，准备获取新验证码重试。")
        else:
            print("结果: 未确认登录成功，准备重试。")
        if args.retry_delay > 0:
            time.sleep(args.retry_delay)

    print("结果: 达到最大登录尝试次数，仍未登录成功。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

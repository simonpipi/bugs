#!/usr/bin/env python3
import argparse
import getpass
import http.cookiejar
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie


BASE_URL = "https://south-plus.org"
LOGIN_URL = f"{BASE_URL}/login.php"


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


def parse_args():
    parser = argparse.ArgumentParser(
        description="South Plus 登录纯协议脚本：获取验证码图片，人工输入验证码后提交登录。"
    )
    parser.add_argument("-u", "--user", help="用户名 / UID / Email")
    parser.add_argument("-p", "--password", help="密码；不传则交互输入")
    parser.add_argument(
        "-c",
        "--cookie",
        help="可选，浏览器复制的 Cookie 字符串，例如 'cf_clearance=...; eb9e6_lastvisit=...'",
    )
    parser.add_argument("--proxy", help="可选代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--ca-file", help="可选，自定义 CA 证书文件路径")
    parser.add_argument("--insecure", action="store_true", help="临时关闭 TLS 证书校验，仅用于本地调试")
    parser.add_argument("--captcha-output", default="southplus/captcha.jpg", help="验证码保存路径")
    parser.add_argument("--jumpurl", default="//south-plus.org/index.php")
    parser.add_argument("--lgt", choices=["0", "1", "2"], default="0", help="0 用户名，1 UID，2 Email")
    parser.add_argument("--hideid", choices=["0", "1"], default="0", help="0 不隐身，1 隐身")
    parser.add_argument(
        "--cktime",
        choices=["31536000", "2592000", "86400", "3600", "0"],
        default="31536000",
        help="登录 Cookie 有效期",
    )
    parser.add_argument("--save-html", default="southplus/login_result.html", help="保存登录响应 HTML")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.user:
        args.user = input("账号: ").strip()
    if not args.password:
        args.password = getpass.getpass("密码: ")

    cookie_jar = http.cookiejar.CookieJar()
    load_cookie_string(cookie_jar, args.cookie)
    opener = build_opener(cookie_jar, args)

    print("[1/4] 请求登录页，建立会话")
    status, headers, body = request(opener, LOGIN_URL)
    if looks_like_cloudflare_block(status, headers, body):
        print("登录页可能被 Cloudflare 拦截。请从浏览器复制 cf_clearance 后用 --cookie 传入。")
        print(f"HTTP 状态: {status}")
        return 2
    if status != 200:
        print(f"登录页请求失败: HTTP {status}")
        return 2
    print_cookie_summary(cookie_jar)

    print("[2/4] 获取验证码图片")
    captcha_url, content_type, size = save_captcha(opener, args.captcha_output)
    print(f"验证码 URL: {captcha_url}")
    print(f"验证码已保存: {os.path.abspath(args.captcha_output)} ({content_type}, {size} bytes)")
    print_cookie_summary(cookie_jar)

    gdcode = input("[3/4] 打开验证码图片并输入验证码: ").strip()
    if not gdcode:
        print("验证码不能为空")
        return 2

    print("[4/4] 提交登录表单")
    status, headers, html = submit_login(opener, args, gdcode)
    os.makedirs(os.path.dirname(os.path.abspath(args.save_html)), exist_ok=True)
    with open(args.save_html, "w", encoding="utf-8") as fp:
        fp.write(html)

    title = extract_title(html)
    print(f"HTTP 状态: {status}")
    print(f"响应标题: {title or '(未提取到 title)'}")
    print(f"响应 HTML: {os.path.abspath(args.save_html)}")
    print_cookie_summary(cookie_jar)

    if "认证码不正确或已过期" in html:
        print("结果: 验证码错误或已过期。需要重新运行脚本获取新的验证码。")
        return 1
    if "用户名或密码错误" in html or "密码错误" in html:
        print("结果: 验证码已通过，但账号或密码错误。")
        return 1
    if "login.php" not in headers.get("location", "") and ("退出" in html or "用户中心" in html):
        print("结果: 可能登录成功，请检查响应 HTML 和 Cookie。")
        return 0
    print("结果: 已提交，请根据响应标题和保存的 HTML 判断是否成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

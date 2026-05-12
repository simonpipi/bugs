#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests


BASE_URL = "https://moxing.lol/"
LOGIN_URL = urljoin(BASE_URL, "member.php?mod=logging&action=login")
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "moxing_config.json"


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class LoginParseError(RuntimeError):
    pass


class LoginError(RuntimeError):
    pass


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def add_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        query[key] = [value]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def extract_first(pattern: str, text: str, name: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        raise LoginParseError(f"未能从登录页提取 {name}")
    return match.group(1)


def parse_login_form(html: str) -> Dict[str, str]:
    form_match = re.search(
        r'<form[^>]+id="loginform_[^"]+"[^>]+action="([^"]+)"[^>]*>(.*?)</form>',
        html,
        re.I | re.S,
    )
    if not form_match:
        raise LoginParseError("未找到登录表单，可能触发了验证页或页面结构变化")

    action = form_match.group(1).replace("&amp;", "&")
    form_html = form_match.group(2)
    formhash = extract_first(
        r'name=["\']formhash["\'][^>]+value=["\']([^"\']+)["\']',
        form_html,
        "formhash",
    )
    referer_match = re.search(
        r'name=["\']referer["\'][^>]+value=["\']([^"\']*)["\']',
        form_html,
        re.I | re.S,
    )

    return {
        "action": urljoin(BASE_URL, action),
        "formhash": formhash,
        "referer": referer_match.group(1) if referer_match else urljoin(BASE_URL, "./"),
    }


def dump_cookies(session: requests.Session, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for cookie in session.cookies:
        data.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "secure": cookie.secure,
            }
        )
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cookies(session: requests.Session, path: Path) -> None:
    if not path.exists():
        return

    for item in json.loads(path.read_text(encoding="utf-8")):
        cookie = Cookie(
            version=0,
            name=item["name"],
            value=item["value"],
            port=None,
            port_specified=False,
            domain=item.get("domain") or ".moxing.lol",
            domain_specified=True,
            domain_initial_dot=(item.get("domain") or "").startswith("."),
            path=item.get("path") or "/",
            path_specified=True,
            secure=bool(item.get("secure")),
            expires=item.get("expires"),
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        session.cookies.set_cookie(cookie)


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("username", "password"):
        if not config.get(key):
            raise LoginError(f"配置文件缺少必填字段: {key}")
    return config


def resolve_config_path(path: str) -> Path:
    config_path = Path(path).expanduser()
    return config_path if config_path.is_absolute() else (Path.cwd() / config_path)


def resolve_config_relative_path(value: str, config_path: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (config_path.parent / path)


def is_login_success(text: str, session: requests.Session) -> bool:
    if any(cookie.name.endswith("_auth") for cookie in session.cookies):
        return True
    return "欢迎您回来" in text or "succeedhandle_" in text


def login(
    username: str,
    password: str,
    *,
    loginfield: str = "username",
    password_is_md5: bool = False,
    auto_login: bool = False,
    questionid: str = "0",
    answer: str = "",
    cookie_file: Optional[Path] = None,
    load_cookie_file: bool = False,
    timeout: int = 20,
) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    if cookie_file and load_cookie_file:
        load_cookies(session, cookie_file)

    page = session.get(LOGIN_URL, timeout=timeout)
    page.raise_for_status()
    form = parse_login_form(page.text)

    post_url = add_query(form["action"], inajax="1")
    password_value = password if password_is_md5 else md5_hex(password)

    data = {
        "formhash": form["formhash"],
        "referer": form["referer"],
        "loginfield": loginfield,
        "username": username,
        "password": password_value,
        "questionid": questionid,
        "answer": answer,
        "loginsubmit": "true",
    }
    if auto_login:
        data["cookietime"] = "2592000"

    headers = {
        "Origin": BASE_URL.rstrip("/"),
        "Referer": LOGIN_URL,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = session.post(post_url, data=data, headers=headers, timeout=timeout)
    resp.raise_for_status()

    text = resp.text
    success = is_login_success(text, session)
    if success:
        print("登录请求已返回成功提示。")
    elif "密码错误" in text or "登录失败" in text or "抱歉" in text:
        print("登录失败，服务端返回：")
        print(strip_html(text)[:800])
    else:
        print("登录请求完成，但未识别明确成功/失败文案。响应片段：")
        print(strip_html(text)[:800])

    if cookie_file and success:
        dump_cookies(session, cookie_file)
        print(f"Cookie 已保存到: {cookie_file}")
    elif cookie_file:
        print("未确认登录成功，未保存 Cookie。")

    return session


def strip_html(text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="moxing.lol Discuz 登录协议脚本")
    parser.add_argument(
        "-c",
        "--config",
        default=str(DEFAULT_CONFIG),
        help="登录配置文件路径，默认 moxing_config.json",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="生成一份配置文件模板后退出",
    )
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)
    if args.init_config:
        template = {
            "username": "你的用户名",
            "password": "你的密码",
            "loginfield": "username",
            "password_is_md5": False,
            "auto_login": True,
            "questionid": "0",
            "answer": "",
            "cookie_file": "moxing_cookies.json",
            "load_cookie_file": False,
            "timeout": 20,
        }
        if config_path.exists():
            raise FileExistsError(f"配置文件已存在，未覆盖: {config_path}")
        config_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"配置模板已生成: {config_path}")
        return

    config = load_config(config_path)

    login(
        config["username"],
        config["password"],
        loginfield=config.get("loginfield", "username"),
        password_is_md5=bool(config.get("password_is_md5", False)),
        auto_login=bool(config.get("auto_login", False)),
        questionid=str(config.get("questionid", "0")),
        answer=str(config.get("answer", "")),
        cookie_file=resolve_config_relative_path(
            str(config.get("cookie_file", "moxing_cookies.json")),
            config_path,
        ),
        load_cookie_file=bool(config.get("load_cookie_file", False)),
        timeout=int(config.get("timeout", 20)),
    )


if __name__ == "__main__":
    main()

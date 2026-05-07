import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from curl_cffi import requests
except ImportError:
    requests = None

from check import CHECK_URL, send_check_request
from encrypt import make_check_payload_from_points
from feich_captcha import fetch_captcha_image
from slider_track import calc_slider_track


BASE_URL = "https://laowang.vip/"
SIGN_URL = "https://laowang.vip/sign.php"
CONTEXT_JSON_PATH = Path(__file__).with_name("context.json")
COOKIES_JSON_PATH = Path(__file__).with_name("cookies.json")
CHECK_RESPONSE_PATTERN = re.compile(r"^[0-9a-fA-F]{32}_ok$")
REQUEST_PROXIES = None


@dataclass(frozen=True)
class FormInfo:
    action: str
    method: str
    fields: list[dict[str, Any]]


class AlreadySignedError(RuntimeError):
    pass


class QdleftHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self.saw_qdleft = False
        self.already_signed = False
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        classes = attrs_dict.get("class", "").split()
        if self._depth == 0 and "qdleft" in classes:
            self.saw_qdleft = True
            self._depth = 1
            return

        if self._depth:
            if "btnvisted" in classes:
                self.already_signed = True
            if tag.lower() == "a" and self.href is None:
                href = attrs_dict.get("href")
                if href:
                    self.href = html.unescape(href)
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._depth:
            self._depth -= 1


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[FormInfo] = []
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag == "form":
            self._current = {
                "action": html.unescape(attrs_dict.get("action", "")),
                "method": (attrs_dict.get("method") or "get").lower(),
                "fields": [],
            }
            return

        if self._current is None:
            return

        if tag == "input":
            self._current["fields"].append(
                {
                    "tag": tag,
                    "type": (attrs_dict.get("type") or "text").lower(),
                    "name": attrs_dict.get("name", ""),
                    "value": html.unescape(attrs_dict.get("value", "")),
                    "disabled": "disabled" in attrs_dict,
                    "checked": "checked" in attrs_dict,
                }
            )
        elif tag == "button":
            self._current["fields"].append(
                {
                    "tag": tag,
                    "type": (attrs_dict.get("type") or "submit").lower(),
                    "name": attrs_dict.get("name", ""),
                    "value": html.unescape(attrs_dict.get("value", "")),
                    "disabled": "disabled" in attrs_dict,
                }
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._current is not None:
            self.forms.append(
                FormInfo(
                    action=self._current["action"],
                    method=self._current["method"],
                    fields=self._current["fields"],
                )
            )
            self._current = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_response_cookies(cookies: dict[str, str], response: Any) -> dict[str, str]:
    merged = dict(cookies)
    if getattr(response, "cookies", None) is not None:
        merged.update(response.cookies.get_dict())
    return merged


def _format_sec_ch_ua(fingerprint: dict[str, Any]) -> str:
    brands = ((fingerprint.get("userAgentData") or {}).get("brands") or [])
    values = []
    for brand in brands:
        name = brand.get("brand")
        version = brand.get("version")
        if name and version:
            values.append(f'"{name}";v="{version}"')
    return ", ".join(values) or '"Chromium";v="147", "Google Chrome";v="147", "Not.A/Brand";v="8"'


def fingerprint_value(fingerprint: Any) -> str:
    if isinstance(fingerprint, str):
        return fingerprint
    if not isinstance(fingerprint, dict):
        return ""
    return str(
        fingerprint.get("browserFpField")
        or fingerprint.get("fingerprint")
        or fingerprint.get("fp")
        or ""
    )


def browser_headers(
    context: dict[str, Any],
    *,
    referer: str,
    accept: str,
    destination: str,
    mode: str,
    site: str = "same-origin",
    content_type: str | None = None,
) -> dict[str, str]:
    fingerprint = context.get("fingerprint") or {}
    user_agent_data = fingerprint.get("userAgentData") or {}
    platform = user_agent_data.get("platform") or fingerprint.get("platform") or "macOS"
    mobile = "?1" if user_agent_data.get("mobile") else "?0"
    headers = dict(context.get("headers") or {})
    headers.update(
        {
            "accept": accept,
            "accept-language": headers.get("accept-language", "zh-CN,zh;q=0.9"),
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": referer,
            "sec-ch-ua": _format_sec_ch_ua(fingerprint),
            "sec-ch-ua-mobile": mobile,
            "sec-ch-ua-platform": f'"{platform}"',
            "sec-fetch-dest": destination,
            "sec-fetch-mode": mode,
            "sec-fetch-site": site,
            "user-agent": fingerprint.get("userAgent") or headers.get("user-agent", ""),
        }
    )
    if content_type:
        headers["content-type"] = content_type
        parsed = urlparse(referer)
        headers["origin"] = f"{parsed.scheme}://{parsed.netloc}"
    else:
        headers.pop("content-type", None)
        headers.pop("origin", None)
    if destination == "document":
        headers["upgrade-insecure-requests"] = "1"
    return headers


def image_headers(context: dict[str, Any], *, referer: str) -> dict[str, str]:
    return browser_headers(
        context,
        referer=referer,
        accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        destination="image",
        mode="no-cors",
    )


def check_headers(context: dict[str, Any], *, referer: str) -> dict[str, str]:
    return browser_headers(
        context,
        referer=referer,
        accept="*/*",
        destination="empty",
        mode="cors",
        content_type="application/x-www-form-urlencoded",
    )


def document_headers(context: dict[str, Any], *, referer: str, site: str = "same-origin") -> dict[str, str]:
    return browser_headers(
        context,
        referer=referer,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        destination="document",
        mode="navigate",
        site=site,
    )


def submit_headers(context: dict[str, Any], *, referer: str) -> dict[str, str]:
    return browser_headers(
        context,
        referer=referer,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        destination="document",
        mode="navigate",
        content_type="application/x-www-form-urlencoded",
    )


def extract_qdleft_href(page_html: str) -> str:
    parser = QdleftHrefParser()
    parser.feed(page_html)
    if not parser.href:
        if parser.saw_qdleft and parser.already_signed:
            raise AlreadySignedError("今日已签到，页面不再返回签到 href")
        raise RuntimeError('未在 div class="qdleft" 下找到 a href')
    return parser.href


def extract_captcha_form(page_html: str) -> FormInfo:
    parser = FormParser()
    parser.feed(page_html)
    for form in parser.forms:
        names = {field.get("name") for field in form.fields}
        if "clicaptcha-submit-info" in names and "fingerprint" in names:
            return form
    if parser.forms:
        return parser.forms[0]
    raise RuntimeError("未找到 form 元素")


def build_form_data(form: FormInfo) -> dict[str, str]:
    data: dict[str, str] = {}
    for field in form.fields:
        if field.get("disabled"):
            continue
        name = field.get("name")
        if not name:
            continue
        field_type = (field.get("type") or "").lower()
        if field.get("tag") == "button" or field_type in {"button", "submit", "image", "reset", "file"}:
            continue
        if field_type in {"checkbox", "radio"} and not field.get("checked"):
            continue
        data[str(name)] = str(field.get("value") or "")
    return data


def get_redirected_sign_page(context: dict[str, Any], cookies: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    if requests is None:
        raise RuntimeError("缺少依赖: pip install curl_cffi")

    first_response = requests.get(
        SIGN_URL,
        headers=document_headers(context, referer=BASE_URL, site="none"),
        cookies=cookies,
        impersonate="chrome",
        allow_redirects=False,
        proxies=REQUEST_PROXIES,
        timeout=30,
    )
    cookies = merge_response_cookies(cookies, first_response)
    print(f"sign.php status: {first_response.status_code}")

    if first_response.status_code in {301, 302, 303, 307, 308}:
        location = first_response.headers.get("location")
        if not location:
            raise RuntimeError("sign.php 返回重定向状态，但缺少 Location")
        redirect_url = urljoin(str(first_response.url), location)
    else:
        redirect_url = str(first_response.url)

    page_response = requests.get(
        redirect_url,
        headers=document_headers(context, referer=SIGN_URL),
        cookies=cookies,
        impersonate="chrome",
        allow_redirects=True,
        proxies=REQUEST_PROXIES,
        timeout=30,
    )
    cookies = merge_response_cookies(cookies, page_response)
    page_response.raise_for_status()
    return str(page_response.url), page_response.text, cookies


def pass_captcha(context: dict[str, Any], cookies: dict[str, str], *, referer: str) -> tuple[str, dict[str, str]]:
    captcha_response = fetch_captcha_image(
        cookies=cookies,
        headers=image_headers(context, referer=referer),
        proxies=REQUEST_PROXIES,
        filename_prefix="qiandao_tncode",
    )
    cookies = dict(captcha_response.cookies)
    print(f"captcha image saved: {captcha_response.image_path.resolve()}")

    slider_result = calc_slider_track(captcha_response.image_path, debug_dir=Path.cwd() / "debug")
    print(f"move_x: {slider_result.move_x}")
    print(f"target position: ({slider_result.target_x}, {slider_result.target_y}), score: {slider_result.score:.4f}")

    payload = make_check_payload_from_points(slider_result.points, offset=slider_result.move_x)
    check_response = send_check_request(
        cookies=cookies,
        headers=check_headers(context, referer=referer),
        payload=payload,
        proxies=REQUEST_PROXIES,
        check_url=CHECK_URL,
    )
    cookies = merge_response_cookies(cookies, check_response)
    check_text = check_response.text.strip()
    print(f"check response: {check_text}")
    if not CHECK_RESPONSE_PATTERN.fullmatch(check_text):
        raise RuntimeError(f"验证码校验返回格式异常: {check_response.text!r}")
    return check_text, cookies


def run() -> None:
    context = load_json(CONTEXT_JSON_PATH)
    cookies = {}
    cookies.update(context.get("cookies") or {})
    cookies.update(load_json(COOKIES_JSON_PATH))

    sign_page_url, sign_page_html, cookies = get_redirected_sign_page(context, cookies)
    try:
        qd_href = extract_qdleft_href(sign_page_html)
    except AlreadySignedError as exc:
        print(str(exc))
        save_json(COOKIES_JSON_PATH, cookies)
        return
    qd_url = urljoin(sign_page_url, qd_href)
    print(f"redirected sign page: {sign_page_url}")
    print(f"qiandao href: {qd_url}")

    form_page_response = requests.get(
        qd_url,
        headers=document_headers(context, referer=sign_page_url),
        cookies=cookies,
        impersonate="chrome",
        allow_redirects=True,
        proxies=REQUEST_PROXIES,
        timeout=30,
    )
    cookies = merge_response_cookies(cookies, form_page_response)
    form_page_response.raise_for_status()
    form_page_url = str(form_page_response.url)
    form = extract_captcha_form(form_page_response.text)
    form_action = urljoin(form_page_url, form.action or form_page_url)
    print(f"form action: {form_action}")

    check_text, cookies = pass_captcha(context, cookies, referer=form_page_url)
    data = build_form_data(form)
    data["clicaptcha-submit-info"] = check_text
    data["fingerprint"] = fingerprint_value(context.get("fingerprint"))

    method = (form.method or "post").lower()
    headers = submit_headers(context, referer=form_page_url)
    if method == "get":
        submit_response = requests.get(
            form_action,
            params=data,
            headers=headers,
            cookies=cookies,
            impersonate="chrome",
            allow_redirects=True,
            proxies=REQUEST_PROXIES,
            timeout=30,
        )
    else:
        submit_response = requests.post(
            form_action,
            data=data,
            headers=headers,
            cookies=cookies,
            impersonate="chrome",
            allow_redirects=True,
            proxies=REQUEST_PROXIES,
            timeout=30,
        )

    cookies = merge_response_cookies(cookies, submit_response)
    save_json(COOKIES_JSON_PATH, cookies)
    print(f"submit status: {submit_response.status_code}")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

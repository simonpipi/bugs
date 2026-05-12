import argparse
import html
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    from curl_cffi import requests
except ImportError:
    requests = None

try:
    from .captcha_flow import pass_slider_captcha
    from .common import (
        fingerprint_value,
        load_context_and_cookies as _load_context_and_cookies,
        merge_response_cookies,
        save_json,
    )
    from .headers import check_headers, document_headers, image_headers, submit_headers
except ImportError:
    from captcha_flow import pass_slider_captcha
    from common import (
        fingerprint_value,
        load_context_and_cookies as _load_context_and_cookies,
        merge_response_cookies,
        save_json,
    )
    from headers import check_headers, document_headers, image_headers, submit_headers
try:
    from .account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs
except ImportError:
    from account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs


BASE_URL = "https://laowang.vip/"
SIGN_URL = "https://laowang.vip/sign.php"
CONTEXT_JSON_PATH = Path(__file__).with_name("context.json")
COOKIES_JSON_PATH = Path(__file__).with_name("cookies.json")
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
    result = pass_slider_captcha(
        context=context,
        cookies=cookies,
        image_headers=image_headers(context, referer=referer),
        check_headers=check_headers(context, referer=referer),
        proxies=REQUEST_PROXIES,
        filename_prefix="qiandao_tncode",
        debug_dir=Path.cwd() / "debug",
    )
    return result.check_text, result.cookies


def load_context_and_cookies(account: AccountConfig | None) -> tuple[dict[str, Any], dict[str, str], Path]:
    return _load_context_and_cookies(
        account,
        default_context_path=CONTEXT_JSON_PATH,
        default_cookies_path=COOKIES_JSON_PATH,
    )


def run(account: AccountConfig | None = None) -> None:
    context, cookies, cookies_path = load_context_and_cookies(account)
    if account is not None:
        print(f"account: {account.name}")

    sign_page_url, sign_page_html, cookies = get_redirected_sign_page(context, cookies)
    try:
        qd_href = extract_qdleft_href(sign_page_html)
    except AlreadySignedError as exc:
        print(str(exc))
        save_json(cookies_path, cookies)
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
    save_json(cookies_path, cookies)
    print(f"submit status: {submit_response.status_code}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用已保存的账号 cookies 执行签到")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="账号配置文件路径，默认 laowang/accounts.json",
    )
    parser.add_argument("--account", help="只签到指定账号名")
    parser.add_argument("--all", action="store_true", help="签到配置中的全部账号")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    use_account_config = args.account or args.all or config_path.exists()
    if not use_account_config:
        run()
        return 0

    accounts = select_account_configs(
        config_path=config_path,
        account_name=args.account,
        all_accounts=args.all,
    )
    failed: list[tuple[str, Exception]] = []
    for account in accounts:
        try:
            run(account)
        except Exception as exc:
            failed.append((account.name, exc))
            print(f"account {account.name} failed: {exc}", file=sys.stderr)
            if not args.all:
                break

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

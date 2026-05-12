import argparse
import html
import json
import random
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

try:
    from curl_cffi import requests
except ImportError:
    requests = None

try:
    from .account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs
    from .captcha_flow import pass_slider_captcha
    from .common import (
        fingerprint_value,
        load_context_and_cookies as _load_context_and_cookies,
        load_json,
        merge_response_cookies,
        resolve_local_path,
        save_json,
    )
    from .headers import (
        browser_headers as _browser_headers,
        check_headers as captcha_check_headers,
        image_headers as captcha_image_headers,
    )
except ImportError:
    from account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs
    from captcha_flow import pass_slider_captcha
    from common import (
        fingerprint_value,
        load_context_and_cookies as _load_context_and_cookies,
        load_json,
        merge_response_cookies,
        resolve_local_path,
        save_json,
    )
    from headers import (
        browser_headers as _browser_headers,
        check_headers as captcha_check_headers,
        image_headers as captcha_image_headers,
    )


BASE_URL = "https://laowang.vip/"
FORUM_URL = "https://laowang.vip/forum.php"
BASE_DIR = Path(__file__).resolve().parent
CONTEXT_JSON_PATH = Path(__file__).with_name("context.json")
COOKIES_JSON_PATH = Path(__file__).with_name("cookies.json")
REQUEST_PROXIES = None
DEFAULT_MESSAGE = "是真人，但是拍摄效果问题，居中小，外围大\r\n"
DEFAULT_REPLY_POOL_PATH = Path(__file__).with_name("reply_pool.json")
DEFAULT_REPLY_POOL_STATE_PATH = Path(__file__).with_name("reply_pool_state.json")
DEBUG_DIR = BASE_DIR.parent / "debug"


class FastPostFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_fastpost_form = False
        self.depth = 0
        self.action = ""
        self.method = "post"
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}

        if tag == "form":
            form_id = attrs_dict.get("id", "")
            form_name = attrs_dict.get("name", "")
            if form_id == "fastpostform" or form_name == "fastpostform":
                self.in_fastpost_form = True
                self.depth = 1
                self.action = html.unescape(attrs_dict.get("action", ""))
                self.method = (attrs_dict.get("method") or "post").lower()
            return

        if not self.in_fastpost_form:
            return

        if tag in {"input", "textarea"}:
            name = attrs_dict.get("name")
            if name and "disabled" not in attrs_dict:
                self.fields[name] = html.unescape(attrs_dict.get("value", ""))

        if tag not in {"input", "br", "hr", "img", "meta", "link"}:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self.in_fastpost_form:
            self.depth -= 1
            if self.depth <= 0:
                self.in_fastpost_form = False


def load_reply_pool(path: Path) -> list[str]:
    if not path.exists():
        return [DEFAULT_MESSAGE]

    if path.suffix.lower() == ".json":
        raw = load_json(path)
        if isinstance(raw, dict):
            raw = raw.get("messages")
        if not isinstance(raw, list):
            raise ValueError("回复池 JSON 必须是数组，或包含 messages 数组")
        messages = [str(item).strip() for item in raw if str(item).strip()]
    else:
        messages = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not messages:
        raise ValueError(f"回复池为空: {path}")
    return messages


def load_reply_pool_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = load_json(path)
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def select_reply_from_pool(
    messages: list[str],
    *,
    mode: str,
    pool_path: Path,
    state_path: Path,
) -> str:
    if mode == "random":
        return random.choice(messages)
    if mode != "sequential":
        raise ValueError(f"不支持的回复池模式: {mode}")

    state = load_reply_pool_state(state_path)
    key = str(pool_path.resolve())
    index = int(state.get(key, 0) or 0)
    message = messages[index % len(messages)]
    state[key] = (index + 1) % len(messages)
    save_json(state_path, state)
    return message


def choose_reply_message(
    explicit_message: str | None,
    *,
    reply_pool: Path,
    reply_pool_state: Path,
    reply_mode: str,
) -> str:
    if explicit_message is not None:
        return explicit_message
    messages = load_reply_pool(reply_pool)
    return select_reply_from_pool(
        messages,
        mode=reply_mode,
        pool_path=reply_pool,
        state_path=reply_pool_state,
    )


def browser_headers(
    context: dict[str, Any],
    *,
    referer: str,
    content_type: str | None = None,
    destination: str = "document",
) -> dict[str, str]:
    return _browser_headers(
        context,
        referer=referer,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        destination=destination,
        mode="navigate",
        content_type=content_type,
        include_sec_fetch_user=True,
        include_upgrade=True,
    )


def load_context_and_cookies(account: AccountConfig | None) -> tuple[dict[str, Any], dict[str, str], Path]:
    return _load_context_and_cookies(
        account,
        default_context_path=CONTEXT_JSON_PATH,
        default_cookies_path=COOKIES_JSON_PATH,
    )


def thread_url(tid: str, page: int) -> str:
    return f"https://laowang.vip/thread-{tid}-{page}-1.html"


def split_action(action: str, *, base_url: str) -> tuple[str, dict[str, str]]:
    action_url = urljoin(base_url, action or FORUM_URL)
    parsed = urlparse(action_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return url, params


def extract_fastpost_form(page_html: str) -> FastPostFormParser:
    parser = FastPostFormParser()
    parser.feed(page_html)
    if not parser.fields:
        raise RuntimeError("未找到 fastpostform，可能未登录或当前帖子不可回复")
    return parser


def extract_fid(page_html: str, action_params: dict[str, str]) -> str:
    if action_params.get("fid"):
        return action_params["fid"]

    patterns = [
        r"forum\.php\?mod=forumdisplay&amp;fid=(\d+)",
        r"forum\.php\?mod=forumdisplay&fid=(\d+)",
        r"forum-(\d+)-1\.html",
        r"fid[\"']?\s*[:=]\s*[\"']?(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html)
        if match:
            return match.group(1)
    raise RuntimeError("未能从帖子页提取 fid，请使用 --fid 指定")


def build_reply_data(
    fields: dict[str, str],
    *,
    message: str,
    fingerprint: str,
    captcha_check_text: str,
    subject: str,
) -> dict[str, str]:
    data = dict(fields)
    data.update(
        {
            "file": data.get("file", ""),
            "message": message,
            "fingerprint": fingerprint,
            "clicaptcha-submit-info": captcha_check_text,
            "usesig": data.get("usesig", "1"),
            "subject": subject,
        }
    )
    return data


def build_reply_params(
    form_params: dict[str, str],
    *,
    fid: str,
    tid: str,
    page: int,
) -> dict[str, str]:
    params = {
        "mod": "post",
        "action": "reply",
        "fid": fid,
        "tid": tid,
        "extra": f"page={page}",
        "replysubmit": "yes",
        "infloat": "yes",
        "handlekey": "fastpost",
        "inajax": "1",
    }
    params.update({k: v for k, v in form_params.items() if k not in {"mod", "action", "fid", "tid"}})
    return params


def fetch_thread_page(
    context: dict[str, Any],
    cookies: dict[str, str],
    *,
    tid: str,
    page: int,
) -> tuple[str, str, dict[str, str]]:
    if requests is None:
        raise RuntimeError("缺少依赖: pip install curl_cffi")

    url = thread_url(tid, page)
    response = requests.get(
        url,
        headers=browser_headers(context, referer=BASE_URL),
        cookies=cookies,
        impersonate="chrome",
        allow_redirects=True,
        proxies=REQUEST_PROXIES,
        timeout=30,
    )
    cookies = merge_response_cookies(cookies, response)
    response.raise_for_status()
    return str(response.url), response.text, cookies


def submit_reply(
    context: dict[str, Any],
    cookies: dict[str, str],
    *,
    reply_url: str,
    params: dict[str, str],
    data: dict[str, str],
    referer: str,
) -> tuple[Any, dict[str, str]]:
    if requests is None:
        raise RuntimeError("缺少依赖: pip install curl_cffi")

    response = requests.post(
        reply_url,
        params=params,
        data=data,
        headers=browser_headers(
            context,
            referer=referer,
            content_type="application/x-www-form-urlencoded",
            destination="iframe",
        ),
        cookies=cookies,
        impersonate="chrome",
        allow_redirects=True,
        proxies=REQUEST_PROXIES,
        timeout=30,
    )
    cookies = merge_response_cookies(cookies, response)
    return response, cookies


def pass_captcha(context: dict[str, Any], cookies: dict[str, str], *, referer: str) -> tuple[str, dict[str, str]]:
    result = pass_slider_captcha(
        context=context,
        cookies=cookies,
        image_headers=captcha_image_headers(context, referer=referer),
        check_headers=captcha_check_headers(context, referer=referer),
        proxies=REQUEST_PROXIES,
        filename_prefix="huifu_tncode",
        debug_dir=DEBUG_DIR,
    )
    return result.check_text, result.cookies


def run(
    *,
    account: AccountConfig | None = None,
    tid: str,
    fid: str | None,
    message: str,
    page: int = 1,
    subject: str = "  ",
) -> None:
    context, cookies, cookies_path = load_context_and_cookies(account)
    if account is not None:
        print(f"account: {account.name}")

    thread_page_url, page_html, cookies = fetch_thread_page(context, cookies, tid=tid, page=page)
    form = extract_fastpost_form(page_html)
    form_url, form_params = split_action(form.action, base_url=thread_page_url)
    reply_fid = fid or extract_fid(page_html, form_params)
    params = build_reply_params(form_params, fid=reply_fid, tid=tid, page=page)
    check_text, cookies = pass_captcha(context, cookies, referer=thread_page_url)
    data = build_reply_data(
        form.fields,
        message=message,
        fingerprint=fingerprint_value(context.get("fingerprint")),
        captcha_check_text=check_text,
        subject=subject,
    )

    print(f"thread page: {thread_page_url}")
    print(f"reply url: {form_url}?{urlencode(params)}")
    response, cookies = submit_reply(
        context,
        cookies,
        reply_url=form_url,
        params=params,
        data=data,
        referer=thread_page_url,
    )
    save_json(cookies_path, cookies)
    print(f"reply status: {response.status_code}")
    print(response.text[:500])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用已保存的账号登录态调用回复接口")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="账号配置文件路径")
    parser.add_argument("--account", help="只使用指定账号名")
    parser.add_argument("--all", action="store_true", help="配置中的全部账号都回复")
    parser.add_argument("--tid", default="2716676", help="帖子 tid")
    parser.add_argument("--fid", help="版块 fid；不传则从帖子页提取")
    parser.add_argument("--page", type=int, default=1, help="帖子页码")
    parser.add_argument("--message", help="回复内容；传入后会覆盖回复池")
    parser.add_argument(
        "--reply-pool",
        default=str(DEFAULT_REPLY_POOL_PATH),
        help="回复池文件，支持 JSON 数组、包含 messages 数组的 JSON 对象，或一行一条的 txt",
    )
    parser.add_argument(
        "--reply-mode",
        choices=["random", "sequential"],
        default="random",
        help="回复池取值模式",
    )
    parser.add_argument(
        "--reply-pool-state",
        default=str(DEFAULT_REPLY_POOL_STATE_PATH),
        help="sequential 模式的状态文件",
    )
    parser.add_argument("--subject", default="  ", help="回复 subject 字段，默认两个空格")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    reply_pool = resolve_local_path(args.reply_pool)
    reply_pool_state = resolve_local_path(args.reply_pool_state)
    use_account_config = args.account or args.all or config_path.exists()
    if not use_account_config:
        message = choose_reply_message(
            args.message,
            reply_pool=reply_pool,
            reply_pool_state=reply_pool_state,
            reply_mode=args.reply_mode,
        )
        run(
            account=None,
            tid=str(args.tid),
            fid=args.fid,
            page=args.page,
            message=message,
            subject=args.subject,
        )
        return 0

    accounts = select_account_configs(
        config_path=config_path,
        account_name=args.account,
        all_accounts=args.all,
    )
    failed: list[tuple[str, Exception]] = []
    for account in accounts:
        try:
            message = choose_reply_message(
                args.message,
                reply_pool=reply_pool,
                reply_pool_state=reply_pool_state,
                reply_mode=args.reply_mode,
            )
            run(
                account=account,
                tid=str(args.tid),
                fid=args.fid,
                page=args.page,
                message=message,
                subject=args.subject,
            )
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

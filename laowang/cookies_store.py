import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from .feich_captcha import fetch_captcha_image
    from .slider_track import calc_slider_track
    from .encrypt import make_check_payload_from_points
    from .check import build_check_headers, send_check_request
    from .login import login
except ImportError:
    from feich_captcha import fetch_captcha_image
    from slider_track import calc_slider_track
    from encrypt import make_check_payload_from_points
    from check import build_check_headers, send_check_request
    from login import login
try:
    from .account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs
except ImportError:
    from account_config import DEFAULT_CONFIG_PATH, AccountConfig, select_account_configs

URL = "https://laowang.vip/member.php?mod=logging&action=login"
BASE_DIR = Path(__file__).resolve().parent
SCREENSHOT_PATH = BASE_DIR / "security_verification_popup.png"
CONTEXT_JSON_PATH = BASE_DIR / "context.json"
COOKIES_JSON_PATH = BASE_DIR / "cookies.json"
DEBUG_DIR = BASE_DIR.parent / "debug"
REQUEST_PROXIES = {
    "http": "http://127.0.0.1:7897",
    "https": "http://127.0.0.1:7897",
}
CHECK_RESPONSE_PATTERN = re.compile(r"^[0-9a-fA-F]{32}_ok$")

JS = r"""
(() => {
  function canvasFingerprint() {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 220;
      canvas.height = 198;

      const ctx = canvas.getContext("2d");
      if (!ctx) return "nc";

      ctx.fillStyle = "rgba(100,200,50,0.8)";
      ctx.textBaseline = "alphabetic";
      ctx.fillRect(0, 0, 220, 30);

      ctx.fillStyle = "#069";
      ctx.font = "14px Arial,sans-serif";
      ctx.fillText("Lw老王_fp😀", 4, 20);

      ctx.fillStyle = "#f0a";
      ctx.font = "11px Georgia";
      ctx.fillText("hfsdn", 80, 26);

      return canvas.toDataURL().slice(-40);
    } catch (e) {
      return "ce";
    }
  }

  function webglRenderer() {
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) return "";

      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "";

      return gl.getParameter(gl.RENDERER) || "";
    } catch (e) {
      return "";
    }
  }

  return {
    browserFpField: document.getElementById("browser_fp")?.value || "",
    userAgent: navigator.userAgent,
    languages: navigator.languages,
    language: navigator.language,
    screenWidth: screen.width,
    screenHeight: screen.height,
    colorDepth: screen.colorDepth,
    timezoneOffset: new Date().getTimezoneOffset(),
    platform: navigator.platform,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory || "",
    userAgentData: navigator.userAgentData ? {
      brands: navigator.userAgentData.brands,
      mobile: navigator.userAgentData.mobile,
      platform: navigator.userAgentData.platform
    } : null,
    canvasTail: canvasFingerprint(),
    webglRenderer: webglRenderer()
  };
})()
"""

LOGIN_FORM_JS = r"""
(() => {
  const form = document.querySelector('form[name="login"]');
  if (!form) return null;

  const fields = Array.from(form.querySelectorAll("input, select, textarea, button")).map((el) => {
    const info = {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      name: el.getAttribute("name") || "",
      id: el.id || "",
      value: "value" in el ? el.value : "",
      disabled: Boolean(el.disabled),
      required: Boolean(el.required),
      placeholder: el.getAttribute("placeholder") || "",
      autocomplete: el.getAttribute("autocomplete") || "",
    };

    if ("checked" in el) info.checked = Boolean(el.checked);
    if (el.tagName.toLowerCase() === "select") {
      info.options = Array.from(el.options).map((option) => ({
        value: option.value,
        text: option.text,
        selected: option.selected,
      }));
    }
    return info;
  });

  return {
    name: form.getAttribute("name") || "",
    id: form.id || "",
    action: form.action || "",
    actionAttr: form.getAttribute("action") || "",
    method: form.method || "",
    methodAttr: form.getAttribute("method") || "",
    enctype: form.enctype || "",
    target: form.target || "",
    fields,
  };
})()
"""


@dataclass(frozen=True)
class BrowserRequestContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    fingerprint: dict[str, Any]
    login_form: dict[str, Any] | None
    cookie_header: str
    storage_state: dict[str, Any]


@dataclass(frozen=True)
class CaptchaCheckResult:
    check_text: str
    cookies: dict[str, str]


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def format_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _format_sec_ch_ua(user_agent_data: dict[str, Any] | None) -> str:
    brands = (user_agent_data or {}).get("brands") or []
    values = []
    for brand in brands:
        name = brand.get("brand")
        version = brand.get("version")
        if name and version:
            values.append(f'"{name}";v="{version}"')
    return ", ".join(values) or '"Chromium";v="147", "Google Chrome";v="147", "Not.A/Brand";v="8"'


def build_captcha_headers(fingerprint: dict[str, Any], *, referer: str = URL) -> dict[str, str]:
    user_agent_data = fingerprint.get("userAgentData")
    platform = (user_agent_data or {}).get("platform") or fingerprint.get("platform") or "macOS"
    mobile = "?1" if (user_agent_data or {}).get("mobile") else "?0"

    return {
        "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "i",
        "referer": referer,
        "sec-ch-ua": _format_sec_ch_ua(user_agent_data),
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": f'"{platform}"',
        "sec-fetch-dest": "image",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-site": "same-origin",
        "user-agent": fingerprint.get("userAgent", ""),
    }


def get_browser_request_context(
    *,
    url: str = URL,
    headless: bool = True,
    timeout: int = 60000,
    form_timeout: int = 5000,
) -> BrowserRequestContext:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=headless)
        except Exception:
            browser = p.chromium.launch(headless=headless)
        page = browser.new_page(locale="zh-CN")

        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_selector('form[name="login"]', state="attached", timeout=form_timeout)
        except PlaywrightTimeoutError:
            pass

        fingerprint = page.evaluate(JS)
        login_form = page.evaluate(LOGIN_FORM_JS)
        storage_state = page.context.storage_state()
        cookies_list = storage_state.get("cookies", [])
        browser.close()

    cookies = {cookie["name"]: cookie["value"] for cookie in cookies_list}
    cookie_header = format_cookie_header(cookies)
    headers = build_captcha_headers(fingerprint, referer=url)
    return BrowserRequestContext(
        cookies=cookies,
        headers=headers,
        fingerprint=fingerprint,
        login_form=login_form,
        cookie_header=cookie_header,
        storage_state=storage_state,
    )


def pass_captcha_check(
    context: BrowserRequestContext,
    *,
    cookies_path: Path = COOKIES_JSON_PATH,
) -> CaptchaCheckResult:
    result = fetch_captcha_image(
        cookies=context.cookies,
        headers=context.headers,
        proxies=REQUEST_PROXIES,
    )
    print(f"captcha image saved: {result.image_path.resolve()}")
    print("merged cookies:", result.cookies)
    save_json(cookies_path, result.cookies)

    slider_result = calc_slider_track(result.image_path, debug_dir=DEBUG_DIR)
    print(f"move_x: {slider_result.move_x}")
    print(f"target position: ({slider_result.target_x}, {slider_result.target_y}), score: {slider_result.score:.4f}")
    # print(f"track points: {slider_result.points}")

    payload = make_check_payload_from_points(
        slider_result.points,
        offset=slider_result.move_x,
    )
    print(f"check payload: {payload}")

    check_headers = build_check_headers(context.fingerprint)
    check_response = send_check_request(
        cookies=result.cookies,
        headers=check_headers,
        payload=payload,
        proxies=REQUEST_PROXIES,
    )
    print(f"check response: {check_response.text}")
    check_text = check_response.text.strip()
    if not CHECK_RESPONSE_PATTERN.fullmatch(check_text):
        raise RuntimeError(f"check response format invalid: {check_response.text!r}")

    cookies = dict(result.cookies)
    if getattr(check_response, "cookies", None) is not None:
        cookies.update(check_response.cookies.get_dict())
    save_json(cookies_path, cookies)

    return CaptchaCheckResult(
        check_text=check_text,
        cookies=cookies,
    )


def save_context_with_cookies(path: Path, context: BrowserRequestContext, cookies: dict[str, str]) -> None:
    context_data = asdict(context)
    context_data["cookies"] = cookies
    context_data["cookie_header"] = format_cookie_header(cookies)
    save_json(path, context_data)


def refresh_account(account: AccountConfig, *, headless: bool = True) -> None:
    print(f"account: {account.name}")
    context = get_browser_request_context(headless=headless)
    save_context_with_cookies(account.context_path, context, context.cookies)
    save_json(account.cookies_path, context.cookies)
    print("fingerprint data:", context.fingerprint)
    # print("login form:", context.login_form)
    print("cookie header:", context.cookie_header)
    print("context saved:", account.context_path.resolve())
    print("cookies saved:", account.cookies_path.resolve())

    captcha_check = pass_captcha_check(context, cookies_path=account.cookies_path)
    check_text = captcha_check.check_text
    login_cookies = dict(captcha_check.cookies)

    login_username = account.username
    login_password = account.password
    if not login_username or not login_password:
        print(f"skip login: 账号 {account.name} 缺少 username/password 配置")
    else:
        login_response = login(
            login_username,
            login_password,
            context,
            check_text,
            cookies=login_cookies,
            proxies=REQUEST_PROXIES,
        )
        print(f"login response status: {login_response.status_code}")
        print(f"login response: {login_response.text[:1000]}")
        print(f"login response cookies: {login_response.cookies.get_dict() if getattr(login_response, 'cookies', None) else {}}")
        if getattr(login_response, "cookies", None) is not None:
            login_cookies.update(login_response.cookies.get_dict())
        save_json(account.cookies_path, login_cookies)
        save_context_with_cookies(account.context_path, context, login_cookies)
        print("cookies saved:", account.cookies_path.resolve())
        print("context saved:", account.context_path.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新老王账号的 context 和 cookies")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="账号配置文件路径，默认 laowang/accounts.json",
    )
    parser.add_argument("--account", help="只刷新指定账号名")
    parser.add_argument("--all", action="store_true", help="刷新配置中的全部账号")
    parser.add_argument("--headless", action="store_true", help="使用无头浏览器，默认启用")
    parser.add_argument("--headed", action="store_false", dest="headless", help="调试时显示浏览器窗口")
    parser.set_defaults(headless=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    accounts = select_account_configs(
        config_path=Path(args.config),
        account_name=args.account,
        all_accounts=args.all,
    )

    failed: list[tuple[str, Exception]] = []
    for account in accounts:
        try:
            refresh_account(account, headless=args.headless)
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

"""滑块验证码的完整通过流程。

流程为：下载验证码图 -> 识别滑块位移和轨迹 -> 生成前端同款校验 payload
-> 调用 check.php -> 合并服务端返回的 Cookie。
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from .check import CHECK_URL, send_check_request
    from .common import merge_response_cookies
    from .encrypt import make_check_payload_from_points
    from .feich_captcha import fetch_captcha_image
    from .slider_track import calc_slider_track
except ImportError:
    from check import CHECK_URL, send_check_request
    from common import merge_response_cookies
    from encrypt import make_check_payload_from_points
    from feich_captcha import fetch_captcha_image
    from slider_track import calc_slider_track


CHECK_RESPONSE_PATTERN = re.compile(r"^[0-9a-fA-F]{32}_ok$")
HeaderBuilder = Callable[[Any], dict[str, str]]


@dataclass(frozen=True)
class CaptchaCheckResult:
    """验证码校验成功后向业务脚本返回的结果。"""

    check_text: str
    cookies: dict[str, str]
    image_path: Path
    move_x: int
    target_x: int
    target_y: int
    score: float


def pass_slider_captcha(
    *,
    context: Any,
    cookies: dict[str, str],
    image_headers: dict[str, str],
    check_headers: dict[str, str],
    proxies: dict[str, str] | None,
    filename_prefix: str,
    debug_dir: Path,
    check_url: str = CHECK_URL,
    verbose: bool = True,
) -> CaptchaCheckResult:
    """执行一次滑块验证码识别与校验。"""

    captcha_response = fetch_captcha_image(
        cookies=cookies,
        headers=image_headers,
        proxies=proxies,
        filename_prefix=filename_prefix,
    )
    merged_cookies = dict(captcha_response.cookies)
    if verbose:
        print(f"captcha image saved: {captcha_response.image_path.resolve()}")

    slider_result = calc_slider_track(captcha_response.image_path, debug_dir=debug_dir)
    if verbose:
        print(f"move_x: {slider_result.move_x}")
        print(
            f"target position: ({slider_result.target_x}, {slider_result.target_y}), "
            f"score: {slider_result.score:.4f}"
        )

    # check.php 需要前端同款 track/sign/tn_r 参数，不能直接提交移动距离。
    payload = make_check_payload_from_points(slider_result.points, offset=slider_result.move_x)
    check_response = send_check_request(
        cookies=merged_cookies,
        headers=check_headers,
        payload=payload,
        proxies=proxies,
        check_url=check_url,
    )
    merged_cookies = merge_response_cookies(merged_cookies, check_response)
    check_text = check_response.text.strip()
    if verbose:
        print(f"check response: {check_text}")
    if not CHECK_RESPONSE_PATTERN.fullmatch(check_text):
        raise RuntimeError(f"验证码校验返回格式异常: {check_response.text!r}")

    return CaptchaCheckResult(
        check_text=check_text,
        cookies=merged_cookies,
        image_path=captcha_response.image_path,
        move_x=slider_result.move_x,
        target_x=slider_result.target_x,
        target_y=slider_result.target_y,
        score=slider_result.score,
    )

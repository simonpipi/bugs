"""复现前端滑块验证码 check.php 所需的 track/sign 参数。

这里的 JSON 序列化、FNV-1a 变体、XOR 与 base64 编码都需要和前端逻辑保持
一致，否则服务端会拒绝验证码校验。
"""

import base64
import json
import math
import time
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlencode

SECRET = "GWDiugh398huiw0ioOYGd0934hew"


def js_json_dumps(obj):
    """使用接近 JavaScript JSON.stringify 的紧凑格式。"""

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def fnv1a32(text: str) -> str:
    """计算前端用于 sign 字段的 32 位 FNV-1a 哈希。"""

    h = 0x811C9DC5

    for ch in text:
        h ^= ord(ch)
        h = (
            h
            + ((h << 1) & 0xFFFFFFFF)
            + ((h << 4) & 0xFFFFFFFF)
            + ((h << 7) & 0xFFFFFFFF)
            + ((h << 8) & 0xFFFFFFFF)
            + ((h << 24) & 0xFFFFFFFF)
        ) & 0xFFFFFFFF

    return format(h, "x")


def xor_with_secret(text: str, secret: str = SECRET) -> bytes:
    """按密钥循环异或轨迹 JSON，生成 track 的原始字节。"""

    text_bytes = text.encode("utf-8")
    secret_bytes = secret.encode("utf-8")

    return bytes(
        b ^ secret_bytes[i % len(secret_bytes)]
        for i, b in enumerate(text_bytes)
    )


def make_track(track_info: dict) -> str:
    """把轨迹统计信息编码成接口需要的 track 字符串。"""

    raw_json = js_json_dumps(track_info)
    xored = xor_with_secret(raw_json)
    return base64.b64encode(xored).decode("ascii")


def normalize_points(points: Iterable[Sequence[int] | Mapping[str, int]]) -> list[dict[str, int]]:
    """兼容 tuple/list 点位和 dict 点位，统一成 {x, y, t}。"""

    normalized: list[dict[str, int]] = []
    for point in points:
        if isinstance(point, Mapping):
            normalized.append({
                "x": int(point["x"]),
                "y": int(point["y"]),
                "t": int(point["t"]),
            })
        else:
            x, y, t = point
            normalized.append({"x": int(x), "y": int(y), "t": int(t)})
    return normalized


def build_track_info(points: Iterable[Sequence[int] | Mapping[str, int]]) -> dict:
    """把原始移动点转换成前端校验用的速度、方向、距离统计。"""

    normalized = normalize_points(points)
    track_info = {
        "valid": False,
    }
    if len(normalized) <= 2:
        return track_info

    total_time = normalized[-1]["t"]
    total_dist = 0.0
    speeds: list[float] = []
    directions: list[float] = []

    for index in range(1, len(normalized)):
        prev = normalized[index - 1]
        current = normalized[index]
        dx = current["x"] - prev["x"]
        dy = current["y"] - prev["y"]
        dt = current["t"] - prev["t"]
        if dt <= 0:
            continue

        dist = math.sqrt(dx * dx + dy * dy)
        total_dist += dist
        speeds.append(dist / dt)
        directions.append(math.atan2(dy, dx))

    # 服务端使用这些统计值判断轨迹是否像真实拖拽。
    avg_speed = sum(speeds) / len(speeds) if speeds else 0
    max_speed = max(speeds) if speeds else 0
    min_speed = min(speeds) if speeds else 0
    speed_var = 0.0
    if speeds:
        speed_var = sum((speed - avg_speed) ** 2 for speed in speeds) / len(speeds)

    dir_changes = 0
    for index in range(1, len(directions)):
        if abs(directions[index] - directions[index - 1]) > math.pi / 3:
            dir_changes += 1

    return {
        "valid": True,
        "points": len(normalized),
        "totalTime": total_time,
        "totalDist": total_dist,
        "avgSpeed": avg_speed,
        "maxSpeed": max_speed,
        "minSpeed": min_speed,
        "speedVar": speed_var,
        "dirChanges": dir_changes,
        "finalX": normalized[-1]["x"] - normalized[0]["x"],
    }


def make_check_payload(track_info: dict, offset: float, ts: int | None = None) -> dict:
    """生成 check.php 表单字段：tn_r、track、ts、sign。"""

    tn_r = f"{offset:.2f}"
    ts = int(time.time() * 1000) if ts is None else int(ts)

    raw_json = js_json_dumps(track_info)
    track = make_track(track_info)
    sign = fnv1a32(raw_json + str(ts) + tn_r + SECRET)

    return {
        "tn_r": tn_r,
        "track": track,
        "ts": str(ts),
        "sign": sign,
    }


def make_check_payload_from_points(
    points: Iterable[Sequence[int] | Mapping[str, int]],
    offset: float,
    ts: int | None = None,
) -> dict:
    """从绝对轨迹点直接生成验证码校验 payload。"""

    return make_check_payload(build_track_info(points), offset, ts=ts)


def make_check_query(payload: dict) -> str:
    """把 payload 编码成 application/x-www-form-urlencoded query。"""

    return urlencode(payload)

"""读取并规范化多账号配置。

该模块只负责把 accounts.json 中的账号、登录态路径和凭据来源整理成
AccountConfig，供刷新 Cookie、签到、回复、购买等脚本复用。
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).with_name("accounts.json")
DEFAULT_DATA_DIR_NAME = "accounts"


@dataclass(frozen=True)
class AccountConfig:
    """单个账号运行所需的静态配置。"""

    name: str
    username: str
    password: str
    context_path: Path
    cookies_path: Path


def safe_account_name(name: str) -> str:
    """把账号名转换成适合用作本地目录名的安全字符串。"""

    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    value = value.strip("._-")
    if not value:
        raise ValueError(f"账号名称不合法: {name!r}")
    return value


def _resolve_path(value: Any, *, base_dir: Path) -> Path:
    """解析配置中的路径；相对路径按配置文件所在目录计算。"""

    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path


def _read_secret(raw_account: dict[str, Any], key: str) -> str:
    """读取账号敏感字段，支持直接配置或通过 *_env 指向环境变量。"""

    if raw_account.get(key) is not None:
        return str(raw_account.get(key) or "")

    env_name = raw_account.get(f"{key}_env")
    if env_name:
        return os.getenv(str(env_name), "")

    return ""


def _normalize_raw_accounts(raw_accounts: Any) -> list[tuple[str, dict[str, Any]]]:
    """兼容对象和数组两种 accounts 写法，统一输出 (name, config)。"""

    if isinstance(raw_accounts, dict):
        accounts = []
        for name, raw_account in raw_accounts.items():
            if not isinstance(raw_account, dict):
                raise ValueError(f"账号配置 {name!r} 必须是对象")
            accounts.append((str(name), raw_account))
        return accounts

    if isinstance(raw_accounts, list):
        accounts = []
        for index, raw_account in enumerate(raw_accounts):
            if not isinstance(raw_account, dict):
                raise ValueError(f"第 {index + 1} 个账号配置必须是对象")
            name = raw_account.get("name") or raw_account.get("id")
            if not name:
                raise ValueError(f"第 {index + 1} 个账号缺少 name")
            accounts.append((str(name), raw_account))
        return accounts

    raise ValueError("accounts 必须是对象或数组")


def load_account_configs(config_path: Path = DEFAULT_CONFIG_PATH) -> tuple[list[AccountConfig], str | None]:
    """加载账号配置文件，并补齐默认 context/cookies 存储路径。"""

    config_path = config_path.expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"账号配置文件不存在: {config_path}")

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw_config, dict):
        raise ValueError("账号配置文件根节点必须是对象")

    base_dir = config_path.parent
    data_dir = _resolve_path(raw_config.get("data_dir", DEFAULT_DATA_DIR_NAME), base_dir=base_dir)
    raw_accounts = raw_config.get("accounts")
    if not raw_accounts:
        raise ValueError("账号配置文件缺少 accounts")

    accounts: list[AccountConfig] = []
    for name, raw_account in _normalize_raw_accounts(raw_accounts):
        safe_name = safe_account_name(name)
        # 未显式指定路径时，每个账号独立放到 accounts/<safe_name>/ 下。
        context_path = (
            _resolve_path(raw_account["context_path"], base_dir=base_dir)
            if raw_account.get("context_path")
            else data_dir / safe_name / "context.json"
        )
        cookies_path = (
            _resolve_path(raw_account["cookies_path"], base_dir=base_dir)
            if raw_account.get("cookies_path")
            else data_dir / safe_name / "cookies.json"
        )
        accounts.append(
            AccountConfig(
                name=name,
                username=_read_secret(raw_account, "username"),
                password=_read_secret(raw_account, "password"),
                context_path=context_path,
                cookies_path=cookies_path,
            )
        )

    active_account = raw_config.get("active_account")
    return accounts, str(active_account) if active_account else None


def select_account_configs(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    account_name: str | None = None,
    all_accounts: bool = False,
) -> list[AccountConfig]:
    """按命令行参数选择一个账号，或在 --all 模式下返回全部账号。"""

    accounts, active_account = load_account_configs(config_path)
    if all_accounts:
        return accounts

    selected_name = account_name or active_account or accounts[0].name
    for account in accounts:
        if account.name == selected_name:
            return [account]

    names = ", ".join(account.name for account in accounts)
    raise ValueError(f"未找到账号 {selected_name!r}，可用账号: {names}")

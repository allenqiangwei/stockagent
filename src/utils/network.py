"""网络工具模块 - 代理管理等网络相关功能"""

import os
import threading
from contextlib import contextmanager
from typing import Generator


# 代理相关的环境变量
PROXY_ENV_VARS = [
    'HTTP_PROXY', 'http_proxy',
    'HTTPS_PROXY', 'https_proxy',
    'ALL_PROXY', 'all_proxy',
]

# 用于设置 NO_PROXY 的变量
NO_PROXY_VARS = ['NO_PROXY', 'no_proxy']

# 线程安全的引用计数：多个线程可以同时处于 no_proxy 状态，
# 只有第一个进入时禁用代理，最后一个退出时恢复代理。
_proxy_lock = threading.Lock()
_no_proxy_refcount = 0
_saved_proxies_global: dict = {}
_saved_no_proxy_global: dict = {}


def _clear_requests_proxy_cache():
    """清除 requests/urllib3 的代理缓存

    requests 和 urllib3 会缓存代理设置，简单删除环境变量不够。
    需要清除其内部缓存才能真正绕过代理。
    """
    try:
        import urllib3
        # 清除 urllib3 的 poolmanager 缓存
        if hasattr(urllib3, 'poolmanager'):
            pm = urllib3.poolmanager
            if hasattr(pm, 'ProxyManager'):
                # 重置默认代理设置
                pass
    except ImportError:
        pass

    try:
        import requests
        # 清除 requests 的 Session 缓存
        # requests.Session 会根据环境变量设置代理
        # 通过 trust_env=False 可以忽略环境变量，但我们通过设置 NO_PROXY=* 来实现
    except ImportError:
        pass


@contextmanager
def no_proxy() -> Generator[None, None, None]:
    """临时禁用系统代理的上下文管理器（线程安全）

    使用引用计数实现：第一个线程进入时禁用代理，最后一个线程退出时恢复。
    多个线程可以同时处于 no_proxy 状态，不会互相干扰。

    Usage:
        with no_proxy():
            # 这里的请求不会使用代理
            response = requests.get("http://example.com")
    """
    global _no_proxy_refcount, _saved_proxies_global, _saved_no_proxy_global

    with _proxy_lock:
        _no_proxy_refcount += 1
        if _no_proxy_refcount == 1:
            # 第一个线程进入：保存并禁用代理
            _saved_proxies_global = {}
            for var in PROXY_ENV_VARS:
                if var in os.environ:
                    _saved_proxies_global[var] = os.environ[var]
                    del os.environ[var]

            _saved_no_proxy_global = {}
            for var in NO_PROXY_VARS:
                if var in os.environ:
                    _saved_no_proxy_global[var] = os.environ[var]
                os.environ[var] = '*'

            _clear_requests_proxy_cache()

    try:
        yield
    finally:
        with _proxy_lock:
            _no_proxy_refcount -= 1
            if _no_proxy_refcount == 0:
                # 最后一个线程退出：恢复代理
                for var, value in _saved_proxies_global.items():
                    os.environ[var] = value

                for var in NO_PROXY_VARS:
                    if var in _saved_no_proxy_global:
                        os.environ[var] = _saved_no_proxy_global[var]
                    elif var in os.environ:
                        del os.environ[var]

                _saved_proxies_global = {}
                _saved_no_proxy_global = {}


@contextmanager
def with_proxy() -> Generator[None, None, None]:
    """临时恢复系统代理的上下文管理器（线程安全）

    某些 API（如 AkShare）需要通过代理访问国内数据源。
    此上下文管理器会：
    1. 移除 NO_PROXY=* 设置
    2. 通知 requests 猴子补丁允许使用代理

    Usage:
        with with_proxy():
            df = ak.stock_zh_a_hist(...)
    """
    # 设置线程局部变量，通知 requests 补丁允许代理
    try:
        from src.dashboard.live_data_service import set_thread_proxy
        set_thread_proxy(True)
    except ImportError:
        pass

    with _proxy_lock:
        # 临时移除 NO_PROXY 设置
        saved = {}
        for var in NO_PROXY_VARS:
            if var in os.environ:
                saved[var] = os.environ.pop(var)

    try:
        yield
    finally:
        with _proxy_lock:
            # 恢复 NO_PROXY 设置
            for var, value in saved.items():
                os.environ[var] = value

        try:
            from src.dashboard.live_data_service import set_thread_proxy
            set_thread_proxy(False)
        except ImportError:
            pass


def disable_proxy_globally() -> dict:
    """全局禁用代理

    Returns:
        保存的原有代理设置，可用于后续恢复
    """
    saved_proxies = {}
    for var in PROXY_ENV_VARS:
        if var in os.environ:
            saved_proxies[var] = os.environ[var]
            del os.environ[var]
    return saved_proxies


def restore_proxy(saved_proxies: dict) -> None:
    """恢复代理设置

    Args:
        saved_proxies: 之前保存的代理设置
    """
    for var, value in saved_proxies.items():
        os.environ[var] = value


def get_current_proxy() -> dict:
    """获取当前代理设置

    Returns:
        当前的代理环境变量设置
    """
    proxies = {}
    for var in PROXY_ENV_VARS:
        if var in os.environ:
            proxies[var] = os.environ[var]
    return proxies

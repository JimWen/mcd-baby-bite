"""mcd-baby-bite 的异常类型。所有 message 均为面向用户的中文。"""
from __future__ import annotations

APPLY_URL = "https://open.mcd.cn/mcp"


class BabyBiteError(Exception):
    """基础异常。"""


class AuthError(BabyBiteError):
    """Token 缺失、无效或过期。"""


class RateLimitError(BabyBiteError):
    """HTTP 429 限流。"""


class TransportError(BabyBiteError):
    """网络错误或非预期的 HTTP 状态。"""


class FixtureMissingError(BabyBiteError):
    """离线模式下找不到对应的录制数据。"""


class McdBusinessError(BabyBiteError):
    """麦当劳接口返回的业务错误（code != 200）。"""

    def __init__(self, code, message: str):
        self.code = code
        self.message = message
        super().__init__(f"麦当劳接口返回错误 code={code}：{message}")

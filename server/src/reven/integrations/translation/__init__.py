"""百度与阿里机器翻译的 API 客户端和安全错误类型。"""


class TranslationError(Exception):
    """机翻 API 调用失败（错误信息不含任何密钥）。"""

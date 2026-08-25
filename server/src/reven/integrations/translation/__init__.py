"""机器翻译集成：腾讯/百度/阿里三家机翻的 API 客户端与连接测试适配器。"""


class TranslationError(Exception):
    """机翻 API 调用失败（错误信息不含任何密钥）。"""

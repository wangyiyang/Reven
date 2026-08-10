"""腾讯云对象存储集成。"""

from reven.integrations.tencent_cos.client import TencentCosClient
from reven.integrations.tencent_cos.configuration import TencentCosConfiguration, load_tencent_cos_configuration
from reven.integrations.tencent_cos.store import ArchivedAsset, TencentCosAssetStore, build_tencent_cos_asset_store

__all__ = [
    "ArchivedAsset",
    "TencentCosAssetStore",
    "TencentCosClient",
    "TencentCosConfiguration",
    "build_tencent_cos_asset_store",
    "load_tencent_cos_configuration",
]

# 品牌管理契约

## 范围
稿件发布已退役，品牌模块只管理档案、素材和已有渠道模板配置。
已删除正文模板应用、发布任务绑定、封面发布校验与 Notion VI Hub 导入。

## 保留行为
- 品牌档案和渠道模板以草稿、已发布、已归档版本保存；发布新版本归档旧版本。
- 模板发布前验证引用素材存在；模板目前不触发任何内容发布。
- 品牌素材上传校验格式与大小，使用腾讯云 COS；按 SHA-256 去重。
- COS 未配置返回明确 503，非图片或不合法用途返回 422。
- 品牌素材存储协议定义于 brand/service.py，不能依赖退役的 content_sync/publishing。
- template_assets.py 只提取模板引用素材 ID，不负责渲染正文。

## 验证
server/tests/api/test_brand.py 覆盖档案/模板版本切换、引用素材缺失、上传与去重。
server/tests/migrations/test_retire_publishing_migration.py 验证保留品牌表、移除导入记录表。

# 实施与发布验证

## 最终实现

- 按最新 main 的 #128/#129 基线适配，不恢复稿件发布、Notion、jobs/outbox。
- 统一 reven.notifications、RSS 汇总/审核、真实手动测试与 Actions 部署通知到 feishu_bot。
- 删除 Webhook provider/UI/API/客户端；0022_remove_feishu_webhook 接续 0021_retire_publishing。
- 保留 RSS 实际运行的独立审核尝试、同日完成缓存与每日重试行为。
- 密钥加密保存；接收人来自当前应用，空名单和任一发送失败均不得报告成功。

## 最终本地质量检查

- 后端全量 596 项测试通过，覆盖率 87.26%（门禁80%）；Ruff、格式检查227文件、Mypy128源文件通过。
- 前端全量180项测试通过，lint、TypeScript/Vite构建通过。既有MSW/构建体积提示未阻断验证。
- 所有数据库测试使用独立容器 reven-feishu-release-test-0921；全新schema已升至0022。
- 独立 check 未发现阻塞：唯一迁移head、前后端五项provider一致、无退役发布模块残留。

## 发布执行

用户已授权立即升级线上。使用GitHub Flow：功能分支PR通过后合并，再以新Tag触发完整CI、容器检查、镜像扫描与digest部署。
升级前保存数据库、运行卷、环境主密钥和旧镜像的私有备份；0021不可逆，旧版本恢复不能仅回滚镜像。
production环境部署通知Secrets已从线上加密配置安全同步，值未写入代码或输出。

升级前线上飞书文本和卡片发送证据见runtime-verification.md，最终上线证据在部署后记录。
原有dogfood-output不属于本任务，保留且不提交。此前旧基线的outbox续租实现随主线退役删除，旧测试计数不作为当前验收结果。

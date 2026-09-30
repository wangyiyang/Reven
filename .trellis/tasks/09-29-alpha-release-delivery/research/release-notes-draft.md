# GitHub Release notes 草稿（v0.5.0 开源 Alpha）

> 使用时机：tag 推送且 image job 产出 digest 后，用本稿创建 Release，把 DIGEST 占位替换为实际值。

---

Reven 首个开源 Alpha：**面向独立创作者的单用户、自托管内容运营工作台**（RSS 内容发现 → 人工筛选 → 本地素材库 + 飞书通知）。

## 快速开始

- 源码构建（默认，Linux AMD64 + Docker Compose ≥ 2.24.4）：[自托管指南](https://github.com/wangyiyang/Reven/blob/main/docs/self-hosting.md)
- 公开镜像（与生产同一产物，经 Trivy CRITICAL 门禁）：

```bash
REVEN_IMAGE=ghcr.io/wangyiyang/reven@sha256:DIGEST
```

- 运维（升级/备份/恢复/回滚）：[运维指南](https://github.com/wangyiyang/Reven/blob/main/docs/self-hosting-operations.md)

## Alpha 已知限制

- 单用户单管理员，无注册流程，请勿作为多租户服务暴露公网
- RSS 发现每日 06:00（Asia/Shanghai）一次，首次安装次日才有候选
- AI 集成（翻译/Embedding/Qwen）未配置时降级运行，界面有明确提示
- 迁移 0021 不可降级；升级前必须备份
- 正式支持 Linux AMD64；ARM64 未验证

## 镜像与供应链

- 镜像 digest（ACR 与 GHCR 等价）：`sha256:DIGEST`
- SBOM：`reven-sbom.cdx.json`（Release 工件）
- 许可：Apache-2.0；第三方声明见 [THIRD_PARTY_NOTICES.md](https://github.com/wangyiyang/Reven/blob/main/THIRD_PARTY_NOTICES.md)
- 安全问题：[SECURITY.md](https://github.com/wangyiyang/Reven/blob/main/SECURITY.md)（私密漏洞报告入口已启用）

# Issue #115：仅发版执行容器镜像构建

## 目标

落实普通 PR 和 main push 不构建容器镜像、版本 tag 发版仍执行完整容器验证的约定，减少日常重复构建。

## 背景

- Issue：https://github.com/wangyiyang/Reven/issues/115。
- PR #98 只修改了生产发布触发器，CI 的 container 任务仍按路径过滤执行。
- 当前条件位于 `.github/workflows/ci.yml`：`inputs.full || needs.changes.outputs.container == 'true'`。
- `.github/workflows/release.yml` 的 quality-gate 在 tag push 时以 `full: true` 调用 CI，image 依赖 quality-gate 成功。
- 用户在已阅读原因、修复建议及风险后，要求创建工作树并开始处理；本任务按该已确认范围实施，无待定产品决策。

## 需求与验收

- 普通 PR/main CI 跳过 container，不构建 reven:test；前后端、renderer、migration 仍按既有路径条件执行。
- 发版完整 CI 继续执行 container、沙箱验证、扫描、SBOM，quality-gate 成功后才构建推送正式镜像。
- 清理由条件修改产生的未使用 container 路径过滤与 changes 输出。
- 回归测试覆盖 full 默认 false、container 只依赖 full、发版调用 full true，以及普通检查保持原有过滤行为；先确认回归测试在修复前失败。
- 运维文档明确 tag push、GitHub Release 事件、手动部署的区别，说明容器错误会延后到发版发现。
- 相关测试、Python lint/格式/类型检查、工作流语法检查通过，或明确记录可验证的环境限制。

## 变更边界

- `.github/workflows/ci.yml`：在真正决定容器运行的 job 条件处修复，仅保留 `inputs.full`。
- `server/tests/security/test_deployment_automation.py`：更新失效路径断言并加入 CI/发布边界的回归覆盖。
- `docs/runbook.md`：修正第 6/7/供应链验证相关说明，准确反映日常与发版职责。
- `.trellis/spec/reven-server/backend/ci-release-contract.md` 及 index：保存本次 CI/发版可执行约定，防止再次遗漏独立构建入口。
- 不改变 release 生产任务、版本校验、部署或回滚实现，不增加额外构建开关，不优化发版内部重复构建，不修改远端分支保护。

## 已接受的取舍

容器打包、运行环境、沙箱及镜像漏洞问题延后至发版发现。普通语言层检查仍照常执行。

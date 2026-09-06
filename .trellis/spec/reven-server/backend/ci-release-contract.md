# CI 与发版镜像构建契约

## 1. 范围与触发

维护 `.github/workflows/ci.yml`、`release.yml` 或部署结构测试时遵守本契约。
Issue #115 修复了仅限制生产发布入口、却遗漏普通 CI 测试镜像构建的问题。

## 2. 调用签名

- CI：`pull_request` 指向 main、`push` 到 main，以及 `workflow_call`。
- `workflow_call.inputs.full`：可选 boolean，默认 `false`。
- 发版：`push.tags: ['v*']`；quality-gate 调用 CI 并传入 `full: true`。
- 手动：`workflow_dispatch(operation: deploy | rollback, version?: string)` 使用已有镜像。

## 3. 行为契约

- `jobs.container.if` 必须为 `inputs.full`，不得再由变更路径启用。
- 普通 PR/main CI 不构建 `reven:test`；backend、migration、frontend、renderer 保留各自的路径过滤及 full 覆盖。
- changes 不输出 container，也不维护 container 路径过滤。
- 发版完整 CI 保留容器运行、沙箱、SBOM 和漏洞检查。正式 image 任务依赖 quality-gate 成功。
- 正式镜像构建和自动部署由 tag push 触发，不监听 `release.published`。
- 手动部署和回滚不构建镜像；不得为验证本契约实际触发生产部署。

## 4. 验证与失败矩阵

| 场景 | 容器任务 | 后续行为 |
| --- | --- | --- |
| PR/main push，任意改动路径 | skipped | 其他检查按路径执行 |
| workflow_call，未传 full 或 full=false | skipped | 其他检查按路径执行 |
| 发版 workflow_call，full=true | 执行 | 完整质量检查通过后允许 image |
| quality-gate 失败 | 发版失败 | 不运行 image，不自动部署 |
| 手动部署或回滚 | 不运行 quality-gate/image | 解析已有镜像或上一健康镜像 |

GitHub 对 job-level `if` 跳过的检查按成功处理，即使它仍列为 required check，也不会阻止合并。
来源：[GitHub 条件执行文档](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-jobs-with-conditions)。

## 5. 正常、默认与错误示例

- 正常：推送版本 tag，完整 CI 验证测试镜像后，生产任务构建并推送正式镜像。
- 默认：仅修改 `web/**` 的 PR 运行 frontend 检查，container 跳过。
- 错误：给 container 条件追加任意路径匹配分支，导致日常代码改动再次构建镜像。

仅发版构建会将容器打包、运行环境和漏洞问题延后至发版发现；这是本契约的取舍。

## 6. 必须覆盖的测试

`server/tests/security/test_deployment_automation.py` 应验证：

- CI full 为 boolean 且默认 false，container 只由 full 启用。
- container 路径过滤及输出已移除，其他任务仍具备各自的路径条件。
- 发版调用传入 full true、image 依赖 quality-gate，并保留 tag 与手动通道条件。
- 原有容器基础设施同步验证、部署脚本 smoke 检查仍存在。

修改条件时先确认新增回归断言在旧配置失败，再验证修复通过；工作流同时通过 actionlint。
不要只检查 release 触发器就推断仓库内其他工作流不构建镜像。

## 7. 错误与正确写法

```yaml
# 错误：任何匹配路径都会在普通 CI 构建镜像
if: inputs.full || needs.changes.outputs.container == 'true'

# 正确：由发版调用显式启用完整验证
if: inputs.full
```

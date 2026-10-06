# 执行计划：仓库个人绑定清理

分支：`chore/repo-personal-binding-cleanup`（从 main 拉出，PR 合回）。

1. **建分支**：`git switch -c chore/repo-personal-binding-cleanup`。
2. **.gitignore**：追加 `workspace/`、`.coverage`、`sync-to-notion.sh`。
   - 验证：`git check-ignore -v workspace/ server/.coverage sync-to-notion.sh`。
3. **config.py 默认值**：`http://dev.wangyiyang.cc:3001` → `http://localhost:8080`；`test_config.py:20` 断言同步。
   - 验证：`uv run pytest server/tests/test_config.py -q`。
4. **根 .env.example**：PUBLIC_BASE_URL/COS_BUCKET/COS_PUBLIC_BASE_URL 占位化；REVEN_IMAGE 去个人命名空间 + 注释。
   - 验证：`git diff` 人工核对无其余个人值。
5. **scripts/smoke.sh**：默认 BASE_URL → `http://localhost:8080`。
   - 验证：`bash -n scripts/smoke.sh`。
6. **残留复查**：`git grep -n "dev.wangyiyang.cc\|wangyiyang"` 按允许清单过滤后零命中。
   - 验证：输出为空。
7. **质量门**：`trellis-check` 子代理全量检查本次 diff。
8. **提交并开 PR**（conventional commit：`chore: 清理仓库个人环境绑定`），关联 Issue #127。

## 回滚点

任一步骤验证失败即停在本步骤修复；改动全部为字符串/模板级，回滚 = revert 单个 commit。

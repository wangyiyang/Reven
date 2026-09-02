# PRD · #103 财务连续删除一致性

## Goal

消除财务删除的假成功窗口，让 UI 展示始终以服务端已确认的删除结果为准。

## Confirmed Facts

- 当前 `deleteMutation.onMutate` 在 DELETE 请求完成前就从所有 finance entries 查询缓存移除记录。
- 对话框在 mutation pending 时会阻止重复确认，但自动化点击旧元素仍可能观察到客户端空态而服务端未完成。
- `onError` 会回滚、`onSettled` 会失效查询；现有测试只覆盖单条乐观删除和失败回滚，未覆盖连续删除。

## Requirements

- 取消财务删除的乐观移除；DELETE 204 后再失效列表与汇总查询并关闭对话框。
- pending 期间保留目标行、禁用重复确认；失败时保留数据并展示错误。
- 增加多条记录快速顺序删除的回归测试，断言每条 DELETE 都实际发出并最终与服务端列表一致。

## Acceptance Criteria

- [ ] 服务端响应挂起时目标行仍显示，不出现假空态。
- [ ] 每次成功删除恰好发出一个对应 DELETE；连续删除 3–4 条后 UI/服务端一致。
- [ ] DELETE 失败时行仍在、汇总不被错误清空且有错误提示。
- [ ] 财务前端测试通过。

## Out of Scope

- 批量删除 API 或撤销删除功能。

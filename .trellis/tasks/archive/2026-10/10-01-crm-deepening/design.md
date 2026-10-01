# 设计：CRM 客户跟进变更 module

## 结论

深化已有 CrmService，领域拥有输入校验与完整写操作。持久化是内部 seam；REST 与 MCP adapter 保留传输转换，读路径不重写。

## 文件与职责

- crm/inputs.py：移动六个现有创建/更新模型及约束、归一化；配对校验由领域拥有。
- crm/errors.py：固定客户/联系人/跟进缺失与行动日期错误，不携带 HTTP 或 MCP 信息。
- crm/service.py：输入模型 + 业务 ID，内部取实体、范围校验与提交，session/repository 变私有。
- api/schemas/crm.py：保留 Response，显式重导出原六个请求模型名称，JSON / OpenAPI 兼容。
- api/routes/crm.py 与 agent/tools_crm.py：删除写前查 ORM / 缺失接线，映射领域错误；读查询保持原状。
- tools_crm.py 当前 586 行。若接线删除后仍超 500，按客户、联系人、跟进三个完整 adapter 拆分；共用输入转换和错误标签只保留真实复用，注册点明确装配，不保留空聚合 facade。

## 业务 interface

CrmService 继续提供客户、联系人、跟进的 create/update/delete：create 接收已验证 input；update/delete 接收客户与资源 ID，内部完成范围查找。

创建联系人/跟进返回 (Customer, Contact/FollowUp)，供 MCP 保留客户名，REST 仅序列化资源。删除返回已加载实体供 MCP 保留原提示，REST 继续 204。返回 ORM 标量符合现有 expire_on_commit=False，不另建每实体 DTO。

精确方法草图及全部调用方见父任务 research/crm-delivery-plan.md。

## 不变量

- 更新用 exclude_unset=True，保留未提供 / 显式 null / 空串归一的不同含义。
- 行动与日期配对按合并后状态校验；合法的只改日期与非法的清空行动分别处理。
- MCP 先收集 contact_id / clear_contact 等全部字段再检查空更新，补复现和修复仅关联/解除跟进联系人的路径。
- customer_id + resource_id 范围查找在领域内完成，跨客户仍显示原缺失错误。
- 主联系人切换、创建历史与 set_as_current 保持一次提交；修改/删除历史不改当前计划；删除联系人保留快照。
- 验证失败不提交；已有 session context 负责 rollback，数据库异常显式传播。

## 测试与取舍

共享 interface 用 PostgreSQL 检查缺失/范围、部分更新、历史/当前计划、主联系人/快照与失败无副作用；保留 HTTP/MCP 的参数、错误和中文结果覆盖。规则测试迁移采用 replace-don't-layer。

不改数据库、事务次数或读查询，不增加通用 CRUD、锁、protocol 或仅为旧内部测试保留的 facade。回滚本项原子改动即可，无迁移。

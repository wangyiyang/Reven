# 设计：会话模型身份 module

## 结论

深化现有 AgentService，三个业务操作为 model_state / use_model / chat，不添加另一层 facade。它与 runtime 同寿命，REST 和飞书复用 app.state.agent_service；override 以外部 session_id 为键，主循环内存持有。

## Interface 与结果

- model_state(session_id) 返回不可变 SessionModelState：available_refs、default_ref、current_ref、is_override、pending_default_ref。
- use_model(session_id, model_ref) 验证可用选择；生效默认清 override，其他有效模型写入 override；失败保留原选择。
- chat(message, session_id=None) 返回不可变 AgentTurn：session_id、response、model_ref、is_override；REST 仅输出既有 session_id / response，不扩展 JSON。
- chat 进入 runtime 前捕获本轮选择和身份；执行中收到切换不能让已开始回答的落款改变。

具体类型草图、错误矩阵与九个组合场景见父任务 research/session-plan.md。

## 模型语义

生效 default_ref 只取 runtime.default_model_ref 的启动快照，现读 registry 的 is_default 是已保存配置。

- 保存默认与生效默认不同：current 仍表示生效模型；list / current 补“重启后默认”提示，不宣称已热更新。
- 启动 A，保存默认改 B：use B 为明确 override，use A 恢复实际默认。即使现读表不再包含 A，既有主 harness 的 A 仍作为恢复选项。
- 已选 B 后禁用/移除 B：调用明确失败、A 零调用、选择保留；用户显式恢复才用 A。
- override 调用失败归一为现有模型不可用错误，默认错误原样传播；日志只带稳定 ref / type / code。
- 未配置和启动失败保留已有先决条件，不暗中启动附加模型绕开主实例。

## 文件与职责

- agent/service.py：两个结果类型、三操作、选择与本轮生效身份；直接复用 runtime / credentials，不新增 protocol / session store。
- app.py：startup 创建唯一业务对象，传同一对象给飞书；停止仍沿原 runtime 清理链，无新 start/close 包装。
- api/dependencies.py / routes/agent.py：依赖拿共享对象，适配内部结果到既有 JSON；没有“缺失就临时再 new”的退路。
- feishu_bot/chat_dispatcher.py：删除 _overrides/_override_key 与 registry 默认判断；用同一 IM 外部 session_id 调三操作，按 AgentTurn 身份渲染。
- feishu_bot/commands.py：保留解析/用法/中文意义，消费去凭证结果；只有默认漂移场景补重启提示。
- runtime/config：保留池、per-ref 首用锁、resolver、别名、dsh，原则上不改产品机制。resolver 有现读可用性语义，不能当空转发删掉。

## 生命周期、测试与回滚

所有状态读写仍在主循环，完成现读后的写入不 await；不加全局锁或同会话执行锁。进程重启重新创建对象，override 丢失是已有取舍，别名仍由 runtime 重铸。

真实 AgentService + runtime + fake harness 在同一 interface 验证选择、真实模型、恢复、重铸、禁用失败、默认漂移、执行中切换与关闭。保留 runtime 初始化/池/别名、配置真数据库、飞书语法/白名单/桥接和 REST 认证/错误测试；替换旧私有字典或转发参数断言，不复制状态机到 stub。

无热重建、持久化、前端选择、resume、历史策略或依赖变更。回滚本项原子改动即可。

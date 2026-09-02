# Implement · #104 财务现金口径

- [ ] 在 `server/tests/api/test_finance.py` 构造已收、应收、已付、应付、已记录记录，先断言严格现金口径。
- [ ] 在 `FinanceRepository.summary` 的 income/expense case 中加入 kind + status 条件。
- [ ] 更新 finance 页面副标题与三张核心卡名，补前端文案回归测试。
- [ ] 运行 server finance 测试、web finance 测试、web lint/build。
- [ ] 由 `trellis-check` 复核 API 语义、边界状态和测试有效性。

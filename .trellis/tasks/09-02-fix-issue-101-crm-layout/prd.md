# PRD · #101 CRM 详情页排版

## Goal

在 1280px 桌面视口完整、稳定地展示 CRM 日期、邮箱和主要联系人标签。

## Confirmed Facts

- 详情页在 `xl` 时把联系人和跟进卡各分配半宽；跟进表单内部再使用三等分列，日期输入可用宽度不足。
- 联系方式使用 `break-all`，会把邮箱末尾单字符拆行。
- “设为主要联系人”及 `Badge` 都未声明不换行。

## Requirements

- 为跟进日期列提供足够最小宽度或调整网格比例，日期文本和图标不得重叠。
- 联系方式采用 `overflow-wrap:anywhere`/`break-words` 级别策略，不强制逐字符断词。
- 主要联系人复选框标签和徽标保持单行，并允许周边布局合理换行。

## Acceptance Criteria

- [ ] 1280px 视口完整显示 `YYYY/MM/DD` 日期及日历图标。
- [ ] `zhangsan@example.com` 不在普通可用宽度下拆成孤立字符。
- [ ] 两处“主要联系人”文案均不拆词。
- [ ] 组件测试和浏览器截图回归通过。

## Out of Scope

- 重设 CRM 信息架构或移动端布局。

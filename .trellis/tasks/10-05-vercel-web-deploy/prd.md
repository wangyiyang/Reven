# web 部署 Vercel（第一期：静态托管 + /api 代理）

## Goal

将 web 前端部署到 Vercel：新增 vercel.json（SPA rewrite + /api 反向代理到现有 server），验证构建产物可用，补充部署文档。对应 issue #120 第一期。

关联 issue：https://github.com/wangyiyang/Reven/issues/120
分支：`issue/gh-120-deploy-vercel-web-server-serverless`

## 背景与仓库证据

- web 是 React 19 + Vite SPA（`tsc -b && vite build`），纯静态产物。
- 前端所有 API 调用走相对路径 `/api`（`web/src/lib/api.ts:22`），cookie 会话 + `X-Reven-CSRF` 头（`web/src/lib/api.ts:21`），同源代理即可，无 CORS 问题。
- 本地开发代理：`web/vite.config.ts` 中 `server.proxy["/api"] -> http://127.0.0.1:8000`，Vercel rewrite 与之同构。
- server 部署在现有 VPS（dev.wangyiyang.cc），本期不动 server。

## Requirements

- 在 `web/` 下新增 `vercel.json`，包含：
  - `/api/(.*)` rewrite 到现有 server（目标地址可通过 Vercel 环境变量或固定值配置，需在文档中说明）；
  - SPA fallback：其余路径 rewrite 到 `/index.html`；
  - 注意 rewrite 顺序（`/api` 规则必须先于 SPA fallback）。
- 不改前端业务代码（零改造原则）。
- 补充部署文档：Vercel 项目配置要点（root directory = `web`、build command、output directory、环境变量）。
- server 侧 serverless 化属于第二期，不在本任务范围。

## Acceptance Criteria

- [ ] `web/vercel.json` 存在且规则正确：`/api/*` 代理优先于 SPA fallback。
- [ ] `pnpm build`（web 目录）通过，产物为纯静态文件。
- [ ] 部署文档落档（docs/ 下），含 Vercel 项目配置步骤与 /api 目标说明。
- [ ] 前端 lint / type-check / test 不回归。

## Notes

- 验证 Vercel 实际部署需要用户在自己账号操作（导入仓库、绑域名），本任务交付仓库侧全部配置与文档。

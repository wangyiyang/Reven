# web 部署 Vercel（历史配置）

> 2026-10-06 部署决策：维护者前后端恢复统一 VPS 发布，当前配置与验收以
> [运行手册](runbook.md)为准。`web/vercel.json` 声明 `git.deploymentEnabled: false`，
> 作为未来 Root Directory 为 `web` 时的配置保护。当前项目未连接 Git，没有持续
> Git 自动发布；这不等于平台自动部署开关已关闭。
> 下文保留 v0.7.1 的混合部署记录，旧项目/部署及其 Origin
> 白名单作为故障回退入口，不代表当前推荐入口；本次不做 serverless 迁移。

**历史形态：web 前端部署到 Vercel（纯静态托管），server 留在 VPS。** 前端所有 API 调用走相对路径 `/api`，通过 `web/vercel.json` 的 rewrite 将 `/api/*` 反向代理到现有 server，其余路径回退到 `index.html` 支持 SPA 路由。与本地开发时 `vite.config.ts` 中的 `server.proxy["/api"]` 同构，无 CORS 问题。

本文对应 issue [#120](https://github.com/wangyiyang/Reven/issues/120) 第一期（静态托管 + /api 代理），改动分支为 `issue/gh-120-deploy-vercel-web-server-serverless`。原第二期 serverless 设想不属于本次统一 VPS 部署范围。

## 1. 工作原理

`web/vercel.json` 中的 rewrite 规则按数组顺序匹配，命中即停：

| 顺序 | source | destination | 作用 |
| --- | --- | --- | --- |
| 1 | `/api/(.*)` | `https://dev.wangyiyang.cc/api/$1` | API 请求代理到现有 server，保留原始路径 |
| 2 | `/(.*)` | `/index.html` | SPA fallback，其余路径交给前端路由 |

`/api` 规则必须排在 SPA fallback 之前，否则 API 请求会被回退到 `index.html`。Vercel 对命中真实静态文件（如构建产物中的 JS/CSS）的请求不做 rewrite，因此 SPA fallback 不影响静态资源加载。

## 2. Vercel 项目配置

以下保留历史的 web/Vite 配置方法，不代表当前项目设置。2026-10-06 的平台只读检查显示
`reven-web` 的 Root Directory 为 `.`（API 的 rootDirectory=null）、Node.js 为 24.x，
Git link=null，平台 createDeployments 仍为 enabled。当前没有持续 Git 自动发布，本次
无需改平台设置，保留现有手动部署。`web/vercel.json` 的禁用声明仅在项目实际读取该
文件时生效，不能用它宣称当前平台开关已关闭。将来重新连接 Git 时必须先核对 Root
Directory 与配置路径；如需故障处置中重新发布，还须复核其与 API 版本的兼容性。

1. **Import 仓库**：Add New → Project，选择 `wangyiyang/Reven` 仓库。
2. **Root Directory**：点击 Edit，设置为 `web`。
3. **Framework Preset**：选择 **Vite**（设置 Root Directory 后通常自动识别）。
4. **Build Command**：`pnpm build`（默认即可；该命令实际执行 `tsc -b && vite build`）。
5. **Output Directory**：`dist`（Vite 默认值，通常自动识别，无需在 vercel.json 中显式声明）。
6. **Install Command**：保持默认。Vercel 识别根目录的 pnpm-workspace，会自动安装 workspace 依赖。
7. 原流程点击 **Deploy**；当前保留已有部署，不主动重新发布。

历史构建要求 Node `>= 22.22.2`；恢复 Vercel 发布时应核对实际 Node 版本与仓库要求，不沿用过期的项目设置假设。

## 3. /api 代理目标

当前代理目标固定写在 `web/vercel.json` 第一条 rewrite 的 `destination` 中，指向 **dev 环境**：

```
https://dev.wangyiyang.cc/api/$1
```

更换环境（如指向生产 server）时，修改 `web/vercel.json` 中该条规则的 `destination` 并重新部署即可。注意保留路径中的 `/api/$1`，保证 `/api/xxx` 被代理到 `<目标>/api/xxx`。

server 使用 cookie 会话并校验 `X-Reven-CSRF` 头与 `Origin`。浏览器始终访问同源（Vercel 域名），cookie 可正常种植；但写请求携带的 `Origin` 是 Vercel 域，与 server 的 `PUBLIC_BASE_URL` 不一致，需在 server 侧配置 `REVEN_CSRF_ALLOWED_ORIGINS` 放行（见第 4 节），否则登录等写请求会被 403 拒绝。

## 4. server 放行 Vercel 域 Origin（必须）

前端部署到 Vercel 后，浏览器写请求的 `Origin` 为 Vercel 域（如 `https://reven-web-nine.vercel.app`）。server 的 `CsrfOriginMiddleware` 默认只放行 `Origin == PUBLIC_BASE_URL` 的写请求，不配置时登录等写请求返回 403（`csrf_validation_failed`）。

在 server 所在 VPS 的环境变量中追加 Vercel 域并重启容器：

```bash
# 多个前端域用逗号分隔
REVEN_CSRF_ALLOWED_ORIGINS=https://reven-web-nine.vercel.app
```

- 取值为 HTTP/HTTPS origin（不含路径），server 启动时逐项校验，非法值直接报错（fail-closed）；
- 修改后需重启 server 容器生效（更新流程见 `docs/runbook.md`）；
- 未设置该变量时行为与之前完全一致：仅校验 `PUBLIC_BASE_URL`。

## 5. 自有域名绑定与验收

1. 在 Project Settings → Domains 中添加自有域名，按提示配置 DNS（A/CNAME 记录），等待证书签发完成。
2. 验收方式：
   - 访问 `https://<自有域名>`，页面正常打开，刷新子路由（如直接打开某个前端路由地址）不 404，说明 SPA fallback 生效；
   - 登录后进入仪表盘，候选/素材等数据正常加载（浏览器开发者工具中 `/api/...` 请求返回 200），说明 `/api` 代理生效。

## 6. 本地验证

部署前可在仓库内验证构建产物为纯静态文件：

```bash
pnpm install
cd web
pnpm build
pnpm lint
```

构建产物输出在 `web/dist/`，仅包含 HTML、JS、CSS 等静态文件，不依赖任何 Node 运行时。

## 7. 统一 VPS 发布后的过渡

正式入口使用 `https://dev.wangyiyang.cc`。VPS 的 Caddy 同时服务 web 静态产物和 `/api`，
前后端来自同一应用镜像。VPS 验收完成后，再核验 Vercel 仍未连接 Git、不持续独立发布。

关闭自动部署使用官方 `git.deploymentEnabled: false` 配置，见
[Vercel Git Configuration](https://vercel.com/docs/project-configuration/git-configuration#turning-off-all-automatic-deployments)。
只有项目实际读取该配置时才会生效，不能用仓库文件代替平台核验。已有部署不会因此
删除；彻底删除项目或移除旧 Origin 白名单不属于此次补丁。

Vercel 域的 Cookie 不会转移到 VPS 域，首次使用 VPS 需要重新登录。若按原 v0.7.1 digest
回退，VPS 恢复纯 API 配置，页面入口回到原 Vercel 域；恢复及验收按运行手册执行。

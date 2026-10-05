# web 部署 Vercel

**结论：web 前端零改造即可部署到 Vercel（纯静态托管），server 仍留在现有 VPS 不动。** 前端所有 API 调用走相对路径 `/api`，通过 `web/vercel.json` 的 rewrite 将 `/api/*` 反向代理到现有 server，其余路径回退到 `index.html` 支持 SPA 路由。与本地开发时 `vite.config.ts` 中的 `server.proxy["/api"]` 同构，无 CORS 问题。

本文对应 issue [#120](https://github.com/wangyiyang/Reven/issues/120) 第一期（静态托管 + /api 代理），改动分支为 `issue/gh-120-deploy-vercel-web-server-serverless`。server 侧 serverless 化属于第二期，不在本文范围。

## 1. 工作原理

`web/vercel.json` 中的 rewrite 规则按数组顺序匹配，命中即停：

| 顺序 | source | destination | 作用 |
| --- | --- | --- | --- |
| 1 | `/api/(.*)` | `https://dev.wangyiyang.cc/api/$1` | API 请求代理到现有 server，保留原始路径 |
| 2 | `/(.*)` | `/index.html` | SPA fallback，其余路径交给前端路由 |

`/api` 规则必须排在 SPA fallback 之前，否则 API 请求会被回退到 `index.html`。Vercel 对命中真实静态文件（如构建产物中的 JS/CSS）的请求不做 rewrite，因此 SPA fallback 不影响静态资源加载。

## 2. Vercel 项目配置

在 Vercel 控制台执行一次即可，仓库侧配置已全部就绪：

1. **Import 仓库**：Add New → Project，选择 `wangyiyang/Reven` 仓库。
2. **Root Directory**：点击 Edit，设置为 `web`。
3. **Framework Preset**：选择 **Vite**（设置 Root Directory 后通常自动识别）。
4. **Build Command**：`pnpm build`（默认即可；该命令实际执行 `tsc -b && vite build`）。
5. **Output Directory**：`dist`（Vite 默认值，通常自动识别，无需在 vercel.json 中显式声明）。
6. **Install Command**：保持默认。Vercel 识别根目录的 pnpm-workspace，会自动安装 workspace 依赖。
7. 点击 **Deploy**。

若构建因 Node 版本失败，在 Project Settings → General → Node.js Version 中选择 **22.x**（仓库 `engines` 要求 `node >= 22.22.2`）。

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

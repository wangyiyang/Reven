import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"

export const server = setupServer(
  http.get("/api/rss/runs/latest", () =>
    HttpResponse.json({ code: "RSS_RUN_NOT_FOUND", message: "暂无运行记录" }, { status: 404 })),
  // 集成页渲染飞书卡片即拉取绑定列表；默认空列表，用例按需 server.use 覆盖
  http.get("/api/integrations/feishu_bot/bindings", () => HttpResponse.json([])),
)

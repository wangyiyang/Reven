import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"

export const server = setupServer(
  http.get("/api/rss/runs/latest", () =>
    HttpResponse.json({ code: "RSS_RUN_NOT_FOUND", message: "暂无运行记录" }, { status: 404 })),
)

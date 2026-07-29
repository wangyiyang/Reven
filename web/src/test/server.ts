import { HttpResponse, http } from "msw"
import { setupServer } from "msw/node"

export const server = setupServer(
  http.get("/api/system/egress-ip", () => HttpResponse.json({ available: true, ip: "203.0.113.8" })),
)

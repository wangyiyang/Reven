import { Route, Routes } from "react-router-dom"

import { AppShell } from "@/components/app-shell"
import { routes, type RouteDef } from "@/routes"

export function App() {
  return (
    <Routes>
      {routes.filter((def) => def.bare).map(renderRoute)}
      <Route element={<ShellRoutes />} path="*" />
    </Routes>
  )
}

function ShellRoutes() {
  return (
    <AppShell>
      <Routes>{routes.filter((def) => !def.bare).flatMap(expandRoute).map(renderRoute)}</Routes>
    </AppShell>
  )
}

// 绝对 path 的子路由（导航分组）提升为兄弟路由平铺注册；
// 相对 path / index 的子路由留在父级嵌套渲染
function expandRoute(def: RouteDef): RouteDef[] {
  const flat = def.children?.filter((child) => child.path?.startsWith("/")) ?? []
  const nested = def.children?.filter((child) => !child.path?.startsWith("/"))
  return [{ ...def, children: nested }, ...flat]
}

function renderRoute(def: RouteDef) {
  if (def.index) return <Route element={def.element} index key="index" />
  return (
    <Route element={def.element} key={def.path} path={def.path}>
      {def.children?.map(renderRoute)}
    </Route>
  )
}

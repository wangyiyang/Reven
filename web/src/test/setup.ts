import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll } from "vitest"

import { server } from "./server"

beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
beforeAll(() => {
  Element.prototype.hasPointerCapture ??= () => false
  Element.prototype.setPointerCapture ??= () => undefined
  Element.prototype.releasePointerCapture ??= () => undefined
  Element.prototype.scrollIntoView ??= () => undefined
  // jsdom 无 ResizeObserver：打桩为 no-op（测试用 scroll 事件驱动更新）
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

// Node ≥26 内置的实验性 localStorage 在未提供 --localstorage-file 时存在但不可用，
// 会遮蔽 jsdom 注入的实现（全局 localStorage 为 undefined）。测试环境在检测到不可用时
// 兜底为内存实现，使测试套件与本地 Node 版本解耦（CI 固定在 Node 22，不受影响）。
class MemoryStorage implements Storage {
  private readonly store = new Map<string, string>()

  get length(): number {
    return this.store.size
  }

  clear(): void {
    this.store.clear()
  }

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

function localStorageUsable(): boolean {
  try {
    const probe = "__reven_storage_probe__"
    globalThis.localStorage.setItem(probe, "1")
    globalThis.localStorage.removeItem(probe)
    return true
  } catch {
    return false
  }
}

if (!localStorageUsable()) {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: new MemoryStorage(),
  })
}

export function todayInShanghai(): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date())
  const value = (kind: "year" | "month" | "day") => parts.find((part) => part.type === kind)?.value ?? ""
  return `${value("year")}-${value("month")}-${value("day")}`
}

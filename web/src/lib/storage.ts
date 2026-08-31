export function readLocal(key: string, fallback: string): string {
  try {
    const value = localStorage.getItem(key)
    return value ?? fallback
  } catch {
    return fallback
  }
}

export function writeLocal(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 测试环境或隐私模式下不可用，忽略
  }
}

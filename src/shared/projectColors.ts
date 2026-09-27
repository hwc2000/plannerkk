const saturation = 64
const lightness = 48

/** 프로젝트 id만으로 안정적인 색을 계산해 기존 localStorage 데이터도 자동 지원한다. */
export function projectColor(projectId?: string): string {
  if (!projectId) return '#87928c'
  let hash = 2166136261
  for (let index = 0; index < projectId.length; index += 1) {
    hash ^= projectId.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  const hue = (hash >>> 0) % 360
  return `hsl(${hue} ${saturation}% ${lightness}%)`
}

const saturation = 64
const lightness = 48

export const PROJECT_COLORS = ['#5b5bd6', '#2f80ed', '#0f9d8a', '#3f9142', '#d9822b', '#e5484d', '#d6409f', '#8e4ec6', '#6b7280']

const chosen = new Map<string, string>()

export function setProjectColors(projects: Array<{ id: string; color?: string }>) {
  chosen.clear()
  for (const project of projects) if (project.color) chosen.set(project.id, project.color)
}

export function projectColor(projectId?: string): string {
  if (!projectId) return '#87928c'
  return chosen.get(projectId) ?? autoProjectColor(projectId)
}

/** 프로젝트 id만으로 안정적인 색을 계산해 기존 localStorage 데이터도 자동 지원한다. */
export function autoProjectColor(projectId: string): string {
  let hash = 2166136261
  for (let index = 0; index < projectId.length; index += 1) {
    hash ^= projectId.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  const hue = (hash >>> 0) % 360
  return `hsl(${hue} ${saturation}% ${lightness}%)`
}

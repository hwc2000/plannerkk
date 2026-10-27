import type {
  MemoryCategory,
  MilestoneStatus,
  Project,
  ProjectStatus,
} from './types'

export const weekdayNames = ['일', '월', '화', '수', '목', '금', '토']

export const dateKey = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`

export const now = new Date()
export const TODAY = dateKey(now)

export const milestoneLabel: Record<MilestoneStatus, string> = {
  todo: '시작 전',
  in_progress: '진행 중',
  done: '완료',
  deferred: '미룸',
}

export const priorityLabel: Record<Project['priority'], string> = {
  high: '높음',
  medium: '보통',
  low: '낮음',
}

export const statusLabel: Record<ProjectStatus, string> = {
  active: '진행 중',
  completed: '완료',
  paused: '중지',
}

export const memoryLabel: Record<MemoryCategory, string> = {
  availability: '가용 시간',
  preference: '작업 성향',
  priority: '우선순위',
  context: '프로젝트 맥락',
}

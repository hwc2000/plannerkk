import type {
  CalendarEvent,
  Memory,
  MemoryCategory,
  Milestone,
  MilestoneStatus,
  Project,
  ProjectStatus,
} from './types'

export const weekdayNames = ['일', '월', '화', '수', '목', '금', '토']

export const dateKey = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`

export const now = new Date()
export const TODAY = dateKey(now)
const shiftDay = (days: number) =>
  dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + days))

export const seedProjects: Project[] = [
  {
    id: 'project-planner',
    title: 'AI 플래너 MVP',
    goal: '프로젝트·일정·AI 조율이 연결된 개인 플래너 완성',
    startDate: shiftDay(-12),
    dueDate: shiftDay(8),
    priority: 'high',
    status: 'active',
  },
  {
    id: 'project-portfolio',
    title: '포트폴리오 정리',
    goal: '핵심 결과물과 소개 자료 정리',
    startDate: shiftDay(-21),
    dueDate: shiftDay(9),
    priority: 'medium',
    status: 'active',
  },
]

export const seedMilestones: Milestone[] = [
  {
    id: 'milestone-schema',
    projectId: 'project-planner',
    title: 'DB 스키마 설계',
    startDate: TODAY,
    dueDate: shiftDay(4),
    estimatedHours: 4,
    status: 'in_progress',
  },
  {
    id: 'milestone-ui',
    projectId: 'project-planner',
    title: '화면 흐름 검토',
    startDate: TODAY,
    dueDate: TODAY,
    estimatedHours: 2,
    status: 'todo',
  },
]

export const seedEvents: CalendarEvent[] = [
  {
    id: 'event-class',
    title: '고정 수업',
    date: TODAY,
    startTime: '15:00',
    endTime: '17:00',
    isFixed: true,
  },
]

export const seedMemories: Memory[] = [
  {
    id: 'memory-1',
    content: '평일에는 오후 7시 이후에 집중 작업을 배치하는 편이에요.',
    category: 'availability',
    source: 'user',
    createdAt: TODAY,
  },
]

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

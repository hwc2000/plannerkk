export const answerLabels: Record<string, string> = { roles: '생활 형태', regularity: '생활 규칙성', barriers: '계획이 무너지는 이유', focusMinutes: '한 번의 집중 시간', dailyMinutes: '하루 여유 시간', energy: '집중이 잘되는 시간', recovery: '계획이 틀어졌을 때', constraints: '고정 일정', context: '추가 설명', scheduleStyle: '선호하는 계획 방식' }
export const options: Record<string, Array<[string,string]>> = {
  scheduleStyle: [['time_blocks','시간 지정형 · 18:30~19:00 공부'],['flexible_queue','작업량 지정형 · 공부 1시간, 운동 30분'],['unknown','아직 모르겠어요']],
  roles: [['student','학생'],['employee','직장인'],['job_seeker','취업 준비생'],['freelancer','프리랜서'],['other','그 외']],
  regularity: [['regular','대체로 규칙적'],['mixed','요일마다 다름'],['irregular','예측하기 어려움'],['unknown','잘 모르겠어요']],
  barriers: [['starting','시작이 어려움'],['overplanning','과도한 계획'],['distraction','집중력 저하'],['fatigue','피로'],['interruptions','갑작스러운 일'],['unclear','무엇부터 할지 모름'],['none','특별한 어려움 없음'],['unknown','잘 모르겠어요']],
  energy: [['morning','오전'],['afternoon','오후'],['evening','저녁·밤'],['variable','그때그때 다름'],['unknown','잘 모르겠어요']],
  recovery: [['replan','시간을 다시 배치'],['reduce','할 일을 줄임'],['continue','밀린 일을 건너뛰고 계속'],['abandon','그날 계획을 포기'],['unknown','잘 모르겠어요']],
}

export function formatAnswer(key: string, value: unknown): string {
  if (value === null || value === undefined) return '모름'
  if (Array.isArray(value)) return value.map(v => formatAnswer(key, v)).join(', ')
  const label = options[key]?.find(([code]) => code === value)?.[1]
  if (label) return label
  if (key === 'focusMinutes' || key === 'dailyMinutes') return `${String(value)}분`
  return String(value) || '없음'
}

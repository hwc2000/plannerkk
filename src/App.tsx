import { useState } from 'react'
import { ArrowRight, ArrowUp, Brain, CalendarDays, Check, ChevronLeft, ChevronRight, CircleAlert, CircleCheck, Clock3, Flame, LayoutDashboard, Menu, MessageCircle, MoreHorizontal, Plus, Settings2, Sparkles, Target, X } from 'lucide-react'
import './styles.css'

type CheckinMode = 'completed' | 'partial' | 'postponed' | null

type Task = {
  time: string
  title: string
  detail: string
  duration: string
  tone: 'violet' | 'lime' | 'orange'
}

const tasks: Task[] = [
  { time: '17:30', title: '핵심 기능 3개 정리', detail: '기획 문서의 기능 우선순위 확정', duration: '20분', tone: 'violet' },
  { time: '18:00', title: '화면 흐름 초안 작성', detail: '첫 계획 생성 → 체크인 흐름', duration: '25분', tone: 'lime' },
  { time: '18:35', title: '팀원 공유용 요약 작성', detail: '오늘 결정한 내용 5줄로 정리', duration: '20분', tone: 'orange' },
]

const reasonOptions = ['작업이 너무 커서 시작이 어려웠어요', '예상보다 시간이 오래 걸렸어요', '에너지·집중력이 부족했어요', '예정에 없던 일이 생겼어요']
const weekdayNames = ['일', '월', '화', '수', '목', '금', '토']
const calendarDays = Array.from({ length: 35 }, (_, index) => new Date(2026, 7, 30 + index))
const defaultCalendarPlans: Record<string, { label: string; tone: string }[]> = {
  '2026-09-07': [{ label: '백로그 정리', tone: 'slate' }],
  '2026-09-10': [{ label: '핵심 기능 3개', tone: 'violet' }, { label: '화면 흐름 초안', tone: 'lime' }],
  '2026-09-14': [{ label: '팀 피드백 정리', tone: 'orange' }],
  '2026-09-18': [{ label: '중간 점검', tone: 'violet' }],
}

function dateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function CalendarWorkspace() {
  const [selectedDate, setSelectedDate] = useState('2026-09-10')
  const [draft, setDraft] = useState('')
  const [customPlans, setCustomPlans] = useState<Record<string, string[]>>({})
  const selected = calendarDays.find((day) => dateKey(day) === selectedDate) ?? calendarDays[11]
  const selectedLabel = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' }).format(selected)

  function addPlan() {
    const trimmed = draft.trim()
    if (!trimmed) return
    setCustomPlans((plans) => ({ ...plans, [selectedDate]: [...(plans[selectedDate] ?? []), trimmed] }))
    setDraft('')
  }

  return (
    <section className="calendar-workspace" aria-label="월간 캘린더">
      <div className="calendar-intro">
        <div><p className="eyebrow">MONTHLY VIEW</p><h1>계획을 <em>한눈에</em> 놓아보세요.</h1><p>날짜를 고르고 짧은 계획을 적어두면, AI가 나중에 현실적인 흐름으로 다듬어줘요.</p></div>
        <button className="primary-button compact" onClick={() => setSelectedDate('2026-09-10')}><CalendarDays size={16} />오늘로 이동</button>
      </div>
      <div className="calendar-layout">
        <div className="month-card">
          <div className="month-card-head"><div><p className="section-kicker">SEPTEMBER 2026</p><h2>2026년 9월</h2></div><span className="month-hint">날짜를 눌러 계획 추가</span></div>
          <div className="weekday-row">{weekdayNames.map((day, index) => <span className={index === 0 ? 'sunday' : index === 6 ? 'saturday' : ''} key={day}>{day}</span>)}</div>
          <div className="month-grid">
            {calendarDays.map((day) => {
              const key = dateKey(day)
              const isCurrentMonth = day.getMonth() === 8
              const isSelected = key === selectedDate
              const plans = [...(defaultCalendarPlans[key] ?? []), ...(customPlans[key] ?? []).map((label) => ({ label, tone: 'custom' }))]
              return <button className={`calendar-cell ${!isCurrentMonth ? 'outside' : ''} ${isSelected ? 'selected' : ''}`} key={key} onClick={() => setSelectedDate(key)}><span className="calendar-date">{day.getDate()}</span><div className="calendar-pills">{plans.slice(0, 2).map((plan, index) => <span className={`calendar-pill ${plan.tone}`} key={`${plan.label}-${index}`}>{plan.label}</span>)}{plans.length > 2 && <small>+{plans.length - 2}개 더</small>}</div></button>
            })}
          </div>
        </div>
        <aside className="day-planner">
          <p className="section-kicker">DAY NOTE</p><h2>{selectedLabel}</h2><p className="day-planner-copy">이 날의 할 일을 짧게 적어두세요. 저장은 현재 화면에서만 반영되는 UI 프로토타입이에요.</p>
          <div className="selected-plan-list">{[...(defaultCalendarPlans[selectedDate] ?? []), ...(customPlans[selectedDate] ?? []).map((label) => ({ label, tone: 'custom' }))].map((plan, index) => <div key={`${plan.label}-${index}`}><i className={plan.tone} />{plan.label}</div>)}{!(defaultCalendarPlans[selectedDate]?.length || customPlans[selectedDate]?.length) && <span className="empty-day">아직 적어둔 계획이 없어요.</span>}</div>
          <label className="plan-field"><span>짧은 계획 추가</span><input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') addPlan() }} placeholder="예: 사용자 인터뷰 질문 5개" /></label>
          <button className="primary-button full" onClick={addPlan}><Plus size={16} />이 날짜에 추가</button>
          <p className="calendar-ai-note"><Sparkles size={14} />계획이 쌓이면 AI가 과한 날을 찾아 조정안을 제안해요.</p>
        </aside>
      </div>
    </section>
  )
}

const portfolioProjects = [
  { id: 'a', name: '프로젝트 A', group: '진행 중인 목표', start: '9월 10일', due: '9월 30일', elapsed: 25, progress: 21, elapsedText: '5 / 20일', status: 'watch', statusLabel: '주의', insight: '예상 진도보다 4%p 늦어요.', workload: '이번 주 3개 · 약 4시간 30분' },
  { id: 'b', name: '프로젝트 B', group: '진행 중인 목표', start: '9월 1일', due: '10월 1일', elapsed: 43, progress: 47, elapsedText: '13 / 30일', status: 'on-track', statusLabel: '정상', insight: '계획한 페이스보다 4%p 앞서 있어요.', workload: '다음 작업 2개 · 약 2시간' },
  { id: 'c', name: '프로젝트 C', group: '진행 중인 목표', start: '9월 5일', due: '9월 24일', elapsed: 32, progress: 12, elapsedText: '6 / 19일', status: 'risk', statusLabel: '조정 필요', insight: '선행 작업이 아직 시작되지 않았어요.', workload: '이번 주 재조율이 필요해요' },
  { id: 'd', name: '프로젝트 D', group: '시작 전 목표', start: '10월 1일', due: '11월 7일', elapsed: 0, progress: 0, elapsedText: '시작 전', status: 'planned', statusLabel: '시작 전', insight: '시작일에 맞춰 첫 작업을 제안할게요.', workload: '아직 계획을 만들지 않았어요' },
]

function PortfolioWorkspace() {
  const [selectedId, setSelectedId] = useState('a')
  const selected = portfolioProjects.find((project) => project.id === selectedId) ?? portfolioProjects[0]

  return (
    <section className="portfolio-workspace" aria-label="전체 계획">
      <div className="portfolio-intro"><div><p className="eyebrow">PLAN MAP</p><h1>전체 목표를 <em>함께</em> 조율해요.</h1><p>프로젝트별 실제 진도와 기간 경과를 비교해, 지금 조정이 필요한 목표부터 보여줘요.</p></div><button className="primary-button compact"><Plus size={16} />새 프로젝트</button></div>
      <div className="portfolio-summary">
        <div><span className="summary-icon violet"><Target size={17} /></span><p><strong>진행 중</strong><b>3</b><small>전체 프로젝트 6개</small></p></div>
        <div><span className="summary-icon orange"><CircleAlert size={17} /></span><p><strong>조정 필요</strong><b>2</b><small>이번 주 확인할 목표</small></p></div>
        <div><span className="summary-icon lime"><Clock3 size={17} /></span><p><strong>이번 주 가용 시간</strong><b>8시간 30분</b><small>고정 일정 제외</small></p></div>
        <button className="replan-button"><Sparkles size={16} /><span><strong>이번 주 재조율</strong><small>AI 제안 보기</small></span><ArrowRight size={16} /></button>
      </div>
      <div className="portfolio-layout">
        <div className="project-list-panel"><div className="project-list-head"><div><p className="section-kicker">ACTIVE PROJECTS</p><h2>진행 중인 목표</h2></div><button className="text-button">위험도순</button></div><div className="project-card-list">{portfolioProjects.map((project) => <button className={`project-progress-card ${project.status} ${selected.id === project.id ? 'selected' : ''}`} key={project.id} onClick={() => setSelectedId(project.id)}><div className="project-card-top"><span className={`status-chip ${project.status}`}>{project.statusLabel}</span><span>{project.start} 시작 · {project.due} 마감</span></div><div className="project-name-row"><h3>{project.name}</h3><ArrowRight size={16} /></div><div className="progress-pair"><div><span>기간 경과</span><strong>{project.elapsedText} · {project.elapsed}%</strong><i><b style={{ width: `${project.elapsed}%` }} /></i></div><div><span>실제 달성</span><strong>{project.progress}%</strong><i><b style={{ width: `${project.progress}%` }} /></i></div></div><p className="project-insight">{project.insight}</p></button>)}</div></div>
        <aside className={`project-detail-panel ${selected.status}`}><div className="detail-heading"><div><span className={`status-chip ${selected.status}`}>{selected.statusLabel}</span><h2>{selected.name}</h2></div><button aria-label="프로젝트 옵션"><MoreHorizontal size={18} /></button></div><p className="detail-date">{selected.start} 시작 · {selected.due} 마감</p><div className="detail-meter"><div><span>기간 경과율</span><strong>{selected.elapsedText} · {selected.elapsed}%</strong></div><i><b style={{ width: `${selected.elapsed}%` }} /></i><div><span>실제 달성률</span><strong>{selected.progress}%</strong></div><i className="actual"><b style={{ width: `${selected.progress}%` }} /></i></div><div className="detail-insight"><Sparkles size={16} /><div><strong>{selected.insight}</strong><p>{selected.workload}</p></div></div><div className="detail-actions"><button className="primary-button full"><Sparkles size={16} />조정안 만들기</button><button className="secondary-button">프로젝트 상세 보기</button></div><p className="detail-note">AI는 기간, 마일스톤, 고정 일정과 승인된 실행 기록을 바탕으로 제안만 만들어요.</p></aside>
      </div>
    </section>
  )
}

function App() {
  const [planOpen, setPlanOpen] = useState(false)
  const [checkinMode, setCheckinMode] = useState<CheckinMode>(null)
  const [checkinSaved, setCheckinSaved] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [activeView, setActiveView] = useState<'today' | 'calendar' | 'memory' | 'portfolio' | 'settings'>('today')
  const [dateOffset, setDateOffset] = useState(0)
  const [runningTask, setRunningTask] = useState(false)
  const [notice, setNotice] = useState('')
  const [chat, setChat] = useState('')
  const [chatReply, setChatReply] = useState('')

  const visibleDate = new Date(2026, 8, 10 + dateOffset)
  const dateLabel = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' }).format(visibleDate)
  const weekdayLabel = new Intl.DateTimeFormat('ko-KR', { weekday: 'long' }).format(visibleDate)

  function selectView(view: typeof activeView) {
    setActiveView(view)
    if (view === 'memory') setMemoryOpen(true)
    if (view === 'settings') setNotice('설정 화면은 다음 단계에서 연결할 수 있어요.')
  }

  function submitChat() {
    if (!chat.trim()) return
    setChatReply('좋아요. 지금 계획의 부담을 낮춰서 가장 먼저 시작할 수 있는 15분짜리 작업으로 다시 정리해볼게요.')
    setChat('')
  }

  function saveCheckin() {
    setCheckinMode(null)
    setCheckinSaved(true)
    window.setTimeout(() => setCheckinSaved(false), 3500)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Sparkles size={15} /></span><span>re:plan</span></div>
        <nav className="nav-list" aria-label="주요 메뉴">
          <button className={`nav-item ${activeView === 'today' ? 'active' : ''}`} onClick={() => selectView('today')}><LayoutDashboard size={18} />오늘</button>
          <button className={`nav-item ${activeView === 'calendar' ? 'active' : ''}`} onClick={() => selectView('calendar')}><CalendarDays size={18} />캘린더</button>
          <button className={`nav-item ${activeView === 'memory' ? 'active' : ''}`} onClick={() => selectView('memory')}><Brain size={18} />기억</button>
          <button className={`nav-item ${activeView === 'portfolio' ? 'active' : ''}`} onClick={() => selectView('portfolio')}><Target size={18} />전체 계획</button>
        </nav>
        <div className="sidebar-bottom">
          <button className={`nav-item ${activeView === 'settings' ? 'active' : ''}`} onClick={() => selectView('settings')}><Settings2 size={18} />설정</button>
          <div className="profile"><div className="avatar">H</div><div><strong>현우</strong><span>실행 중인 목표 1개</span></div><MoreHorizontal size={17} /></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" aria-label="메뉴" onClick={() => setNotice('메뉴는 화면 왼쪽에서 선택할 수 있어요.')}><Menu size={20} /></button>
          <div className="date-control"><button aria-label="이전 날짜" onClick={() => setDateOffset((value) => value - 1)}><ChevronLeft size={18} /></button><div><span>{dateLabel}</span><strong>{weekdayLabel}</strong></div><button aria-label="다음 날짜" onClick={() => setDateOffset((value) => value + 1)}><ChevronRight size={18} /></button></div>
          <div className="topbar-actions"><button className="icon-button" aria-label="집중 타이머" onClick={() => setNotice('25분 집중 타이머를 시작할 준비가 됐어요.')}><Clock3 size={18} /></button><button className="primary-button compact" onClick={() => setPlanOpen(true)}><Sparkles size={16} />AI와 계획 만들기</button></div>
        </header>

        {activeView === 'calendar' ? <CalendarWorkspace /> : activeView === 'portfolio' ? <PortfolioWorkspace /> : <>
        <section className="hero-row">
          <div>
            <p className="eyebrow">TODAY · 3 STEPS</p>
            <h1>오늘은 <em>작게</em> 시작해도 충분해.</h1>
            <p className="hero-description">졸업작품 기획을 위한 집중 블록 3개를 준비했어요. 첫 번째 작업은 20분이면 돼요.</p>
          </div>
          <div className="streak-card"><span className="streak-icon"><Flame size={19} /></span><div><strong>3일째 이어가는 중</strong><p>작은 완료가 쌓이고 있어요</p></div></div>
        </section>

        <section className="content-grid">
          <div className="timeline-panel">
            <div className="section-heading"><div><p className="section-kicker">TODAY'S FLOW</p><h2>오늘의 계획</h2></div><button className="text-button" onClick={() => setPlanOpen(true)}><Plus size={17} />계획 추가</button></div>
            <div className="timeline">
              <div className="now-line"><span>NOW</span><i /></div>
              {tasks.map((task, index) => (
                <article className="task-card" key={task.title}>
                  <div className="task-time">{task.time}</div>
                  <div className={`task-dot ${task.tone}`} />
                  <div className="task-main"><div className="task-title-row"><h3>{task.title}</h3><span className="duration"><Clock3 size={13} />{task.duration}</span></div><p>{task.detail}</p></div>
                  <div className="task-actions">
                    {index === 0 ? <button className="start-button" onClick={() => { setRunningTask(true); setNotice('첫 작업을 시작했어요. 끝나면 아래에서 체크인해 주세요.') }}><span />{runningTask ? '진행 중' : '시작하기'}</button> : <button className="check-button" aria-label="완료" onClick={() => setCheckinMode('completed')}><Check size={16} /></button>}
                    <button className="overflow-button" aria-label="더 보기" onClick={() => setNotice(`“${task.title}”의 일정 변경 기능은 다음 단계에서 연결할 수 있어요.`)}><MoreHorizontal size={18} /></button>
                  </div>
                  {index === 0 && <div className="quick-check"><button onClick={() => setCheckinMode('completed')}><CircleCheck size={15} />완료</button><button onClick={() => setCheckinMode('partial')}>일부 완료</button><button onClick={() => setCheckinMode('postponed')}>미룸</button></div>}
                </article>
              ))}
              <button className="add-slot" onClick={() => setPlanOpen(true)}><Plus size={16} />비어 있는 시간에 계획 추가</button>
            </div>
          </div>

          <aside className="coach-panel">
            <div className="coach-head"><div className="coach-orb"><Sparkles size={18} /></div><div><p className="section-kicker">AI COACH</p><h2>지금 막힌 게 있나요?</h2></div></div>
            <p className="coach-intro">계획을 줄이거나, 다음 행동 하나만 정해달라고 말해보세요.</p>
            <div className="suggestion-list"><button onClick={() => setChatReply('오늘 남은 시간 기준으로 계획을 더 작게 나눠볼게요. 우선 17:30–17:45에 핵심 기능 3개만 적어보는 건 어때요?')}>오늘 계획 너무 많은데 줄여줘 <ArrowUp size={15} /></button><button onClick={() => setChatReply('좋아요. 첫 작업의 최소 행동은 “기획 문서 열고 핵심 기능 후보 3개를 제목만 적기”예요.')}>지금 할 최소 행동 하나 정해줘 <ArrowUp size={15} /></button></div>
            {chatReply && <div className="coach-reply"><Sparkles size={15} /><p>{chatReply}</p></div>}
            <div className="chat-input"><textarea value={chat} onChange={(e) => setChat(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitChat() } }} placeholder="오늘 상황을 말해보세요" rows={2} /><button onClick={submitChat} aria-label="보내기"><ArrowUp size={17} /></button></div>
            <p className="privacy-note">AI는 승인된 기억과 오늘의 계획만 참고해요.</p>
          </aside>
        </section>

        {checkinSaved && <button className="memory-toast" onClick={() => setMemoryOpen(true)}><Brain size={17} /><span><strong>기억 후보가 생겼어요</strong><small>검토하고 저장 여부를 정할 수 있어요.</small></span><ChevronRight size={17} /></button>}
        </>}
      </main>

      {notice && <div className="notice-toast" role="status"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="알림 닫기"><X size={15} /></button></div>}

      {planOpen && <div className="modal-backdrop" onMouseDown={() => setPlanOpen(false)}><section className="plan-modal" onMouseDown={(e) => e.stopPropagation()}><button className="close-button" onClick={() => setPlanOpen(false)} aria-label="닫기"><X size={18} /></button><span className="modal-mark"><Sparkles size={18} /></span><p className="section-kicker">FIRST STEP</p><h2>오늘 무엇을 해볼까요?</h2><p className="modal-copy">목표, 마감 시간, 비어 있지 않은 시간을 편하게 말해주세요. AI가 초안을 만들고 적용 전 확인받아요.</p><textarea placeholder="예: 오늘 저녁 7시까지 졸업작품 기획을 정리하고 싶어. 3시부터 5시는 수업이야." rows={4} autoFocus /><div className="modal-chips"><button>시간이 별로 없어요</button><button>할 일이 너무 많아요</button><button>우선순위를 모르겠어요</button></div><button className="primary-button full" onClick={() => setPlanOpen(false)}><Sparkles size={17} />계획 초안 만들기</button></section></div>}

      {checkinMode && <div className="modal-backdrop" onMouseDown={() => setCheckinMode(null)}><section className="checkin-modal" onMouseDown={(e) => e.stopPropagation()}><button className="close-button" onClick={() => setCheckinMode(null)} aria-label="닫기"><X size={18} /></button><span className={`checkin-symbol ${checkinMode}`}>{checkinMode === 'completed' ? <Check size={20} /> : <MessageCircle size={20} />}</span><p className="section-kicker">QUICK CHECK-IN</p><h2>{checkinMode === 'completed' ? '잘 해냈어요. 이유를 남겨볼까요?' : '어떤 점이 막혔나요?'}</h2><p className="modal-copy">짧게 남긴 기록이 다음 계획을 더 현실적으로 만들어요.</p><div className="reason-options">{reasonOptions.map((reason, i) => <label key={reason}><input type="radio" name="reason" defaultChecked={i === 0} /><span>{reason}</span></label>)}</div><textarea placeholder="추가 메모가 있다면 적어주세요 (선택)" rows={3} /><button className="primary-button full" onClick={saveCheckin}>{checkinMode === 'completed' ? '기록 저장' : '회복 계획 제안받기'}</button></section></div>}

      {memoryOpen && <div className="modal-backdrop" onMouseDown={() => setMemoryOpen(false)}><section className="memory-modal" onMouseDown={(e) => e.stopPropagation()}><button className="close-button" onClick={() => setMemoryOpen(false)} aria-label="닫기"><X size={18} /></button><span className="memory-symbol"><Brain size={20} /></span><p className="section-kicker">MEMORY CANDIDATE</p><h2>다음 계획에 반영할까요?</h2><div className="memory-quote">“사용자는 작업이 작게 나뉘어 있을 때 시작 부담이 낮아져요.”</div><p className="modal-copy">체크인에서 남긴 내용과 최근 실행 기록을 바탕으로 제안했어요. AI는 승인 전에는 이 내용을 기억으로 저장하지 않아요.</p><div className="memory-actions"><button className="secondary-button" onClick={() => setMemoryOpen(false)}>문구 수정</button><button className="secondary-button" onClick={() => setMemoryOpen(false)}>이번에만 적용</button><button className="primary-button" onClick={() => setMemoryOpen(false)}>기억 저장</button></div></section></div>}
    </div>
  )
}

export default App

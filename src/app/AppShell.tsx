import { useState, type ReactNode } from 'react'
import {
  Brain,
  CalendarDays,
  LayoutDashboard,
  Menu,
  MoreHorizontal,
  Plus,
  Settings2,
  Sparkles,
  Target,
  X,
} from 'lucide-react'
import type { View } from '../shared/types'

type AppShellProps = {
  activeView: View
  onChangeView: (view: View) => void
  onCreateProject: () => void
  onShowSettingsNotice: () => void
  projectCount: number
  notice: string
  onCloseNotice: () => void
  children: ReactNode
  editor: ReactNode
}

const mobileNavigation: ReadonlyArray<readonly [View, string]> = [
  ['today', '오늘'],
  ['calendar', '캘린더'],
  ['memory', '기억'],
  ['portfolio', '전체 계획'],
  ['execution', '실행 프로필·주간 계획'],
]

function viewTitle(view: View) {
  if (view === 'execution') return '실행 프로필·주간 계획'
  if (view === 'portfolio') return '전체 계획'
  if (view === 'calendar') return '캘린더'
  if (view === 'memory') return '기억 관리'
  return '오늘'
}

export function AppShell({
  activeView,
  onChangeView,
  onCreateProject,
  onShowSettingsNotice,
  projectCount,
  notice,
  onCloseNotice,
  children,
  editor,
}: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={15} /></span>
          <span>re:plan</span>
        </div>
        <nav className="nav-list" aria-label="주요 메뉴">
          <button className={`nav-item ${activeView === 'execution' ? 'active' : ''}`} onClick={() => onChangeView('execution')}>
            <Sparkles size={18} />실행 프로필·주간 계획
          </button>
          <button className={`nav-item ${activeView === 'today' ? 'active' : ''}`} onClick={() => onChangeView('today')}>
            <LayoutDashboard size={18} />오늘
          </button>
          <button className={`nav-item ${activeView === 'calendar' ? 'active' : ''}`} onClick={() => onChangeView('calendar')}>
            <CalendarDays size={18} />캘린더
          </button>
          <button className={`nav-item ${activeView === 'memory' ? 'active' : ''}`} onClick={() => onChangeView('memory')}>
            <Brain size={18} />기억
          </button>
          <button className={`nav-item ${activeView === 'portfolio' ? 'active' : ''}`} onClick={() => onChangeView('portfolio')}>
            <Target size={18} />전체 계획
          </button>
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={onShowSettingsNotice}>
            <Settings2 size={18} />설정
          </button>
          <div className="profile">
            <div className="avatar">H</div>
            <div><strong>현우</strong><span>프로젝트 {projectCount}개</span></div>
            <MoreHorizontal size={17} />
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileNavOpen((open) => !open)} aria-label="메뉴">
            <Menu size={20} />
          </button>
          <div className="date-control">
            <CalendarDays size={17} />
            <div><span>PERSONAL PLANNER</span><strong>{viewTitle(activeView)}</strong></div>
          </div>
          <button className="primary-button compact" onClick={onCreateProject}>
            <Plus size={16} />새 프로젝트
          </button>
        </header>

        {mobileNavOpen && (
          <nav className="mobile-nav" aria-label="모바일 메뉴">
            {mobileNavigation.map(([view, label]) => (
              <button
                className={activeView === view ? 'active' : ''}
                key={view}
                onClick={() => {
                  onChangeView(view)
                  setMobileNavOpen(false)
                }}
              >
                {label}
              </button>
            ))}
          </nav>
        )}

        {children}
      </main>

      {notice && (
        <div className="notice-toast">
          <span>{notice}</span>
          <button onClick={onCloseNotice} aria-label="알림 닫기"><X size={15} /></button>
        </div>
      )}
      {editor}
    </div>
  )
}

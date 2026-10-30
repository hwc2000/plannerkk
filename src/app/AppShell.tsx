import { useState, type ReactNode } from 'react'
import {
  Brain,
  CalendarDays,
  Clock,
  LogOut,
  Menu,
  MoreHorizontal,
  Plus,
  Sparkles,
  Target,
  UserRound,
  X,
} from 'lucide-react'
import type { AuthUser, Project, View } from '../shared/types'
import { projectColor } from '../shared/projectColors'

type AppShellProps = {
  activeView: View
  onChangeView: (view: View) => void
  onCreateProject: () => void
  projectCount: number
  /** Projects in the sidebar, like channels; the ended ones fold away below. */
  projects: Project[]
  endedProjectIds: string[]
  activeProjectId: string
  onOpenProject: (projectId: string) => void
  user?: AuthUser
  onLogout?: () => void
  notice: string
  onCloseNotice: () => void
  children: ReactNode
  editor: ReactNode
}

const mobileNavigation: ReadonlyArray<readonly [View, string]> = [
  ['calendar', '홈'],
  ['schedule', '이번 주 시간'],
  ['execution', '내 프로필'],
  ['memory', '기억'],
  ['portfolio', '전체 계획'],
]

function viewTitle(view: View, project?: Project) {
  if (view === 'project') return project?.title ?? '프로젝트'
  if (view === 'execution') return '내 프로필'
  if (view === 'portfolio') return '전체 계획'
  if (view === 'calendar') return '이번 주'
  if (view === 'schedule') return '이번 주 시간'
  return '기억 관리'
}

export function AppShell({
  activeView,
  onChangeView,
  onCreateProject,
  projectCount,
  projects,
  endedProjectIds,
  activeProjectId,
  onOpenProject,
  user,
  onLogout,
  notice,
  onCloseNotice,
  children,
  editor,
}: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const openProject = projects.find(p => p.id === activeProjectId)
  const ongoing = projects.filter(p => !endedProjectIds.includes(p.id))
  const ended = projects.filter(p => endedProjectIds.includes(p.id))
  const projectButton = (project: Project) => (
    <button key={project.id} className={`nav-item nav-project ${activeView === 'project' && project.id === activeProjectId ? 'active' : ''}`}
      onClick={() => onOpenProject(project.id)} title={project.title}>
      <i className="project-dot" style={{ background: projectColor(project.id) }} /><span>{project.title}</span>
    </button>
  )

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={15} /></span>
          <span>re:plan</span>
        </div>
        <nav className="nav-list" aria-label="주요 메뉴">
          <button className={`nav-item ${activeView === 'calendar' ? 'active' : ''}`} onClick={() => onChangeView('calendar')}>
            <CalendarDays size={18} />홈
          </button>
          <button className={`nav-item ${activeView === 'schedule' ? 'active' : ''}`} onClick={() => onChangeView('schedule')}>
            <Clock size={18} />이번 주 시간
          </button>
          <div className="nav-section" role="group" aria-label="프로젝트">
            <span className="nav-heading">프로젝트</span>
            {ongoing.map(projectButton)}
            <button className="nav-item nav-add" onClick={onCreateProject}><Plus size={16} />새 프로젝트</button>
            {ended.length > 0 && <details className="nav-ended"><summary>끝낸 프로젝트 {ended.length}개</summary>{ended.map(projectButton)}</details>}
          </div>
          <button className={`nav-item ${activeView === 'execution' ? 'active' : ''}`} onClick={() => onChangeView('execution')}>
            <UserRound size={18} />내 프로필
          </button>
          <button className={`nav-item ${activeView === 'memory' ? 'active' : ''}`} onClick={() => onChangeView('memory')}>
            <Brain size={18} />기억
          </button>
          <button className={`nav-item ${activeView === 'portfolio' ? 'active' : ''}`} onClick={() => onChangeView('portfolio')}>
            <Target size={18} />전체 계획
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className={`profile ${activeView === 'execution' ? 'active' : ''}`}>
            <button className="profile-open" onClick={() => onChangeView('execution')} title="내 프로필 열기">
              <span className="avatar">{(user?.displayName ?? '나').slice(0, 1).toUpperCase()}</span>
              <span className="profile-text">
                <strong>{user?.displayName ?? '로컬 사용자'}</strong>
                <span className="profile-email" title={user?.email}>{user ? user.email : `프로젝트 ${projectCount}개`}</span>
              </span>
            </button>
            {onLogout
              ? <button className="profile-logout" onClick={onLogout} aria-label="로그아웃" title="로그아웃"><LogOut size={16} /></button>
              : <MoreHorizontal size={17} />}
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
            <div><span>PERSONAL PLANNER</span><strong>{viewTitle(activeView, openProject)}</strong></div>
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
            {ongoing.map(project => (
              <button
                className={activeView === 'project' && project.id === activeProjectId ? 'active' : ''}
                key={project.id}
                onClick={() => {
                  onOpenProject(project.id)
                  setMobileNavOpen(false)
                }}
              >
                # {project.title}
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

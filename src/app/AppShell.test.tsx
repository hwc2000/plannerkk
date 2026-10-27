// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { AppShell } from './AppShell'
import type { Project } from '../shared/types'

afterEach(cleanup)

const project = (id: string, title: string) =>
  ({ id, title, goal: '', startDate: '2030-01-01', dueDate: '2030-01-31', priority: 'high', status: 'active' }) as Project

it('lists projects in the sidebar like channels, with the ended ones folded away', () => {
  const open = vi.fn()
  render(<AppShell activeView="project" onChangeView={vi.fn()} onCreateProject={vi.fn()} onShowSettingsNotice={vi.fn()} projectCount={2}
    projects={[project('essay', '에세이'), project('toeic', '토익')]} endedProjectIds={['toeic']} activeProjectId="essay" onOpenProject={open}
    notice="" onCloseNotice={vi.fn()} editor={null}><p>본문</p></AppShell>)

  const nav = screen.getByRole('group', { name: '프로젝트' })
  expect(nav.textContent).toContain('에세이')
  expect(screen.getByText('끝낸 프로젝트 1개')).toBeTruthy()
  expect(screen.getAllByText('에세이').length).toBeGreaterThan(1)  // the topbar names the open project
  fireEvent.click(screen.getByTitle('토익'))
  expect(open).toHaveBeenCalledWith('toeic')
})

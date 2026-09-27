import { Pencil, Plus, Trash2 } from 'lucide-react'
import { memoryLabel } from '../../shared/constants'
import type { Memory } from '../../shared/types'

type MemoryViewProps = {
  memories: Memory[]
  onCreate: () => void
  onEdit: (id: string) => void
  onDelete: (id: string) => void
}

export function MemoryView({ memories, onCreate, onEdit, onDelete }: MemoryViewProps) {
  return (
    <section className="memory-workspace">
      <div className="calendar-intro">
        <div>
          <p className="eyebrow">MEMORY</p>
          <h1>나의 맥락을 <em>직접 관리</em>.</h1>
          <p>현재는 사용자가 입력한 기억을 localStorage에 저장합니다.</p>
        </div>
        <button className="primary-button compact" onClick={onCreate}>
          <Plus size={16} />기억 추가
        </button>
      </div>
      <div className="memory-grid">
        {memories.map((memory) => (
          <article className="memory-card" key={memory.id}>
            <div>
              <span className="status-chip planned">{memoryLabel[memory.category]}</span>
              <span className="row-actions">
                <button onClick={() => onEdit(memory.id)} aria-label="기억 수정"><Pencil size={15} /></button>
                <button onClick={() => onDelete(memory.id)} aria-label="기억 삭제"><Trash2 size={15} /></button>
              </span>
            </div>
            <p>“{memory.content}”</p>
            <small>{memory.createdAt} 저장</small>
          </article>
        ))}
        {!memories.length && <div className="empty-state">저장한 기억이 없습니다.</div>}
      </div>
    </section>
  )
}

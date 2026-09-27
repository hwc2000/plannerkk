import { useState } from 'react'
import { X } from 'lucide-react'
import { memoryLabel, TODAY } from '../../shared/constants'
import type { Editor, Memory, MemoryCategory } from '../../shared/types'

type MemoryFormProps = {
  editor: Exclude<Editor, null>
  memories: Memory[]
  onClose: () => void
  onSave: (value: Memory) => void
}

const createId = () => crypto.randomUUID()

export function MemoryForm({ editor, memories, onClose, onSave }: MemoryFormProps) {
  const existing = memories.find((item) => item.id === editor.id)
  const [content, setContent] = useState(existing?.content ?? '')
  const [category, setCategory] = useState<MemoryCategory>(existing?.category ?? 'context')
  const heading = `${existing ? '수정' : '추가'} · 기억`

  function submit() {
    if (!content.trim()) return
    onSave({
      id: existing?.id ?? createId(),
      content: content.trim(),
      category,
      source: existing?.source ?? 'user',
      createdAt: existing?.createdAt ?? TODAY,
    })
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form
        className="data-modal"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <button className="close-button" type="button" onClick={onClose} aria-label="닫기"><X size={18} /></button>
        <p className="section-kicker">LOCAL CRUD</p>
        <h2>{heading}</h2>
        <label>
          기억 내용
          <input autoFocus value={content} onChange={(event) => setContent(event.target.value)} required />
        </label>
        <label>
          분류
          <select value={category} onChange={(event) => setCategory(event.target.value as MemoryCategory)}>
            {Object.entries(memoryLabel).map(([value, label]) => (
              <option value={value} key={value}>{label}</option>
            ))}
          </select>
        </label>
        <button className="primary-button full" type="submit">저장</button>
      </form>
    </div>
  )
}

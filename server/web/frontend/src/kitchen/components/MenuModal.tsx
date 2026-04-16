import { useEffect, useState } from 'react'
import type { MenuItem } from '../../api/client'

interface Props {
  open: boolean
  items: MenuItem[]
  loading: boolean
  onSelect: (item: MenuItem) => void
  onClose: () => void
}

export default function MenuModal({ open, items, loading, onSelect, onClose }: Props) {
  const [selected, setSelected] = useState<MenuItem | null>(null)

  // reset selection when modal opens
  useEffect(() => {
    if (open) setSelected(null)
  }, [open])

  if (!open) return null

  const available = items.filter(i => i.is_available)

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col justify-end"
      style={{ background: 'rgba(0,0,0,0.6)' }}
      onClick={onClose}
    >
      <div
        className="rounded-t-2xl p-5 flex flex-col gap-4"
        style={{ background: '#242840', maxHeight: '70vh', overflowY: 'auto' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center -mt-1 mb-1">
          <div className="w-10 h-1 rounded-full" style={{ background: '#3a3f5c' }} />
        </div>

        <h2 className="text-lg font-bold text-white">메뉴 선택</h2>
        <p className="text-sm -mt-2" style={{ color: '#a0aec0' }}>로봇을 보낼 진열장을 선택하세요</p>

        {loading ? (
          <div className="flex justify-center py-8">
            <div
              className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin"
              style={{ borderColor: '#4c6ef5', borderTopColor: 'transparent' }}
            />
          </div>
        ) : available.length === 0 ? (
          <p className="text-sm text-center py-6" style={{ color: '#6b7280' }}>
            현재 이용 가능한 메뉴가 없습니다
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {available.map(item => {
              const isSelected = selected?.menu_id === item.menu_id
              return (
                <button
                  key={item.menu_id}
                  onClick={() => setSelected(isSelected ? null : item)}
                  className="px-4 py-2 rounded-full text-sm font-medium transition-all"
                  style={{
                    background: isSelected ? '#4c6ef5' : '#2e3250',
                    color: isSelected ? '#fff' : '#a0aec0',
                    border: `2px solid ${isSelected ? '#4c6ef5' : '#3a3f5c'}`,
                  }}
                >
                  {item.name}
                  <span className="ml-2 text-xs opacity-70">{item.place_id}</span>
                </button>
              )
            })}
          </div>
        )}

        <div className="flex gap-3 mt-2">
          <button
            className="flex-1 py-3 rounded-xl font-semibold text-sm transition-opacity"
            style={{ background: '#2e3250', color: '#a0aec0' }}
            onClick={onClose}
          >
            취소
          </button>
          <button
            className="flex-1 py-3 rounded-xl font-semibold text-sm transition-opacity disabled:opacity-40"
            style={{ background: '#4c6ef5', color: '#fff' }}
            disabled={!selected}
            onClick={() => selected && onSelect(selected)}
          >
            로봇 호출
          </button>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import BackButton from '../components/BackButton'
import type { MenuItem } from '../types'

const DISPLAY_EMOJIS: Record<string, string> = {
  DISP_01: '🍽️',
  DISP_02: '🥘',
  DISP_03: '🍱',
  DISP_04: '🥗',
  DISP_05: '🍜',
  DISP_06: '🥩',
}

interface RawMenuItem {
  menu_id: number
  name: string
  place_id: string
  is_available: number
  sort_order: number
}

interface Props {
  onSelect: (items: MenuItem[]) => void
  onBack: () => void
}

export default function MenuSelectionScreen({ onSelect, onBack }: Props) {
  const [menuItems, setMenuItems] = useState<MenuItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [fetchKey, setFetchKey] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  useEffect(() => {
    setLoading(true)
    setError(false)
    fetch('/api/menu-items')
      .then(r => {
        if (!r.ok) throw new Error('fetch failed')
        return r.json()
      })
      .then((data: { menu_items: RawMenuItem[] }) => {
        const items: MenuItem[] = data.menu_items
          .filter(m => m.is_available === 1)
          .map(m => ({
            id: m.place_id,
            name: m.name,
            emoji: DISPLAY_EMOJIS[m.place_id] ?? '🍽️',
          }))
        setMenuItems(items)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [fetchKey])

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // maintain selection order by insertion — derive ordered list
  const selectedOrdered = menuItems.filter(m => selected.has(m.id))

  const handleConfirm = () => {
    if (selectedOrdered.length === 0) return
    onSelect(selectedOrdered)
  }

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-8 pb-4">
      <BackButton onClick={onBack} />

      <div className="mt-4">
        <h2 className="text-2xl font-bold text-gray-900">안내받을 메뉴를</h2>
        <h2 className="text-2xl font-bold text-gray-900">선택해 주세요</h2>
        <p className="text-sm text-gray-400 mt-1">여러 개를 선택하면 순서대로 안내합니다</p>
      </div>

      <div className="grid grid-cols-2 gap-3 mt-6 flex-1">
        {loading && (
          <>
            {[1, 2, 3, 4].map(i => (
              <div
                key={i}
                className="bg-white rounded-2xl py-8 border-2 border-gray-100 animate-pulse flex flex-col items-center gap-3"
              >
                <div className="w-10 h-10 bg-gray-200 rounded-full" />
                <div className="w-20 h-4 bg-gray-200 rounded-full" />
              </div>
            ))}
          </>
        )}

        {error && (
          <div className="col-span-2 flex flex-col items-center gap-3 py-10 text-gray-400">
            <span className="text-4xl">⚠️</span>
            <p className="text-sm text-center">메뉴를 불러오지 못했습니다<br />잠시 후 다시 시도해 주세요</p>
            <button
              onClick={() => setFetchKey(k => k + 1)}
              className="mt-2 text-sm font-bold text-gray-700 underline active:opacity-60"
            >
              다시 시도
            </button>
          </div>
        )}

        {!loading && !error && menuItems.length === 0 && (
          <div className="col-span-2 flex flex-col items-center gap-3 py-10 text-gray-400">
            <span className="text-4xl">🍽️</span>
            <p className="text-sm">현재 이용 가능한 메뉴가 없습니다</p>
          </div>
        )}

        {!loading && !error && menuItems.map(item => {
          const isSelected = selected.has(item.id)
          const order = selectedOrdered.findIndex(m => m.id === item.id) + 1
          return (
            <button
              key={item.id}
              onClick={() => toggle(item.id)}
              className={`
                relative bg-white rounded-2xl py-8 flex flex-col items-center gap-3 border-2 active:scale-95 transition-all
                ${isSelected ? 'border-gray-900 shadow-lg' : 'border-gray-100 shadow-sm'}
              `}
            >
              {/* Order badge */}
              {isSelected && (
                <div className="absolute top-2.5 right-2.5 w-6 h-6 rounded-full bg-gray-900 text-white text-xs font-bold flex items-center justify-center">
                  {order}
                </div>
              )}
              <span className="text-4xl">{item.emoji}</span>
              <span className="text-base font-bold text-gray-900">{item.name}</span>
            </button>
          )
        })}
      </div>

      {/* Confirm button */}
      <div className="mt-4 pt-3 border-t border-gray-200">
        <button
          onClick={handleConfirm}
          disabled={selected.size === 0}
          className={`
            w-full py-5 rounded-2xl text-base font-bold transition-all active:scale-95
            ${selected.size > 0
              ? 'bg-gray-900 text-white shadow-md'
              : 'bg-gray-200 text-gray-400 cursor-not-allowed'
            }
          `}
        >
          {selected.size > 0 ? `${selected.size}개 메뉴 안내 시작` : '메뉴를 선택해 주세요'}
        </button>
      </div>
    </div>
  )
}

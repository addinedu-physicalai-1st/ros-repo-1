import { useEffect, useRef } from 'react'
import type { People } from '../types'
import { PRICES, calcTotal, formatPrice } from '../types'

interface Props {
  people: People
  onChange: (people: People) => void
  onNext: () => void
  onIdleReset: () => void
}

const IDLE_MS = 2 * 60 * 1000 // 2 minutes

type PersonKey = keyof People

const LABELS: { key: PersonKey; label: string; sub: string }[] = [
  { key: 'adult', label: '어른', sub: formatPrice(PRICES.adult) },
  { key: 'child', label: '어린이', sub: formatPrice(PRICES.child) },
  { key: 'infant', label: '유아', sub: '무료' },
]

export default function SelectionScreen({ people, onChange, onNext, onIdleReset }: Props) {
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const resetIdle = () => {
    if (idleTimer.current) clearTimeout(idleTimer.current)
    idleTimer.current = setTimeout(() => {
      onChange({ adult: 0, child: 0, infant: 0 })
      onIdleReset()
    }, IDLE_MS)
  }

  useEffect(() => {
    resetIdle()
    const events = ['pointerdown', 'pointermove', 'keydown'] as const
    const handler = () => resetIdle()
    events.forEach(e => window.addEventListener(e, handler))
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current)
      events.forEach(e => window.removeEventListener(e, handler))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const adjust = (key: PersonKey, delta: number) => {
    const next = Math.max(0, people[key] + delta)
    onChange({ ...people, [key]: next })
  }

  const total = calcTotal(people)
  const totalPeople = people.adult + people.child + people.infant

  return (
    <div className="flex flex-col items-center justify-center w-full h-full">
      <div
        className="w-full max-w-lg rounded-3xl px-10 py-10"
        style={{ background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(16px)' }}
      >
        <h2 className="text-3xl font-bold text-gray-900 text-center mb-8">
          인원 선택
        </h2>

        <div className="flex flex-col gap-5 mb-8">
          {LABELS.map(({ key, label, sub }) => (
            <div
              key={key}
              className="flex items-center justify-between rounded-2xl px-6 py-4"
              style={{ background: 'rgba(255,255,255,0.06)' }}
            >
              <div>
                <span className="text-gray-900 text-xl font-semibold">{label}</span>
                <span className="ml-3 text-gray-600 text-sm">{sub}</span>
              </div>
              <div className="flex items-center gap-4">
                <button
                  className="w-10 h-10 rounded-full text-white text-2xl font-bold flex items-center justify-center transition-opacity disabled:opacity-30"
                  style={{ background: 'rgba(124,92,191,0.7)' }}
                  onClick={() => adjust(key, -1)}
                  disabled={people[key] === 0}
                  aria-label={`${label} 감소`}
                >
                  −
                </button>
                <span className="text-gray-900 text-2xl font-bold w-8 text-center">
                  {people[key]}
                </span>
                <button
                  className="w-10 h-10 rounded-full text-white text-2xl font-bold flex items-center justify-center transition-opacity"
                  style={{ background: 'rgba(124,92,191,0.7)' }}
                  onClick={() => adjust(key, 1)}
                  aria-label={`${label} 증가`}
                >
                  +
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="flex justify-between items-center mb-8 px-2">
          <span className="text-gray-800 text-lg font-semibold">합계</span>
          <span className="text-gray-900 text-2xl font-bold">{formatPrice(total)}</span>
        </div>

        <button
          className="w-full py-4 rounded-2xl text-white text-xl font-bold transition-opacity disabled:opacity-40"
          style={{ background: '#7c5cbf' }}
          disabled={totalPeople === 0}
          onClick={onNext}
        >
          결제 단계로 →
        </button>
      </div>
    </div>
  )
}

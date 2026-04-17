import { useState } from 'react'
import type { People, PayMethod } from '../types'
import { calcTotal, formatPrice, PRICES } from '../types'

interface Props {
  people: People
  onBack: () => void
  onPay: (method: PayMethod) => Promise<void>
}

const PAY_METHODS: { key: PayMethod; label: string; icon: string }[] = [
  { key: 'card', label: '카드', icon: '💳' },
  { key: 'samsung', label: '삼성페이', icon: '📱' },
  { key: 'apple', label: '애플페이', icon: '' },
]

const PERSON_LABELS: { key: keyof People; label: string }[] = [
  { key: 'adult', label: '어른' },
  { key: 'child', label: '어린이' },
  { key: 'infant', label: '유아' },
]

export default function PaymentScreen({ people, onBack, onPay }: Props) {
  const [payMethod, setPayMethod] = useState<PayMethod | null>(null)
  const [loading, setLoading] = useState(false)

  const total = calcTotal(people)

  const handlePay = async () => {
    if (!payMethod || loading) return
    setLoading(true)
    await onPay(payMethod)
    setLoading(false)
  }

  return (
    <div className="flex flex-col items-center justify-center w-full h-full">
      <div
        className="w-full max-w-lg rounded-3xl px-10 py-10"
        style={{ background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(16px)' }}
      >
        <h2 className="text-3xl font-bold text-gray-900 text-center mb-8">
          주문 확인
        </h2>

        {/* Order summary */}
        <div
          className="rounded-2xl px-6 py-5 mb-6"
          style={{ background: 'rgba(255,255,255,0.06)' }}
        >
          {PERSON_LABELS.filter(({ key }) => people[key] > 0).map(({ key, label }) => (
            <div key={key} className="flex justify-between items-center py-2">
              <span className="text-gray-700 text-lg">
                {label} × {people[key]}
              </span>
              <span className="text-gray-900 font-semibold">
                {formatPrice(PRICES[key] * people[key])}
              </span>
            </div>
          ))}
          <div
            className="flex justify-between items-center pt-3 mt-2"
            style={{ borderTop: '1px solid rgba(0,0,0,0.12)' }}
          >
            <span className="text-gray-900 text-xl font-bold">총 결제금액</span>
            <span className="text-2xl font-bold" style={{ color: '#5b21b6' }}>{formatPrice(total)}</span>
          </div>
        </div>

        {/* Payment method */}
        <p className="text-gray-700 text-sm mb-3">결제 수단 선택</p>
        <div className="grid grid-cols-3 gap-3 mb-8">
          {PAY_METHODS.map(({ key, label, icon }) => {
            const selected = payMethod === key
            return (
              <button
                key={key}
                onClick={() => setPayMethod(key)}
                className="flex flex-col items-center justify-center gap-2 rounded-2xl py-5 font-semibold transition-all"
                style={{
                  background: selected
                    ? 'rgba(124,92,191,0.8)'
                    : 'rgba(255,255,255,0.06)',
                  border: selected
                    ? '2px solid #a78bfa'
                    : '2px solid transparent',
                  color: selected ? '#fff' : '#1f2937',
                }}
              >
                <span className="text-2xl">{icon}</span>
                <span className="text-sm">{label}</span>
              </button>
            )
          })}
        </div>

        {/* Action buttons */}
        <div className="flex gap-3">
          <button
            className="flex-1 py-4 rounded-2xl text-gray-700 text-lg font-semibold transition-opacity"
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(0,0,0,0.15)' }}
            onClick={onBack}
            disabled={loading}
          >
            ← 이전
          </button>
          <button
            className="flex-[2] py-4 rounded-2xl text-white text-xl font-bold transition-opacity disabled:opacity-40"
            style={{ background: '#7c5cbf' }}
            disabled={!payMethod || loading}
            onClick={handlePay}
          >
            {loading ? '처리 중…' : '결제하기'}
          </button>
        </div>
      </div>
    </div>
  )
}

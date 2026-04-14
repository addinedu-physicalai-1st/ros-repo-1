import { useEffect, useState } from 'react'
import type { Flow } from '../types'

interface Props {
  flow: Flow
  onHome: () => void
}

export default function GuideCompleteScreen({ flow, onHome }: Props) {
  const [countdown, setCountdown] = useState(3)

  useEffect(() => {
    const timer = setTimeout(() => onHome(), 3000)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    if (countdown <= 0) return
    const id = setInterval(() => setCountdown(c => c - 1), 1000)
    return () => clearInterval(id)
  }, [countdown])

  const title = flow === 'menu' ? '안내종료' : '안내가 종료되었습니다.'
  const sub = flow === 'menu'
    ? '이동이 완료되었습니다. 이용해 주셔서 감사합니다.'
    : '화장실 안내가 완료되었습니다. 감사합니다.'

  return (
    <div className="flex flex-col min-h-full bg-gray-900 items-center justify-center px-8 gap-6">
      <div className="w-24 h-24 bg-white/10 rounded-full flex items-center justify-center">
        <span className="text-5xl">🎉</span>
      </div>

      <div className="text-center">
        <h2 className="text-3xl font-bold text-white">{title}</h2>
        <p className="text-sm text-gray-400 mt-3 leading-relaxed">{sub}</p>
      </div>

      <p className="text-sm text-gray-500">
        <span className="text-white font-bold">{countdown}</span>초 후 홈으로 돌아갑니다
      </p>
    </div>
  )
}

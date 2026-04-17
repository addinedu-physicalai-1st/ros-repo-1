import { useEffect, useState } from 'react'

const AUTO_RETURN_SEC = 3

interface Props {
  onHome: () => void
}

export default function AccompanyCompleteScreen({ onHome }: Props) {
  const [countdown, setCountdown] = useState(AUTO_RETURN_SEC)

  useEffect(() => {
    if (countdown <= 0) {
      onHome()
      return
    }
    const id = setInterval(() => setCountdown(c => c - 1), 1000)
    return () => clearInterval(id)
  }, [countdown, onHome])

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] items-center justify-center px-8 gap-6">
      {/* Icon */}
      <div className="w-32 h-32 bg-gray-900 rounded-full flex items-center justify-center shadow-lg">
        <span className="text-6xl">🙏</span>
      </div>

      {/* Message */}
      <div className="text-center">
        <h2 className="text-3xl font-bold text-gray-900 leading-snug">
          이용해 주셔서
          <br />
          감사합니다
        </h2>
        <p className="text-sm text-gray-400 mt-4 leading-relaxed">
          동행 서비스가 종료되었습니다
          <br />
          로봇이 충전소로 복귀합니다
        </p>
      </div>

      {/* Countdown */}
      <div className="flex flex-col items-center gap-2">
        <p className="text-sm text-gray-500">
          <span className="font-bold text-gray-900 text-lg">{countdown}</span>초 후 홈으로 돌아갑니다
        </p>
        <div className="w-40 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-gray-900 rounded-full transition-all duration-1000"
            style={{ width: `${((AUTO_RETURN_SEC - countdown) / AUTO_RETURN_SEC) * 100}%` }}
          />
        </div>
      </div>
    </div>
  )
}

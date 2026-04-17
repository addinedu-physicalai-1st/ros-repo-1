export default function AccompanyCallingScreen() {
  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] items-center justify-center px-8 gap-6">
      {/* Spinner */}
      <div className="relative w-28 h-28">
        <div className="absolute inset-0 rounded-full border-4 border-gray-200" />
        <div className="absolute inset-0 rounded-full border-4 border-gray-900 border-t-transparent animate-spin" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-4xl">🤖</span>
        </div>
      </div>

      <div className="text-center">
        <p className="text-3xl font-bold text-gray-900">호출중...</p>
        <p className="text-sm text-gray-400 mt-3 leading-relaxed">
          동행 로봇을 배차하고 있습니다
          <br />
          잠시만 기다려 주세요
        </p>
      </div>

      {/* Pulsing dots */}
      <div className="flex gap-2 mt-2">
        {[0, 1, 2].map(i => (
          <div
            key={i}
            className="w-2 h-2 rounded-full bg-gray-400 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}

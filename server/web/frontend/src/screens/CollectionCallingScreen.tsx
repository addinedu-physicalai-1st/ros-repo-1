export default function CollectionCallingScreen() {
  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] items-center justify-center px-8 gap-6">
      {/* Spinner */}
      <div className="relative w-24 h-24">
        <div className="absolute inset-0 rounded-full border-4 border-gray-200" />
        <div className="absolute inset-0 rounded-full border-4 border-gray-900 border-t-transparent animate-spin" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-3xl">♻️</span>
        </div>
      </div>

      <div className="text-center">
        <p className="text-2xl font-bold text-gray-900">수거 로봇 호출 중...</p>
        <p className="text-sm text-gray-400 mt-2 leading-relaxed">
          그릇을 수거할 로봇을 배차하고 있습니다
        </p>
      </div>
    </div>
  )
}

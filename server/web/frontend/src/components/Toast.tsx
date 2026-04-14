import { useEffect, useState } from 'react'

export interface ToastMessage {
  id: number
  text: string
  type: 'success' | 'error'
}

interface Props {
  message: ToastMessage | null
}

export default function Toast({ message }: Props) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!message) return
    setVisible(true)
    const timer = setTimeout(() => setVisible(false), 3000)
    return () => clearTimeout(timer)
  }, [message])

  if (!message || !visible) return null

  const colorClass =
    message.type === 'success'
      ? 'bg-white border-green-300 text-green-800'
      : 'bg-white border-red-300 text-red-700'

  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 animate-fade-up">
      <div
        className={`rounded-full border px-6 py-3 text-sm font-medium shadow-lg whitespace-nowrap ${colorClass}`}
      >
        {message.text}
      </div>
    </div>
  )
}

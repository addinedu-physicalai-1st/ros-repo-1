import { useEffect, useRef, useState } from 'react'
import { useTaskEvents } from '../../hooks/useTaskEvents'

interface Props {
  assignedTable: string
  taskId?: string | null
  onDone: () => void
}

interface Step {
  title: string
  sub?: string
}

const STEPS: Step[] = [
  { title: '결제 성공 — 로봇 호출 중' },
  { title: '안내 로봇이 마중 나가고 있습니다' },
  { title: '베리가 도착했습니다!', sub: '자리로 안내해 드리겠습니다' },
  { title: '식사 맛있게 하세요! 😊' },
]

// Fallback timings used when there is no real task to track
const STEP_TIMINGS = [0, 1500, 7000, 11000]
const RESET_TIMING = 18000

// After user confirms arrival: advance to step 3, then step 4, then reset
const POST_CONFIRM_STEP3_DELAY = 500
const POST_CONFIRM_STEP4_DELAY = 3500
const POST_CONFIRM_DONE_DELAY  = 8000

export default function TrackingScreen({ assignedTable, taskId, onDone }: Props) {
  const [activeStep, setActiveStep] = useState(0)
  const [robotArrived, setRobotArrived] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  // Stable ref to prevent stale closures in cleanup
  const timerRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const clearAll = () => {
    timerRef.current.forEach(t => clearTimeout(t))
    timerRef.current = []
  }

  // Listen for real robot arrival via WebSocket (only when we have a taskId)
  useTaskEvents(taskId ?? null, () => setRobotArrived(true))

  // Fallback time-based flow (used when taskId is absent)
  useEffect(() => {
    if (taskId) return // real tracking takes over

    clearAll()
    STEP_TIMINGS.forEach((delay, i) => {
      timerRef.current.push(setTimeout(() => setActiveStep(i), delay))
    })
    timerRef.current.push(setTimeout(onDone, RESET_TIMING))

    return clearAll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  // Real flow: advance step 0→1 immediately, then wait for robotArrived
  useEffect(() => {
    if (!taskId) return

    clearAll()
    timerRef.current.push(setTimeout(() => setActiveStep(1), 1500))

    return clearAll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  // When robot actually arrives (WebSocket), advance to step 2 and wait for user
  useEffect(() => {
    if (!robotArrived) return
    setActiveStep(2)
  }, [robotArrived])

  // After user confirms arrival
  const handleConfirm = () => {
    setConfirmed(true)
    clearAll()
    timerRef.current.push(
      setTimeout(() => setActiveStep(3), POST_CONFIRM_STEP3_DELAY),
    )
    timerRef.current.push(
      setTimeout(() => setActiveStep(4), POST_CONFIRM_STEP4_DELAY),
    )
    timerRef.current.push(setTimeout(onDone, POST_CONFIRM_DONE_DELAY))
  }

  const showArrivalButton = robotArrived && activeStep === 2 && !confirmed

  return (
    <div className="flex flex-col items-center justify-center w-full h-full">
      <div
        className="w-full max-w-lg rounded-3xl px-10 py-12 text-center"
        style={{ background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(16px)' }}
      >
        <div className="text-5xl mb-3">🤖</div>
        <h2 className="text-3xl font-bold text-gray-900 mb-2">안내 로봇 호출</h2>

        <div
          className="inline-block px-6 py-2 rounded-full mb-10 text-gray-900 font-bold text-xl"
          style={{ background: 'rgba(124,92,191,0.3)', border: '1px solid rgba(124,92,191,0.5)' }}
        >
          배정 테이블: {assignedTable}
        </div>

        {/* Progress steps */}
        <div className="flex flex-col gap-0">
          {STEPS.map((step, i) => {
            const done   = i < activeStep
            const active = i === activeStep
            const isLast = i === STEPS.length - 1

            return (
              <div key={i} className="flex items-start gap-4">
                <div className="flex flex-col items-center" style={{ minWidth: 40 }}>
                  <div
                    className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-base flex-shrink-0 transition-all duration-500"
                    style={{
                      background: done
                        ? 'rgba(167,139,250,0.9)'
                        : active
                        ? '#7c5cbf'
                        : 'rgba(255,255,255,0.12)',
                      border: active ? '2px solid #a78bfa' : '2px solid transparent',
                      color: done || active ? '#fff' : 'rgba(255,255,255,0.4)',
                      boxShadow: active ? '0 0 16px rgba(124,92,191,0.7)' : 'none',
                    }}
                  >
                    {done ? '✓' : i + 1}
                  </div>
                  {!isLast && (
                    <div
                      className="w-0.5 flex-1 my-1"
                      style={{
                        minHeight: 28,
                        background: done
                          ? 'rgba(167,139,250,0.7)'
                          : 'rgba(255,255,255,0.12)',
                        transition: 'background 0.5s',
                      }}
                    />
                  )}
                </div>

                <div className="pb-6 pt-1.5 text-left">
                  <p
                    className="font-semibold text-base transition-all duration-500"
                    style={{
                      color: active
                        ? '#1f2937'
                        : done
                        ? '#7c5cbf'
                        : 'rgba(0,0,0,0.3)',
                    }}
                  >
                    {step.title}
                  </p>
                  {step.sub && active && (
                    <p className="text-sm mt-1" style={{ color: '#5b21b6' }}>{step.sub}</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Arrival confirmation button — shown only when robot actually arrives */}
        {showArrivalButton && (
          <button
            onClick={handleConfirm}
            className="mt-6 w-full py-5 rounded-2xl text-white text-xl font-bold active:scale-95 transition-transform"
            style={{
              background: 'linear-gradient(135deg, #7c5cbf, #a78bfa)',
              boxShadow: '0 0 24px rgba(167,139,250,0.5)',
            }}
          >
            ✅ 로봇 도착 확인
          </button>
        )}
      </div>
    </div>
  )
}

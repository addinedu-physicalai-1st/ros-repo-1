import { useEffect, useState } from 'react'

interface Props {
  assignedTable: string
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

const STEP_TIMINGS = [0, 1500, 7000, 11000]
const RESET_TIMING = 18000

export default function TrackingScreen({ assignedTable, onDone }: Props) {
  const [activeStep, setActiveStep] = useState(0)

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []

    STEP_TIMINGS.forEach((delay, i) => {
      timers.push(setTimeout(() => setActiveStep(i), delay))
    })

    timers.push(setTimeout(onDone, RESET_TIMING))

    return () => {
      timers.forEach(t => clearTimeout(t))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col items-center justify-center w-full h-full">
      <div
        className="w-full max-w-lg rounded-3xl px-10 py-12 text-center"
        style={{ background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(16px)' }}
      >
        <div className="text-5xl mb-3">🤖</div>
        <h2 className="text-3xl font-bold text-white mb-2">안내 로봇 호출</h2>

        {/* Assigned table */}
        <div
          className="inline-block px-6 py-2 rounded-full mb-10 text-white font-bold text-xl"
          style={{ background: 'rgba(124,92,191,0.6)', border: '1px solid rgba(167,139,250,0.5)' }}
        >
          배정 테이블: {assignedTable}
        </div>

        {/* Progress steps */}
        <div className="flex flex-col gap-0">
          {STEPS.map((step, i) => {
            const done = i < activeStep
            const active = i === activeStep
            const isLast = i === STEPS.length - 1

            return (
              <div key={i} className="flex items-start gap-4">
                {/* Left: circle + connector */}
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

                {/* Right: text */}
                <div className="pb-6 pt-1.5 text-left">
                  <p
                    className="font-semibold text-base transition-all duration-500"
                    style={{
                      color: active ? '#fff' : done ? 'rgba(167,139,250,0.9)' : 'rgba(255,255,255,0.35)',
                    }}
                  >
                    {step.title}
                  </p>
                  {step.sub && active && (
                    <p className="text-purple-300 text-sm mt-1">{step.sub}</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

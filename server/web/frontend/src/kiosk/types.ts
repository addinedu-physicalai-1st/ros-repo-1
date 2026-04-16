export type Screen = 'welcome' | 'selection' | 'payment' | 'tracking'

export type PayMethod = 'card' | 'samsung' | 'apple'

export interface People {
  adult: number
  child: number
  infant: number
}

export const PRICES: Record<keyof People, number> = {
  adult: 28000,
  child: 18000,
  infant: 0,
}

export function calcTotal(people: People): number {
  return (
    people.adult * PRICES.adult +
    people.child * PRICES.child +
    people.infant * PRICES.infant
  )
}

export function randomTable(): string {
  const letter = ['A', 'B', 'C'][Math.floor(Math.random() * 3)]
  const num = String(Math.floor(Math.random() * 20) + 1).padStart(2, '0')
  return `${letter}-${num}`
}

export function formatPrice(n: number): string {
  return n.toLocaleString('ko-KR') + '원'
}

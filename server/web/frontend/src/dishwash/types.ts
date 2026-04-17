export type DishwashScreen =
  | 'idle'
  | 'robot_arrived'
  | 'collecting'

export interface ActivityEntry {
  id: number
  text: string
  color: 'green' | 'blue' | 'orange' | 'red' | 'gray'
  time: string
}

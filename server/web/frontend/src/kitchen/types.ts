export type KitchenScreen =
  | 'idle'
  | 'robot_coming'
  | 'robot_at_kitchen'
  | 'robot_going_disp'
  | 'robot_returning'
  | 'robot_back'
  | 'completed'
  | 'failed'

export type KitchenFlow = 'menu' | 'toilet' | null

export interface ActivityEntry {
  id: number
  text: string
  color: 'green' | 'blue' | 'orange' | 'red' | 'gray'
  time: string
}

export type StaffScreen =
  | 'idle'
  | 'robot_arriving'
  | 'robot_arrived'
  | 'waiting_unload'
  | 'robot_departing'

export interface ActivityEntry {
  id: number
  time: string
  text: string
}

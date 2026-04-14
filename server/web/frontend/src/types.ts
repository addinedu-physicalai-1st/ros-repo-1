export type Screen =
  | 'home'
  | 'guideMenu'
  | 'restroomOptions'
  | 'menuSelection'
  | 'menuOptions'
  | 'callingRobot'
  | 'robotArrived'
  | 'guideStarting'
  | 'inProgress'
  | 'guideComplete'

export type Flow = 'toilet' | 'menu' | null

export interface MenuItem {
  id: string
  name: string
  emoji: string
}

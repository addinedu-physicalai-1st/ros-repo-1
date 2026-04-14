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
  // Accompany flow
  | 'accompanyCallingRobot'
  | 'accompanyArrived'
  | 'accompanyActive'
  | 'accompanyReturning'
  | 'accompanyReturned'
  | 'accompanyComplete'

export type Flow = 'toilet' | 'menu' | null

export interface MenuItem {
  id: string
  name: string
  emoji: string
}

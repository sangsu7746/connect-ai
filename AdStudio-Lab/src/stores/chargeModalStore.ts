// 인앱 포인트 충전 모달 열림 상태 — 어디서든 useChargeModal.getState().open()으로 열 수 있다.
import { create } from 'zustand'

interface ChargeModalState {
  isOpen: boolean
  open: () => void
  close: () => void
}

export const useChargeModal = create<ChargeModalState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
}))

import { create } from 'zustand'
import type { Outcome, Snapshot, Scenario } from './types'
import { validPicks } from './domain'
export { projectedTable } from './domain'

type Store = {
  mode: 'reality' | 'sandbox'; stageId: string; revision: number; overrides: Record<string, Outcome>;
  model: 'equal' | 'rating'; washoutProbability: number;
  setMode: (mode: Store['mode']) => void; toggle: (id: string, value: Outcome) => void; reset: () => void;
  setModel: (model: Store['model']) => void; setRain: (value: number) => void;
  attach: (snapshot: Snapshot, saved?: Scenario | null) => number;
}
export const useScenario = create<Store>((set, get) => ({
  mode: 'reality', stageId: '', revision: 0, overrides: {}, model: 'equal', washoutProbability: 0.03,
  setMode: (mode) => set({ mode }), setModel: (model) => set({ model }), setRain: (washoutProbability) => set({ washoutProbability }),
  toggle: (id, value) => set((state) => {
    const overrides = { ...state.overrides }
    if (overrides[id] === value) delete overrides[id]
    else overrides[id] = value
    return { overrides }
  }), reset: () => set({ overrides: {} }),
  attach: (snapshot, saved) => {
    const current = get()
    const source = saved?.stageId === snapshot.stage_id ? saved : current.stageId === snapshot.stage_id ? current : null
    const picks = source?.overrides || {}
    const overrides = validPicks(snapshot, picks)
    set({ stageId: snapshot.stage_id, revision: snapshot.revision, overrides,
      model: source?.model || 'equal', washoutProbability: source?.washoutProbability ?? 0.03 })
    return Object.keys(picks).length - Object.keys(overrides).length
  },
}))

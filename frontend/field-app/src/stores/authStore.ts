import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  facilityId: string | null
  userId: string | null
  name: string | null
  facilityName: string | null
  languagePref: string
  // Set true by setAuth on every successful login; the app shows the
  // "how to use" popup once and clears it via dismissLoginHelp.
  justLoggedIn: boolean
  setAuth: (a: {
    token: string
    facilityId: string
    userId: string
    name: string
    facilityName?: string
    languagePref?: string
  }) => void
  dismissLoginHelp: () => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      facilityId: null,
      userId: null,
      name: null,
      facilityName: null,
      languagePref: 'hi',
      justLoggedIn: false,
      setAuth: (a) => set({ languagePref: 'hi', ...a, justLoggedIn: true }),
      dismissLoginHelp: () => set({ justLoggedIn: false }),
      logout: () =>
        set({
          token: null,
          facilityId: null,
          userId: null,
          name: null,
          facilityName: null,
          languagePref: 'hi',
          justLoggedIn: false,
        }),
    }),
    { name: 'smarthealth-field-auth' },
  ),
)

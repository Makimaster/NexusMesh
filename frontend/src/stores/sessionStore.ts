import { create } from "zustand";

type SessionState = {
  accessToken: string | null;
  setAccessToken: (token: string | null) => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  accessToken: null,
  setAccessToken: (token) => set({ accessToken: token }),
}));

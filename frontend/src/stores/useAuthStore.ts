import { create } from 'zustand';
import { auth } from '../services/api';
import { useChatStore } from './useChatStore';
import { useUIStore } from './useUIStore';

interface AuthState {
  isAuthenticated: boolean;
  userEmail: string | null;
  authDialogOpen: boolean;
  authDialogTab: 'login' | 'register';
  openAuthDialog: (tab?: 'login' | 'register') => void;
  closeAuthDialog: () => void;
  setAuthDialogTab: (tab: 'login' | 'register') => void;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => {
  auth.subscribe(() => {
    if (!auth.isAuthenticated()) {
      useChatStore.getState().resetUserData();
      useUIStore.getState().closeSettings();
    }
    set({
      isAuthenticated: auth.isAuthenticated(),
      userEmail: auth.getUserEmail(),
    });
  });

  return {
    isAuthenticated: auth.isAuthenticated(),
    userEmail: auth.getUserEmail(),
    authDialogOpen: false,
    authDialogTab: 'login',

    openAuthDialog: (tab = 'login') =>
      set({
        authDialogOpen: true,
        authDialogTab: tab,
      }),

    closeAuthDialog: () =>
      set({
        authDialogOpen: false,
      }),

    setAuthDialogTab: (tab) =>
      set({
        authDialogTab: tab,
      }),

    logout: () => auth.logout(),
  };
});

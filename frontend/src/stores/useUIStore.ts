import { create } from 'zustand';

type SettingsTab = 'keys' | 'docs' | 'get-docs';

interface UIState {
  isExpanded: boolean;
  isMobileSidebarOpen: boolean;
  settingsDialogOpen: boolean;
  settingsDialogTab: SettingsTab;
  toggleSidebar: (isCompact: boolean) => void;
  closeMobileSidebar: () => void;
  openSettings: (tab?: SettingsTab) => void;
  closeSettings: () => void;
  setSettingsTab: (tab: SettingsTab) => void;
}

function getStoredSidebarExpanded(): boolean {
  try {
    const stored = localStorage.getItem('sidebar-expanded');
    return stored ? (JSON.parse(stored) as boolean) : false;
  } catch {
    return false;
  }
}

export const useUIStore = create<UIState>((set) => ({
  isExpanded: getStoredSidebarExpanded(),
  isMobileSidebarOpen: false,
  settingsDialogOpen: false,
  settingsDialogTab: 'keys',

  toggleSidebar: (isCompact) => {
    if (isCompact) {
      set((state) => ({ isMobileSidebarOpen: !state.isMobileSidebarOpen }));
    } else {
      set((state) => {
        const nextExpanded = !state.isExpanded;
        localStorage.setItem('sidebar-expanded', JSON.stringify(nextExpanded));
        return { isExpanded: nextExpanded };
      });
    }
  },

  closeMobileSidebar: () => set({ isMobileSidebarOpen: false }),

  openSettings: (tab = 'keys') =>
    set({
      settingsDialogOpen: true,
      settingsDialogTab: tab,
    }),

  closeSettings: () => set({ settingsDialogOpen: false }),

  setSettingsTab: (tab) => set({ settingsDialogTab: tab }),
}));

import { useState, useRef, useEffect } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';
import './App.css';
import { Sidebar } from './components/Sidebar';
import { TopNav } from './components/TopNav';
import { useChatSessions } from './hooks/useChatSessions';
import { APP_ROUTES } from './routes';
import type { AppRouteContext, ChatMode } from './types';

const COMPACT_LAYOUT_QUERY = '(max-width: 1024px)';

function App() {
  const {
    sessions,
    activeChatId,
    messages,
    isTyping,
    handleSend,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
  } = useChatSessions();
  const [mode, setMode] = useState<ChatMode>(() => {
    const stored = localStorage.getItem('chat-mode');
    if (stored) return stored as ChatMode;
    return 'direct';
  });
  const [isExpanded, setIsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('sidebar-expanded');
    if (stored) return JSON.parse(stored);
    return false;
  });
  const [isCompactLayout, setIsCompactLayout] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia(COMPACT_LAYOUT_QUERY).matches;
  });
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    localStorage.setItem('sidebar-expanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  useEffect(() => {
    localStorage.setItem('chat-mode', mode);
  }, [mode]);

  useEffect(() => {
    const mediaQuery = window.matchMedia(COMPACT_LAYOUT_QUERY);

    const handleMediaQueryChange = (event: MediaQueryListEvent) => {
      setIsCompactLayout(event.matches);
      if (!event.matches) {
        setIsMobileSidebarOpen(false);
      }
    };

    mediaQuery.addEventListener('change', handleMediaQueryChange);

    return () => mediaQuery.removeEventListener('change', handleMediaQueryChange);
  }, []);

  useEffect(() => {
    if (!isCompactLayout || !isMobileSidebarOpen) {
      document.body.style.overflow = '';
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsMobileSidebarOpen(false);
      }
    };

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = '';
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isCompactLayout, isMobileSidebarOpen]);

  useEffect(() => {
    if (location.pathname !== APP_ROUTES.chat) {
      return;
    }

    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [location.pathname, messages, isTyping]);

  const toggleSidebar = () => {
    if (isCompactLayout) {
      setIsMobileSidebarOpen((prev) => !prev);
      return;
    }

    setIsExpanded((prev) => !prev);
  };

  const closeMobileSidebar = () => {
    if (isCompactLayout) {
      setIsMobileSidebarOpen(false);
    }
  };

  const handleNewChatAndCloseSidebar = () => {
    handleNewChat();
    closeMobileSidebar();
    navigate(APP_ROUTES.chat);
  };

  const handleSelectChatAndCloseSidebar = (id: string) => {
    handleSelectChat(id);
    closeMobileSidebar();
    navigate(APP_ROUTES.chat);
  };

  const isChatRoute = location.pathname === APP_ROUTES.chat;
  const isSidebarExpanded = isCompactLayout ? isMobileSidebarOpen : isExpanded;
  const outletContext: AppRouteContext = {
    sessions,
    activeChatId,
    messages,
    isTyping,
    handleSend,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
  };

  return (
    <div className="layout-wrapper">
      <Sidebar
        isExpanded={isSidebarExpanded}
        isCompact={isCompactLayout}
        onToggle={toggleSidebar}
        onDismiss={closeMobileSidebar}
        onNewChat={handleNewChatAndCloseSidebar}
        history={sessions}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChatAndCloseSidebar}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
      />
      <main className="app-container" ref={scrollRef}>
        <TopNav
          mode={mode}
          onModeChange={setMode}
          showModeSelector={isChatRoute}
          isCompactLayout={isCompactLayout}
          isSidebarOpen={isMobileSidebarOpen}
          onToggleSidebar={toggleSidebar}
        />
        <Outlet context={outletContext} />
      </main>
    </div>
  );
}

export default App;

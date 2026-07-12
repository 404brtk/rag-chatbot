import { useState, useRef, useEffect, useLayoutEffect } from 'react';
import { Outlet, useLocation } from 'react-router';
import './App.css';
import { Sidebar } from './components/Sidebar';
import { TopNav } from './components/TopNav';
import { AuthDialog } from './components/AuthDialog';
import { SettingsDialog } from './components/SettingsDialog';
import { useChatSessions } from './hooks/useChatSessions';
import { useAuth } from './hooks/useAuth';
import { useMediaQuery } from './hooks/useMediaQuery';
import type { AppRouteContext } from './types';

const COMPACT_LAYOUT_QUERY = '(max-width: 1024px)';

function App() {
  const {
    sessions,
    activeChatId,
    messages,
    mode,
    isTyping,
    handleSend,
    handleStop,
    handleModeChange,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
    provider,
    model,
    setProvider,
    setModel,
    models,
    ragEnabled,
    setRagEnabled,
    compactionEnabled,
    setCompactionEnabled,
    loadMoreMessages,
    selectedDocIds,
    setSelectedDocIds,
    loadMoreConversations,
    totalConversationsCount,
  } = useChatSessions();
  const [isExpanded, setIsExpanded] = useState<boolean>(() => {
    const stored = localStorage.getItem('sidebar-expanded');
    if (stored) return JSON.parse(stored);
    return false;
  });
  const isCompactLayout = useMediaQuery(COMPACT_LAYOUT_QUERY);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [authDialogTab, setAuthDialogTab] = useState<'login' | 'register'>('login');
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [settingsDialogTab, setSettingsDialogTab] = useState<'keys' | 'docs' | 'get-docs'>('keys');

  const { isAuthenticated, userEmail, logout } = useAuth();

  const scrollRef = useRef<HTMLElement>(null);
  const location = useLocation();

  useEffect(() => {
    localStorage.setItem('sidebar-expanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  if (!isCompactLayout && isMobileSidebarOpen) {
    setIsMobileSidebarOpen(false);
  }

  const prevFirstMessageId = useRef<string | null>(null);
  const prevScrollHeight = useRef<number>(0);
  const prevMessagesLength = useRef<number>(0);
  const prevActiveChatId = useRef<string | null>(null);

  useLayoutEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const chatChanged = activeChatId !== prevActiveChatId.current;
    prevActiveChatId.current = activeChatId;

    const firstMsgId = messages[0]?.id || null;

    if (chatChanged) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: 'auto',
      });
      prevFirstMessageId.current = firstMsgId;
      prevScrollHeight.current = container.scrollHeight;
      prevMessagesLength.current = messages.length;
      return;
    }

    const isPrepended =
      prevFirstMessageId.current !== null &&
      firstMsgId !== prevFirstMessageId.current &&
      messages.length > prevMessagesLength.current;

    if (isPrepended) {
      const changeInHeight = container.scrollHeight - prevScrollHeight.current;
      container.scrollTop = container.scrollTop + changeInHeight;
    } else {
      const isChat = location.pathname === '/' || location.pathname.startsWith('/chat/');
      if (isChat) {
        const lastMessage = messages[messages.length - 1];
        const isUserSent = lastMessage && lastMessage.role === 'user';

        const wasAtBottom =
          container.scrollTop + container.clientHeight >= prevScrollHeight.current - 12;

        if (isUserSent || wasAtBottom) {
          container.scrollTo({
            top: container.scrollHeight,
            behavior: isTyping ? 'auto' : prevFirstMessageId.current === null ? 'auto' : 'smooth',
          });
        }
      }
    }

    prevFirstMessageId.current = firstMsgId;
    prevScrollHeight.current = container.scrollHeight;
    prevMessagesLength.current = messages.length;

    const isScrollable = container.scrollHeight > container.clientHeight;
    if (!isScrollable && activeChatId) {
      const activeSession = sessions.find((s) => s.id === activeChatId);
      if (activeSession && activeSession.nextCursor) {
        loadMoreMessages();
      }
    }
  }, [messages, location.pathname, isTyping, activeChatId, sessions, loadMoreMessages]);

  const handleScroll = (e: React.UIEvent<HTMLElement>) => {
    const target = e.currentTarget;
    const isChat = location.pathname === '/' || location.pathname.startsWith('/chat/');

    if (isChat) {
      prevScrollHeight.current = target.scrollHeight;
      if (target.scrollTop <= 50) {
        loadMoreMessages();
      }
    } else if (location.pathname === '/history') {
      const isNearBottom = target.scrollHeight - target.scrollTop - target.clientHeight <= 100;
      if (isNearBottom) {
        loadMoreConversations();
      }
    }
  };

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
  };

  const handleSelectChatAndCloseSidebar = (id: string) => {
    handleSelectChat(id);
    closeMobileSidebar();
  };

  const handleLogout = () => {
    logout();
    handleNewChat();
  };

  const openAuthDialog = (tab: 'login' | 'register' = 'login') => {
    setAuthDialogTab(tab);
    setAuthDialogOpen(true);
  };

  const triggerSettings = (tab: 'keys' | 'docs' | 'get-docs' = 'keys') => {
    setSettingsDialogTab(tab);
    setSettingsDialogOpen(true);
  };

  const isChatRoute = location.pathname === '/' || location.pathname.startsWith('/chat/');
  const isSidebarExpanded = isCompactLayout ? isMobileSidebarOpen : isExpanded;
  const outletContext: AppRouteContext = {
    sessions,
    activeChatId,
    messages,
    mode,
    isTyping,
    handleSend,
    handleStop,
    handleNewChat,
    handleSelectChat,
    handleDeleteChat,
    handleRenameChat,
    provider,
    model,
    setProvider,
    setModel,
    models,
    isAuthenticated,
    ragEnabled,
    setRagEnabled,
    compactionEnabled,
    setCompactionEnabled,
    openAuthDialog,
    userEmail,
    selectedDocIds,
    setSelectedDocIds,
    loadMoreConversations,
    totalConversationsCount,
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
        onOpenSettings={triggerSettings}
        loadMoreConversations={loadMoreConversations}
      />
      <main className="app-container" ref={scrollRef} onScroll={handleScroll}>
        <TopNav
          mode={mode}
          onModeChange={handleModeChange}
          showModeSelector={isChatRoute}
          isCompactLayout={isCompactLayout}
          isSidebarOpen={isMobileSidebarOpen}
          onToggleSidebar={toggleSidebar}
          isAuthenticated={isAuthenticated}
          userEmail={userEmail}
          onOpenLogin={() => {
            setAuthDialogTab('login');
            setAuthDialogOpen(true);
          }}
          onOpenRegister={() => {
            setAuthDialogTab('register');
            setAuthDialogOpen(true);
          }}
          onLogout={handleLogout}
        />
        <Outlet context={outletContext} />
      </main>
      {authDialogOpen ? (
        <AuthDialog
          isOpen={authDialogOpen}
          onClose={() => setAuthDialogOpen(false)}
          defaultTab={authDialogTab}
        />
      ) : null}
      {settingsDialogOpen ? (
        <SettingsDialog
          isOpen={settingsDialogOpen}
          onClose={() => setSettingsDialogOpen(false)}
          defaultTab={settingsDialogTab}
        />
      ) : null}
    </div>
  );
}

export default App;

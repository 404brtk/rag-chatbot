import { useRef, useEffect, useLayoutEffect } from 'react';
import { Outlet, useLocation, useParams } from 'react-router';
import './App.css';
import { Sidebar } from './components/Sidebar';
import { TopNav } from './components/TopNav';
import { AuthDialog } from './components/AuthDialog';
import { SettingsDialog } from './components/SettingsDialog';
import { useMediaQuery } from './hooks/useMediaQuery';
import { useAuthStore } from './stores/useAuthStore';
import { useChatStore, selectActiveMessages } from './stores/useChatStore';
import { useUIStore } from './stores/useUIStore';

const COMPACT_LAYOUT_QUERY = '(max-width: 1024px)';

function App() {
  const { chatId } = useParams<{ chatId?: string }>();
  const location = useLocation();
  const scrollRef = useRef<HTMLElement>(null);
  const isCompactLayout = useMediaQuery(COMPACT_LAYOUT_QUERY);

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isMobileSidebarOpen = useUIStore((s) => s.isMobileSidebarOpen);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);

  const activeChatId = useChatStore((s) => s.activeChatId);
  const setActiveChatId = useChatStore((s) => s.setActiveChatId);
  const loadConversations = useChatStore((s) => s.loadConversations);
  const loadMoreConversations = useChatStore((s) => s.loadMoreConversations);
  const loadModels = useChatStore((s) => s.loadModels);
  const loadMessages = useChatStore((s) => s.loadMessages);
  const loadMoreMessages = useChatStore((s) => s.loadMoreMessages);
  const sessions = useChatStore((s) => s.sessions);
  const messages = useChatStore(selectActiveMessages);
  const isTyping = useChatStore((s) => s.isTyping);

  useEffect(() => {
    setActiveChatId(chatId || null);
  }, [chatId, setActiveChatId]);

  useEffect(() => {
    void loadConversations(isAuthenticated);
    void loadModels(isAuthenticated);
  }, [isAuthenticated, loadConversations, loadModels]);

  useEffect(() => {
    if (activeChatId) {
      void loadMessages(activeChatId);
    }
  }, [activeChatId, loadMessages]);

  useEffect(() => {
    if (!isCompactLayout && isMobileSidebarOpen) {
      closeMobileSidebar();
    }
  }, [isCompactLayout, isMobileSidebarOpen, closeMobileSidebar]);

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
        void loadMoreMessages();
      }
    }
  }, [messages, location.pathname, isTyping, activeChatId, sessions, loadMoreMessages]);

  const handleScroll = (e: React.UIEvent<HTMLElement>) => {
    const target = e.currentTarget;
    const isChat = location.pathname === '/' || location.pathname.startsWith('/chat/');

    if (isChat) {
      prevScrollHeight.current = target.scrollHeight;
      if (target.scrollTop <= 50) {
        void loadMoreMessages();
      }
    } else if (location.pathname === '/history') {
      const isNearBottom = target.scrollHeight - target.scrollTop - target.clientHeight <= 100;
      if (isNearBottom) {
        void loadMoreConversations();
      }
    }
  };

  return (
    <div className="layout-wrapper">
      <Sidebar />
      <main className="app-container" ref={scrollRef} onScroll={handleScroll}>
        <TopNav />
        <Outlet />
      </main>
      <AuthDialog />
      <SettingsDialog />
    </div>
  );
}

export default App;

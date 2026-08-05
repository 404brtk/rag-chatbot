import { useState, useRef, useEffect, useMemo } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import { SessionOptionsMenu } from './SessionOptionsMenu';
import { useSessionActions } from '../hooks/useSessionActions';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { APP_ROUTES } from '../routes';
import { useChatStore } from '../stores/useChatStore';
import { useUIStore } from '../stores/useUIStore';
import './Sidebar.css';

const COMPACT_LAYOUT_QUERY = '(max-width: 1024px)';

interface TooltipProps {
  text: string;
  disabled?: boolean;
  children: React.ReactNode;
}

function Tooltip({ text, disabled, children }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);

  const show = () => {
    if (disabled) return;
    const triggerElement = triggerRef.current?.querySelector<HTMLElement>('button, a');
    if (triggerElement) {
      const rect = triggerElement.getBoundingClientRect();
      setPosition({
        top: rect.top + rect.height / 2,
        left: rect.right + 8,
      });
    }
    setVisible(true);
  };

  const hide = () => setVisible(false);

  return (
    <div
      ref={triggerRef}
      className="sidebar-tooltip-trigger"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      onPointerDown={hide}
    >
      {children}
      {visible &&
        !disabled &&
        createPortal(
          <span className="sidebar-tooltip" style={{ top: position.top, left: position.left }}>
            {text}
          </span>,
          document.body
        )}
    </div>
  );
}

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const isCompact = useMediaQuery(COMPACT_LAYOUT_QUERY);

  const isExpandedState = useUIStore((s) => s.isExpanded);
  const isMobileSidebarOpen = useUIStore((s) => s.isMobileSidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const openSettings = useUIStore((s) => s.openSettings);

  const isExpanded = isCompact ? isMobileSidebarOpen : isExpandedState;

  const history = useChatStore((s) => s.sessions);
  const activeChatId = useChatStore((s) => s.activeChatId);
  const selectChat = useChatStore((s) => s.selectChat);
  const newChat = useChatStore((s) => s.newChat);
  const deleteChat = useChatStore((s) => s.deleteChat);
  const renameChat = useChatStore((s) => s.renameChat);
  const loadMoreConversations = useChatStore((s) => s.loadMoreConversations);

  const handleRenameWrapper = (id: string, title: string) => {
    void renameChat(id, title);
  };

  const {
    editingId,
    editValue,
    optionsMenu,
    editInputRef,
    setEditValue,
    startRename,
    saveRename,
    handleRenameKeyDown,
    toggleOptionsMenu,
    closeOptionsMenu,
  } = useSessionActions(handleRenameWrapper);

  const dialogRef = useRef<HTMLDialogElement>(null);

  const sortedHistory = useMemo(() => {
    return [...history].sort((a, b) => b.timestamp - a.timestamp);
  }, [history]);

  useEffect(() => {
    if (!isCompact) return;
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isExpanded && !dialog.open) {
      dialog.showModal();
    } else if (!isExpanded && dialog.open) {
      dialog.close();
    }
  }, [isCompact, isExpanded]);

  const handleDismiss = () => {
    if (isCompact) {
      closeMobileSidebar();
      return;
    }
    toggleSidebar(isCompact);
  };

  const toggleLabel = isCompact && isExpanded ? 'Close sidebar' : 'Open sidebar';

  const handleHistoryNavClick = () => {
    if (isCompact) {
      closeMobileSidebar();
    }
  };

  const handleDialogClick = (e: React.MouseEvent<HTMLDialogElement>) => {
    if (e.target === e.currentTarget) {
      handleDismiss();
    }
  };

  const handleSidebarScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget;
    if (target.scrollHeight - target.scrollTop - target.clientHeight <= 30) {
      void loadMoreConversations();
    }
  };

  const handleNewChatClick = () => {
    newChat(navigate);
    if (isCompact) {
      closeMobileSidebar();
    }
  };

  const handleSelectChatClick = (id: string) => {
    selectChat(id, navigate);
    if (isCompact) {
      closeMobileSidebar();
    }
  };

  const handleDeleteChatClick = (id: string) => {
    void deleteChat(id, navigate);
  };

  const sidebarContent = (
    <aside
      className={`sidebar ${isExpanded ? 'expanded' : 'collapsed'}${isCompact ? ' compact' : ''}`}
    >
      <div className="sidebar-nav">
        <Tooltip text="Open sidebar" disabled={isExpanded || isCompact}>
          <button
            className="sidebar-icon-btn toggle-btn"
            onClick={() => toggleSidebar(isCompact)}
            aria-label={toggleLabel}
            type="button"
          >
            <Icon name="sidebar" />
          </button>
        </Tooltip>

        <Tooltip text="New Chat" disabled={isExpanded || isCompact}>
          <button
            className="sidebar-icon-btn action-btn primary-action-btn"
            onClick={handleNewChatClick}
            aria-label="New chat"
            type="button"
          >
            <div className="icon-wrapper">
              <Icon name="plus" />
            </div>
            <span className="sidebar-text">New Chat</span>
          </button>
        </Tooltip>

        <Tooltip text="History" disabled={isExpanded || isCompact}>
          <NavLink
            className={({ isActive }) =>
              `sidebar-icon-btn action-btn sidebar-history-link${isActive ? ' active-route' : ''}`
            }
            to={APP_ROUTES.history}
            onClick={handleHistoryNavClick}
            aria-label="History"
          >
            <div className="icon-wrapper">
              <Icon name="history" />
            </div>
            <span className="sidebar-text">History</span>
          </NavLink>
        </Tooltip>
      </div>

      {isExpanded && <div className="sidebar-divider" />}

      {isExpanded && (
        <div className="sidebar-history-container" onScroll={handleSidebarScroll}>
          <div className="history-group">
            {sortedHistory.map((session) => (
              <div
                key={session.id}
                className={`history-item-wrapper ${(location.pathname === APP_ROUTES.chat || location.pathname.startsWith('/chat/')) && session.id === activeChatId ? 'active' : ''} ${optionsMenu?.id === session.id ? 'hover-locked' : ''}`}
              >
                {editingId === session.id ? (
                  <div className="history-item-edit-mode">
                    <input
                      ref={editInputRef}
                      type="text"
                      className="history-edit-input"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={handleRenameKeyDown}
                      onBlur={saveRename}
                    />
                    <button
                      className="inline-action-btn"
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={saveRename}
                    >
                      <Icon name="check" />
                    </button>
                  </div>
                ) : (
                  <div
                    className="sidebar-icon-btn history-item-btn"
                    role="button"
                    tabIndex={0}
                    aria-label={`Conversation: ${session.title}`}
                    onClick={() => handleSelectChatClick(session.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleSelectChatClick(session.id);
                      }
                    }}
                  >
                    <span className="sidebar-text history-text">{session.title}</span>

                    <div className="history-actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="inline-action-btn"
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          const rect = e.currentTarget.getBoundingClientRect();
                          toggleOptionsMenu(session.id, rect);
                        }}
                      >
                        <Icon name="more" />
                      </button>
                      {optionsMenu?.id === session.id && (
                        <SessionOptionsMenu
                          rect={optionsMenu.rect}
                          onRename={() => startRename(session.id, session.title)}
                          onDelete={() => {
                            handleDeleteChatClick(session.id);
                            closeOptionsMenu();
                          }}
                          onClose={closeOptionsMenu}
                        />
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {isExpanded && <div className="sidebar-divider" />}

      <div className="sidebar-bottom">
        <Tooltip text="API Keys" disabled={isExpanded || isCompact}>
          <button
            className="sidebar-icon-btn action-btn keys-btn"
            aria-label="Manage API keys"
            type="button"
            onClick={() => {
              openSettings('keys');
              if (isCompact) closeMobileSidebar();
            }}
          >
            <div className="icon-wrapper">
              <Icon name="pencil" />
            </div>
            <span className="sidebar-text">API Keys</span>
          </button>
        </Tooltip>

        <Tooltip text="Documents" disabled={isExpanded || isCompact}>
          <button
            className="sidebar-icon-btn action-btn docs-btn"
            aria-label="Manage documents"
            type="button"
            onClick={() => {
              openSettings('docs');
              if (isCompact) closeMobileSidebar();
            }}
          >
            <div className="icon-wrapper">
              <Icon name="file" />
            </div>
            <span className="sidebar-text">Documents</span>
          </button>
        </Tooltip>

        <Tooltip text="Get Docs" disabled={isExpanded || isCompact}>
          <button
            className="sidebar-icon-btn action-btn scraper-btn"
            aria-label="Get Docs"
            type="button"
            onClick={() => {
              openSettings('get-docs');
              if (isCompact) closeMobileSidebar();
            }}
          >
            <div className="icon-wrapper">
              <Icon name="search" />
            </div>
            <span className="sidebar-text">Get Docs</span>
          </button>
        </Tooltip>
      </div>
    </aside>
  );

  if (isCompact) {
    return (
      <dialog
        ref={dialogRef}
        className="sidebar-dialog"
        onClose={handleDismiss}
        onClick={handleDialogClick}
      >
        {sidebarContent}
      </dialog>
    );
  }

  return sidebarContent;
}

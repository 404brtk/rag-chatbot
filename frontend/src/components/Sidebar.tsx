import { useState, useRef } from 'react';
import { NavLink } from 'react-router';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import { SessionOptionsMenu } from './SessionOptionsMenu';
import './Sidebar.css';
import { useSessionActions } from '../hooks/useSessionActions';
import { APP_ROUTES } from '../routes';
import type { ChatSession } from '../types';

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

interface SidebarProps {
  isExpanded: boolean;
  isCompact?: boolean;
  onToggle: () => void;
  onDismiss?: () => void;
  onNewChat: () => void;
  history: ChatSession[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onRenameChat: (id: string, title: string) => void;
}

export function Sidebar({
  isExpanded,
  isCompact = false,
  onToggle,
  onDismiss,
  onNewChat,
  history,
  activeChatId,
  onSelectChat,
  onDeleteChat,
  onRenameChat,
}: SidebarProps) {
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
  } = useSessionActions(onRenameChat);

  if (isCompact && !isExpanded) {
    return null;
  }

  const handleDismiss = () => {
    if (onDismiss) {
      onDismiss();
      return;
    }

    onToggle();
  };

  const toggleLabel = isCompact && isExpanded ? 'Close sidebar' : 'Open sidebar';

  const handleHistoryNavClick = () => {
    if (isCompact && onDismiss) {
      onDismiss();
    }
  };

  return (
    <>
      {isCompact && isExpanded && (
        <button
          className="sidebar-mobile-backdrop"
          type="button"
          aria-label="Close sidebar overlay"
          onClick={handleDismiss}
        />
      )}

      <aside
        className={`sidebar ${isExpanded ? 'expanded' : 'collapsed'}${isCompact ? ' compact' : ''}`}
      >
        <div className="sidebar-nav">
          <Tooltip text="Open sidebar" disabled={isExpanded || isCompact}>
            <button
              className="sidebar-icon-btn toggle-btn"
              onClick={isCompact ? handleDismiss : onToggle}
              aria-label={toggleLabel}
            >
              <Icon name="sidebar" />
            </button>
          </Tooltip>

          <Tooltip text="New Chat" disabled={isExpanded || isCompact}>
            <button
              className="sidebar-icon-btn action-btn primary-action-btn"
              onClick={onNewChat}
              aria-label="New chat"
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
          <div className="sidebar-history-container">
            <div className="history-group">
              {history.map((session) => (
                <div
                  key={session.id}
                  className={`history-item-wrapper ${session.id === activeChatId ? 'active' : ''} ${optionsMenu?.id === session.id ? 'hover-locked' : ''}`}
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
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={saveRename}
                      >
                        <Icon name="check" />
                      </button>
                    </div>
                  ) : (
                    <button
                      className="sidebar-icon-btn history-item-btn"
                      aria-label={`Conversation: ${session.title}`}
                      onClick={() => onSelectChat(session.id)}
                    >
                      <span className="sidebar-text history-text">{session.title}</span>

                      <div className="history-actions" onClick={(e) => e.stopPropagation()}>
                        <button
                          className="inline-action-btn"
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
                              onDeleteChat(session.id);
                              closeOptionsMenu();
                            }}
                            onClose={closeOptionsMenu}
                          />
                        )}
                      </div>
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {isExpanded && <div className="sidebar-divider" />}

        <div className="sidebar-bottom">
          <Tooltip text="View Profile" disabled={isExpanded || isCompact}>
            <button className="sidebar-icon-btn action-btn user-btn" aria-label="User profile">
              <div className="icon-wrapper">
                <Icon name="user" />
              </div>
              <span className="sidebar-text">Profile</span>
            </button>
          </Tooltip>
        </div>
      </aside>
    </>
  );
}

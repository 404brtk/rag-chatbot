import { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Icon } from '../components/Icon';
import { SessionOptionsMenu } from '../components/SessionOptionsMenu';
import { useAppRouteContext } from '../hooks/useAppRouteContext';
import { useSessionActions } from '../hooks/useSessionActions';
import { APP_ROUTES } from '../routes';
import './HistoryPage.css';

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatMessageCount(count: number) {
  return `${count} message${count === 1 ? '' : 's'}`;
}

export function HistoryPage() {
  const { sessions, handleSelectChat, handleDeleteChat, handleRenameChat, handleNewChat } =
    useAppRouteContext();
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
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
  } = useSessionActions(handleRenameChat);

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const visibleSessions = useMemo(() => {
    const sortedSessions = [...sessions].sort(
      (first, second) => second.timestamp - first.timestamp
    );

    if (normalizedQuery === '') {
      return sortedSessions;
    }

    return sortedSessions.filter((session) =>
      session.title.toLowerCase().includes(normalizedQuery)
    );
  }, [normalizedQuery, sessions]);

  const openChat = (id: string) => {
    handleSelectChat(id);
    navigate(APP_ROUTES.chat);
  };

  const openNewChat = () => {
    handleNewChat();
    navigate(APP_ROUTES.chat);
  };

  const clearSearch = () => {
    setSearchQuery('');
    searchInputRef.current?.focus();
  };

  const historyCountLabel = `${visibleSessions.length} conversation${visibleSessions.length === 1 ? '' : 's'}`;

  return (
    <section className="history-page">
      <header className="history-page-header">
        <div className="history-page-header-copy">
          <h1 className="history-page-title">History</h1>
          <p className="history-page-subtitle">{historyCountLabel}</p>
        </div>

        <button className="history-page-new-chat" type="button" onClick={openNewChat}>
          <Icon name="plus" size={14} />
          New Chat
        </button>
      </header>

      <div className="history-page-search-field" role="search">
        <Icon name="search" size={14} />
        <input
          ref={searchInputRef}
          className="history-page-search-input"
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search chats"
          aria-label="Search chats"
          autoComplete="off"
          spellCheck={false}
        />
        {searchQuery !== '' && (
          <button
            type="button"
            className="history-page-search-clear"
            aria-label="Clear search"
            onMouseDown={(e) => e.preventDefault()}
            onClick={clearSearch}
          >
            <Icon name="x" size={14} />
          </button>
        )}
      </div>

      {visibleSessions.length === 0 ? (
        <div className="history-page-empty">
          {searchQuery.trim() !== '' ? (
            <>
              <p className="history-page-empty-title">No matching chats</p>
              <p className="history-page-empty-description">
                Try a different phrase or clear your search.
              </p>
            </>
          ) : (
            <>
              <p className="history-page-empty-title">No chats yet</p>
              <p className="history-page-empty-description">
                Start a conversation and it will appear in your history.
              </p>
              <button className="history-page-empty-cta" type="button" onClick={openNewChat}>
                Start chatting
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="history-page-list" role="list">
          {visibleSessions.map((session) => {
            const isEditing = editingId === session.id;

            return (
              <article
                key={session.id}
                role="listitem"
                className={`history-page-item ${isEditing ? 'editing' : 'interactive'}`}
                tabIndex={isEditing ? undefined : 0}
                aria-label={isEditing ? undefined : `Open conversation: ${session.title}`}
                onClick={isEditing ? undefined : () => openChat(session.id)}
                onKeyDown={
                  isEditing
                    ? undefined
                    : (e) => {
                        if (e.target !== e.currentTarget) {
                          return;
                        }

                        if (e.key === 'Enter') {
                          e.preventDefault();
                          openChat(session.id);
                        }
                      }
                }
              >
                {isEditing ? (
                  <div className="history-page-item-edit">
                    <input
                      ref={editInputRef}
                      type="text"
                      className="history-page-edit-input"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={handleRenameKeyDown}
                      onBlur={saveRename}
                    />
                    <button
                      className="history-page-action-btn"
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={saveRename}
                      aria-label="Save rename"
                    >
                      <Icon name="check" size={14} />
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="history-page-item-main">
                      <span className="history-page-item-title">{session.title}</span>
                      <span className="history-page-item-meta">
                        {formatMessageCount(session.messages.length)}
                      </span>
                    </div>

                    <time
                      className="history-page-item-time"
                      dateTime={new Date(session.timestamp).toISOString()}
                    >
                      {DATE_FORMATTER.format(session.timestamp)}
                    </time>

                    <div className="history-page-item-actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="history-page-action-btn"
                        type="button"
                        aria-label={`Conversation options: ${session.title}`}
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          toggleOptionsMenu(session.id, rect);
                        }}
                      >
                        <Icon name="more" size={14} />
                      </button>

                      {optionsMenu?.id === session.id && (
                        <SessionOptionsMenu
                          rect={optionsMenu.rect}
                          onRename={() => startRename(session.id, session.title)}
                          onDelete={() => {
                            handleDeleteChat(session.id);
                            closeOptionsMenu();
                          }}
                          onClose={closeOptionsMenu}
                        />
                      )}
                    </div>
                  </>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router';
import type { ChatMode } from '../types';
import { Icon } from './Icon';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { useAuthStore } from '../stores/useAuthStore';
import { useChatStore, selectActiveMode } from '../stores/useChatStore';
import { useUIStore } from '../stores/useUIStore';
import './TopNav.css';

const COMPACT_LAYOUT_QUERY = '(max-width: 1024px)';

export function TopNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const isCompactLayout = useMediaQuery(COMPACT_LAYOUT_QUERY);
  const showModeSelector = location.pathname === '/' || location.pathname.startsWith('/chat/');

  const mode = useChatStore(selectActiveMode);
  const setMode = useChatStore((s) => s.setMode);
  const newChat = useChatStore((s) => s.newChat);

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const userEmail = useAuthStore((s) => s.userEmail);
  const openAuthDialog = useAuthStore((s) => s.openAuthDialog);
  const logout = useAuthStore((s) => s.logout);

  const isSidebarOpen = useUIStore((s) => s.isMobileSidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleDropdown = () => setIsDropdownOpen(!isDropdownOpen);

  const handleSelectMode = (newMode: ChatMode) => {
    setMode(newMode, navigate);
    setIsDropdownOpen(false);
  };

  const handleLogout = async () => {
    setIsLoggingOut(true);
    setLogoutError(null);
    try {
      await logout();
      newChat(navigate);
    } catch (err) {
      setLogoutError(err instanceof Error ? err.message : 'Logout failed. Please retry.');
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <header className={`topnav ${isCompactLayout ? 'compact' : ''}`}>
      <div className="topnav-left">
        {isCompactLayout && (
          <button
            className={`sidebar-mobile-toggle${isSidebarOpen ? ' open' : ''}`}
            onClick={() => toggleSidebar(true)}
            aria-expanded={isSidebarOpen}
            aria-label={isSidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            type="button"
          >
            <Icon name="sidebar" />
          </button>
        )}

        {showModeSelector && (
          <div className="mode-selector" ref={dropdownRef}>
            <button
              className="mode-btn"
              onClick={toggleDropdown}
              aria-expanded={isDropdownOpen}
              type="button"
            >
              {mode === 'direct' ? 'Direct' : 'Side by Side'}
              <span className="mode-btn-icon">
                <Icon name="chevron-down" size={12} />
              </span>
            </button>
            {isDropdownOpen && (
              <ul className="mode-dropdown">
                <li
                  className={`mode-dropdown-item ${mode === 'direct' ? 'selected' : ''}`}
                  onClick={() => handleSelectMode('direct')}
                >
                  Direct
                </li>
                <li
                  className={`mode-dropdown-item ${mode === 'side-by-side' ? 'selected' : ''}`}
                  onClick={() => handleSelectMode('side-by-side')}
                >
                  Side by Side
                </li>
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="topnav-right">
        {isAuthenticated ? (
          <>
            <span className="user-email-label">{userEmail}</span>
            {logoutError && <span role="alert">{logoutError}</span>}
            <button
              className="btn-secondary"
              type="button"
              onClick={handleLogout}
              disabled={isLoggingOut}
            >
              {isLoggingOut ? 'Logging out...' : 'Logout'}
            </button>
          </>
        ) : (
          <>
            <button
              className="btn-secondary compact-register"
              type="button"
              onClick={() => openAuthDialog('register')}
            >
              Register
            </button>
            <button
              className="btn-primary btn-login-nav"
              type="button"
              onClick={() => openAuthDialog('login')}
            >
              Login
            </button>
          </>
        )}
      </div>
    </header>
  );
}

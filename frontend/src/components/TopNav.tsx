import { useState, useEffect, useRef } from 'react';
import './TopNav.css';
import type { ChatMode } from '../types';
import { Icon } from './Icon';

interface TopNavProps {
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
}

export function TopNav({ mode, onModeChange }: TopNavProps) {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
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
    onModeChange(newMode);
    setIsDropdownOpen(false);
  };

  return (
    <header className="topnav">
      <div className="topnav-left">
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
      </div>

      <div className="topnav-right">
        <button className="btn-register" type="button">
          Register
        </button>
        <button className="btn-login" type="button">
          Login
        </button>
      </div>
    </header>
  );
}

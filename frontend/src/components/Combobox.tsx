import { useState, useEffect, useRef } from 'react';
import { Icon } from './Icon';
import './Combobox.css';

interface ComboboxProps {
  value: string;
  options: string[];
  onChange: (val: string) => void;
  onCommitOption?: (opt: string) => void;
  onRemoveOption?: (opt: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function Combobox({
  value,
  options,
  onChange,
  onCommitOption,
  onRemoveOption,
  disabled,
  placeholder = 'Enter model...',
}: ComboboxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [openDirection, setOpenDirection] = useState<'up' | 'down'>('down');
  const [coords, setCoords] = useState<{
    left: number;
    top?: number;
    bottom?: number;
    width?: number;
  }>({ left: 0 });

  const containerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLUListElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [inputValue, setInputValue] = useState(value);

  useEffect(() => {
    setInputValue(value);
  }, [value]);

  useEffect(() => {
    const popover = popoverRef.current;
    if (!popover) return;

    const handleToggle = (e: Event) => {
      const toggleEvent = e as ToggleEvent;
      setIsOpen(toggleEvent.newState === 'open');
    };

    popover.addEventListener('toggle', handleToggle);
    return () => popover.removeEventListener('toggle', handleToggle);
  }, []);

  const openDropdown = () => {
    if (disabled) return;
    const popover = popoverRef.current;
    const container = containerRef.current;
    if (!popover || !container) return;

    if (!isOpen) {
      const rect = container.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const neededSpace = 200;

      if (spaceBelow >= neededSpace) {
        setOpenDirection('down');
        setCoords({
          left: rect.left,
          top: rect.bottom + 8,
          bottom: undefined,
          width: Math.max(rect.width, 220),
        });
      } else {
        setOpenDirection('up');
        setCoords({
          left: rect.left,
          top: undefined,
          bottom: window.innerHeight - rect.top + 8,
          width: Math.max(rect.width, 220),
        });
      }

      popover.showPopover();
    }
  };

  const closeDropdown = () => {
    popoverRef.current?.hidePopover();
  };

  const handleToggleClick = () => {
    if (disabled) return;
    if (isOpen) {
      closeDropdown();
    } else {
      openDropdown();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const trimmed = inputValue.trim();
      onChange(trimmed);
      onCommitOption?.(trimmed);
      closeDropdown();
    }
  };

  const handleSelect = (opt: string) => {
    setInputValue(opt);
    onChange(opt);
    onCommitOption?.(opt);
    closeDropdown();
  };

  const handleRemove = (e: React.MouseEvent, opt: string) => {
    e.stopPropagation();
    onRemoveOption?.(opt);
  };

  return (
    <div ref={containerRef} className="combobox-container">
      <div className={`combobox-field pill-control ${isOpen ? 'active' : ''}`}>
        <input
          ref={inputRef}
          type="text"
          className="combobox-input"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            onChange(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
        />
        <button
          type="button"
          className="combobox-chevron-btn"
          onClick={handleToggleClick}
          disabled={disabled}
          tabIndex={-1}
          aria-label="Toggle options"
          aria-expanded={isOpen}
        >
          <Icon name="chevron-down" size={10} className="custom-dropdown-chevron" />
        </button>
      </div>

      <ul
        ref={popoverRef}
        popover="auto"
        className={`custom-dropdown-menu ${openDirection}`}
        style={{
          position: 'fixed',
          left: `${coords.left}px`,
          top: coords.top !== undefined ? `${coords.top}px` : 'auto',
          bottom: coords.bottom !== undefined ? `${coords.bottom}px` : 'auto',
          width: coords.width !== undefined ? `${coords.width}px` : 'auto',
          margin: 0,
        }}
      >
        {options.length === 0 ? (
          <li className="combobox-empty">Type a model name to save</li>
        ) : (
          options.map((opt) => (
            <li
              key={opt}
              className={`custom-dropdown-item combobox-item ${opt === value ? 'selected' : ''}`}
              onClick={() => handleSelect(opt)}
            >
              <span className="combobox-item-text">{opt}</span>
              {onRemoveOption ? (
                <button
                  type="button"
                  className="combobox-remove-btn"
                  onClick={(e) => handleRemove(e, opt)}
                  title={`Remove ${opt}`}
                  aria-label={`Remove ${opt}`}
                >
                  <Icon name="x" size={10} />
                </button>
              ) : null}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

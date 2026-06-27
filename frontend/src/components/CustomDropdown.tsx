import { useState, useEffect, useRef } from 'react';
import { Icon } from './Icon';
import './CustomDropdown.css';

interface CustomDropdownProps {
  value: string;
  options: string[];
  onChange: (val: string) => void;
  labelFormatter?: (val: string) => string;
  disabled?: boolean;
  variant?: 'compact' | 'form';
}

export function CustomDropdown({
  value,
  options,
  onChange,
  labelFormatter,
  disabled,
  variant = 'compact',
}: CustomDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [openDirection, setOpenDirection] = useState<'up' | 'down'>('down');
  const [coords, setCoords] = useState<{
    left: number;
    top?: number;
    bottom?: number;
    width?: number;
  }>({ left: 0 });
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLUListElement>(null);

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

  const handleToggleClick = () => {
    if (disabled) return;
    const popover = popoverRef.current;
    const button = buttonRef.current;
    if (!popover || !button) return;

    if (!isOpen) {
      const rect = button.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const neededSpace = 250;

      if (spaceBelow >= neededSpace) {
        setOpenDirection('down');
        setCoords({
          left: rect.left,
          top: rect.bottom + 8,
          bottom: undefined,
          width: rect.width,
        });
      } else {
        setOpenDirection('up');
        setCoords({
          left: rect.left,
          top: undefined,
          bottom: window.innerHeight - rect.top + 8,
          width: rect.width,
        });
      }

      popover.showPopover();
    } else {
      popover.hidePopover();
    }
  };

  const handleSelect = (opt: string) => {
    onChange(opt);
    popoverRef.current?.hidePopover();
  };

  return (
    <div className={`custom-dropdown-container ${variant}`}>
      <button
        ref={buttonRef}
        type="button"
        className={`custom-dropdown-btn ${variant === 'compact' ? 'pill-control' : 'form-control'}`}
        onClick={handleToggleClick}
        disabled={disabled}
        aria-expanded={isOpen}
      >
        <span>{labelFormatter ? labelFormatter(value) : value}</span>
        <Icon
          name="chevron-down"
          size={variant === 'compact' ? 10 : 14}
          className="custom-dropdown-chevron"
        />
      </button>
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
        {options.map((opt) => (
          <li
            key={opt}
            className={`custom-dropdown-item ${opt === value ? 'selected' : ''}`}
            onClick={() => handleSelect(opt)}
          >
            {labelFormatter ? labelFormatter(opt) : opt}
          </li>
        ))}
      </ul>
    </div>
  );
}

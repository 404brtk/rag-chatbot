import { useEffect, useRef } from 'react';
import { Icon } from './Icon';
import './SessionOptionsMenu.css';

interface SessionOptionsMenuProps {
  rect: DOMRect;
  onRename: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export function SessionOptionsMenu({ rect, onRename, onDelete, onClose }: SessionOptionsMenuProps) {
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    popoverRef.current?.showPopover();
  }, [onClose]);

  const handleToggle = (event: React.SyntheticEvent<HTMLDivElement>) => {
    if (!event.currentTarget.matches(':popover-open')) {
      onClose();
    }
  };

  return (
    <div
      ref={popoverRef}
      popover="auto"
      className="session-options-menu"
      onToggle={handleToggle}
      style={{
        margin: 0,
        top: rect.bottom + 4,
        left: rect.right,
        transform: 'translateX(-100%)',
      }}
    >
      <button type="button" onClick={onRename}>
        <Icon name="pencil" />
        Rename
      </button>
      <button type="button" className="danger" onClick={onDelete}>
        <Icon name="trash" />
        Delete
      </button>
    </div>
  );
}

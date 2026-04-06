import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import './SessionOptionsMenu.css';

interface SessionOptionsMenuProps {
  rect: DOMRect;
  onRename: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export function SessionOptionsMenu({ rect, onRename, onDelete, onClose }: SessionOptionsMenuProps) {
  return createPortal(
    <>
      <div
        className="session-options-menu-overlay"
        onClick={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div
        className="session-options-menu"
        style={{
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
    </>,
    document.body
  );
}

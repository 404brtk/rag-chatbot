import React, { useEffect, useRef } from 'react';
import { Icon } from './Icon';
import './Modal.css';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
  id?: string;
}

export function Modal({ isOpen, onClose, title, children, className = '', id }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      if (!dialog.open) {
        try {
          dialog.showModal();
        } catch (err) {
          console.warn('Modal showModal failed:', err);
        }
      }
    } else {
      if (dialog.open) {
        dialog.close();
      }
    }
  }, [isOpen]);

  const handleBackdropClick = (e: React.MouseEvent<HTMLDialogElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <dialog
      ref={dialogRef}
      id={id}
      className={`modal-dialog ${className}`}
      onClose={onClose}
      onClick={handleBackdropClick}
    >
      {title ? (
        <div className="modal-header">
          <h3>{title}</h3>
          <button
            type="button"
            className="modal-close-btn"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <Icon name="x" size={16} />
          </button>
        </div>
      ) : null}
      {children}
    </dialog>
  );
}

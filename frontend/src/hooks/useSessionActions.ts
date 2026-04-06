import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

interface OptionsMenuState {
  id: string;
  rect: DOMRect;
}

type RenameHandler = (id: string, title: string) => void;

export function useSessionActions(onRename: RenameHandler) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [optionsMenu, setOptionsMenu] = useState<OptionsMenuState | null>(null);
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
    }
  }, [editingId]);

  useEffect(() => {
    if (!optionsMenu) {
      return;
    }

    const closeOptionsMenu = () => setOptionsMenu(null);

    window.addEventListener('resize', closeOptionsMenu);
    window.addEventListener('scroll', closeOptionsMenu, true);

    return () => {
      window.removeEventListener('resize', closeOptionsMenu);
      window.removeEventListener('scroll', closeOptionsMenu, true);
    };
  }, [optionsMenu]);

  const startRename = (id: string, title: string) => {
    setEditingId(id);
    setEditValue(title);
    setOptionsMenu(null);
  };

  const saveRename = () => {
    if (editingId && editValue.trim() !== '') {
      onRename(editingId, editValue.trim());
    }

    setEditingId(null);
  };

  const handleRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      saveRename();
    }

    if (e.key === 'Escape') {
      setEditingId(null);
    }
  };

  const toggleOptionsMenu = (id: string, rect: DOMRect) => {
    setOptionsMenu((prev) => {
      if (prev?.id === id) {
        return null;
      }

      return { id, rect };
    });
  };

  const closeOptionsMenu = () => {
    setOptionsMenu(null);
  };

  return {
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
  };
}

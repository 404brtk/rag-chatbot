import { useState, useEffect, useCallback } from 'react';
import { api, auth } from '../services/api';
import { Icon } from './Icon';
import { type DocumentData, type CursorPaginated } from '../types';
import { Modal } from './Modal';
import './DocSelectionDialog.css';

interface DocSelectionDialogProps {
  onClose: () => void;
  selectedDocIds: string[];
  onChange: (ids: string[]) => void;
}

export function DocSelectionDialog({ onClose, selectedDocIds, onChange }: DocSelectionDialogProps) {
  const [availableDocs, setAvailableDocs] = useState<DocumentData[]>([]);
  const [docSearchQuery, setDocSearchQuery] = useState('');
  const [loadingDocs, setLoadingDocs] = useState(false);

  const fetchDocs = useCallback(async () => {
    if (!auth.isAuthenticated()) return;
    setLoadingDocs(true);
    try {
      let allDocs: DocumentData[] = [];
      let url = '/documents/';
      while (url) {
        const data = await api.get<CursorPaginated<DocumentData>>(url);
        allDocs = [...allDocs, ...data.results];
        if (data.next) {
          const urlObj = new URL(data.next);
          url = `/documents/${urlObj.search}`;
        } else {
          break;
        }
      }
      setAvailableDocs(allDocs);
    } catch (err) {
      console.error('Failed to fetch documents:', err);
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    void fetchDocs();
  }, [fetchDocs]);

  const toggleDocSelection = (id: string) => {
    const nextIds = selectedDocIds.includes(id)
      ? selectedDocIds.filter((dId) => dId !== id)
      : [...selectedDocIds, id];
    onChange(nextIds);
  };

  const handleSelectAll = () => {
    if (selectedDocIds.length === availableDocs.length) {
      onChange([]);
    } else {
      onChange(availableDocs.map((d) => d.id));
    }
  };

  const filteredDocs = availableDocs.filter((doc) =>
    doc.filename.toLowerCase().includes(docSearchQuery.toLowerCase())
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      id="doc-selection-popover"
      className="doc-selection-dialog"
    >
      <div className="doc-selection-dialog-wrapper">
        <div className="doc-selection-header modal-header">
          <h3>Select Documents for RAG</h3>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        <div className="doc-selection-search-wrap">
          <Icon name="search" size={14} className="doc-selection-search-icon" />
          <input
            type="text"
            placeholder="Search documents by name..."
            value={docSearchQuery}
            onChange={(e) => setDocSearchQuery(e.target.value)}
            className="doc-selection-search-input"
          />
          {docSearchQuery && (
            <button
              type="button"
              onClick={() => setDocSearchQuery('')}
              className="doc-selection-search-clear"
            >
              <Icon name="x" size={12} />
            </button>
          )}
        </div>

        <div className="doc-selection-body">
          {loadingDocs ? (
            <div className="doc-selection-loading">Loading documents...</div>
          ) : filteredDocs.length === 0 ? (
            <div className="doc-selection-empty">No documents found</div>
          ) : (
            <div className="doc-selection-list">
              {filteredDocs.map((doc) => {
                const isChecked = selectedDocIds.includes(doc.id);
                const isReady = !doc.status || doc.status === 'completed';
                return (
                  <button
                    key={doc.id}
                    type="button"
                    className={`doc-selection-item ${isChecked ? 'selected' : ''} ${!isReady ? 'disabled' : ''}`}
                    onClick={() => isReady && toggleDocSelection(doc.id)}
                    disabled={!isReady}
                  >
                    <span className={`doc-selection-checkbox ${isChecked ? 'checked' : ''}`}>
                      {isChecked && <Icon name="check" size={10} />}
                    </span>
                    <Icon name="file" size={14} className="doc-selection-item-icon" />
                    <span className="doc-selection-item-name" title={doc.filename}>
                      {doc.filename}
                    </span>
                    {doc.status && doc.status !== 'completed' && (
                      <span
                        className={`job-status-badge ${doc.status}`}
                        style={{ fontSize: '10px', marginLeft: 'auto' }}
                      >
                        {doc.status.replace('_', ' ')}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="doc-selection-footer">
          <button type="button" className="doc-selection-footer-btn" onClick={handleSelectAll}>
            {selectedDocIds.length === availableDocs.length ? 'Clear All' : 'Select All'}
          </button>
          <span className="doc-selection-footer-count">
            {selectedDocIds.length} of {availableDocs.length} selected
          </span>
          <button type="button" className="doc-selection-confirm-btn btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Modal>
  );
}

import {
  useState,
  useRef,
  type ChangeEvent,
  type KeyboardEvent,
  type DragEvent,
  type ClipboardEvent,
} from 'react';
import { Icon } from './Icon';
import type { MessageAttachment } from '../types';
import { formatProviderName } from '../utils/format';
import {
  formatBytes,
  fileNameParts,
  isAllowedTextFile,
  isAllowedImageFile,
  MAX_ATTACHMENT_SIZE_BYTES,
  ACCEPTED_TEXT_EXTENSIONS,
  ACCEPTED_IMAGE_EXTENSIONS,
} from '../utils/file';
import { api } from '../services/api';
import { DocSelectionDialog } from './DocSelectionDialog';
import { CustomDropdown } from './CustomDropdown';
import { useAuthStore } from '../stores/useAuthStore';
import { useChatStore, selectActiveMode } from '../stores/useChatStore';
import './ChatInput.css';

interface ChatInputProps {
  placeholder?: string;
}

interface AttachmentComposerState {
  attachments: MessageAttachment[];
  error: string | null;
}

const MAX_HEIGHT = 200;

export function ChatInput({ placeholder = 'Message...' }: ChatInputProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const openAuthDialog = useAuthStore((s) => s.openAuthDialog);

  const provider = useChatStore((s) => s.provider);
  const model = useChatStore((s) => s.model);
  const models = useChatStore((s) => s.models);
  const setProvider = useChatStore((s) => s.setProvider);
  const setModel = useChatStore((s) => s.setModel);
  const ragEnabled = useChatStore((s) => s.ragEnabled);
  const setRagEnabled = useChatStore((s) => s.setRagEnabled);
  const compactionEnabled = useChatStore((s) => s.compactionEnabled);
  const setCompactionEnabled = useChatStore((s) => s.setCompactionEnabled);
  const mode = useChatStore(selectActiveMode);
  const selectedDocIds = useChatStore((s) => s.selectedDocIds);
  const setSelectedDocIds = useChatStore((s) => s.setSelectedDocIds);
  const isTyping = useChatStore((s) => s.isTyping);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const stopStreaming = useChatStore((s) => s.stopStreaming);

  const [message, setMessage] = useState('');
  const [attachmentState, setAttachmentState] = useState<AttachmentComposerState>({
    attachments: [],
    error: null,
  });
  const [isDragActive, setIsDragActive] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepthRef = useRef(0);
  const attachments = attachmentState.attachments;
  const attachmentError = attachmentState.error;

  const [isDocDialogOpen, setIsDocDialogOpen] = useState(false);

  const providers = Object.keys(models);
  const availableModels = models[provider] || [];

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider);
    const pModels = models[newProvider] || [];
    if (pModels.length > 0) {
      setModel(pModels[0]);
    }
  };

  const hasMessage = message.trim().length > 0;
  const isUploading = attachments.some((att) => att.uploading);
  const canSend = (hasMessage || attachments.length > 0) && !isTyping && !isUploading;
  const filePickerAccept = [...ACCEPTED_TEXT_EXTENSIONS, ...ACCEPTED_IMAGE_EXTENSIONS].join(',');

  const updateOverflow = (el: HTMLTextAreaElement) => {
    el.classList.toggle('has-overflow', el.scrollHeight > MAX_HEIGHT);
  };

  const resetTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    updateOverflow(el);
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
    updateOverflow(el);
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    adjustHeight();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (isTyping) {
      return;
    }

    const files = Array.from(e.clipboardData.items)
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);

    if (files.length === 0) {
      return;
    }

    e.preventDefault();
    void addFiles(files);
  };

  const handleSend = () => {
    if (!isAuthenticated) {
      openAuthDialog('login');
      return;
    }
    if (!canSend) return;

    void sendMessage(message.trim(), attachments, selectedDocIds);
    setMessage('');
    setAttachmentState({ attachments: [], error: null });
    resetTextarea();
  };

  const openAttachmentPicker = () => {
    if (!isAuthenticated) {
      openAuthDialog('login');
      return;
    }
    fileInputRef.current?.click();
  };

  const addFiles = async (files: File[]) => {
    if (isTyping) return;

    const validFiles: File[] = [];
    let validationError: string | null = null;

    for (const file of files) {
      if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
        validationError = `File "${file.name}" is too large. Max size is 5 MB.`;
        continue;
      }

      const isText = isAllowedTextFile(file);
      const isImg = isAllowedImageFile(file);

      if (!isText && !isImg) {
        validationError = `File "${file.name}" is not supported. Only text, code, and image files are supported.`;
        continue;
      }

      validFiles.push(file);
    }

    if (validFiles.length === 0) {
      if (validationError) {
        setAttachmentState((prev) => ({ ...prev, error: validationError }));
      }
      return;
    }

    for (const file of validFiles) {
      const tempId = crypto.randomUUID();
      const isImg = isAllowedImageFile(file);

      const tempAttachment: MessageAttachment = {
        id: tempId,
        name: file.name,
        size: file.size,
        mimeType: file.type || (isImg ? 'image/png' : 'text/plain'),
        kind: isImg ? 'image' : 'document',
        uploading: true,
      };

      setAttachmentState((prev) => ({
        ...prev,
        attachments: [...prev.attachments, tempAttachment],
        error: null,
      }));

      try {
        const formData = new FormData();
        formData.append('file', file);

        const res = await api.post<{
          id: string;
          name: string;
          size: number;
          mimeType: string;
          url: string;
        }>('/attachments/', formData);

        let textContent: string | undefined = undefined;
        if (!isImg && !file.name.toLowerCase().endsWith('.pdf')) {
          textContent = await file.text();
        }

        setAttachmentState((prev) => ({
          ...prev,
          attachments: prev.attachments.map((att) =>
            att.id === tempId
              ? {
                  ...att,
                  uploading: false,
                  content: textContent || res.url,
                  url: res.url,
                  backendId: res.id,
                }
              : att
          ),
        }));
      } catch (err) {
        console.error(`Failed to process file "${file.name}":`, err);
        setAttachmentState((prev) => ({
          ...prev,
          attachments: prev.attachments.filter((att) => att.id !== tempId),
          error: `Failed to upload or read file "${file.name}".`,
        }));
      }
    }

    if (validationError) {
      setAttachmentState((prev) => ({ ...prev, error: validationError }));
    }
  };

  const handleAttachmentChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files ? Array.from(e.target.files) : [];
    e.target.value = '';

    if (selectedFiles.length === 0) {
      return;
    }

    void addFiles(selectedFiles);
  };

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (isTyping) return;
    if (!isAuthenticated) {
      openAuthDialog('login');
      return;
    }
    dragDepthRef.current += 1;
    setIsDragActive(true);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (isTyping) return;
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (isTyping) return;
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (isTyping) return;
    dragDepthRef.current = 0;
    setIsDragActive(false);
    if (!isAuthenticated) {
      openAuthDialog('login');
      return;
    }
    const droppedFiles = Array.from(e.dataTransfer.files ?? []);
    if (droppedFiles.length === 0) {
      return;
    }
    void addFiles(droppedFiles);
  };

  const removeAttachment = (id: string) => {
    setAttachmentState((prev) => ({
      attachments: prev.attachments.filter((attachment) => attachment.id !== id),
      error: null,
    }));
  };

  return (
    <div className="chat-input-wrapper">
      <div
        className={`chat-input-container${isDragActive ? ' drag-active' : ''}`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {attachments.length > 0 ? (
          <div className="chat-attachment-list" role="list" aria-label="Selected attachments">
            {attachments.map((attachment) => {
              const { baseName, extension } = fileNameParts(attachment.name);

              return (
                <div
                  className={`chat-attachment-chip${attachment.uploading ? ' uploading' : ''}`}
                  role="listitem"
                  key={attachment.id}
                  style={attachment.uploading ? { opacity: 0.6 } : undefined}
                >
                  <span className="chat-attachment-icon" aria-hidden>
                    <Icon name={attachment.kind === 'image' ? 'image' : 'file'} size={12} />
                  </span>
                  <span className="chat-attachment-name-wrap" title={attachment.name}>
                    <span className="chat-attachment-name">
                      {attachment.uploading ? 'Uploading... ' : ''}
                      {baseName}
                    </span>
                    {extension !== '' ? (
                      <span className="chat-attachment-extension">{extension}</span>
                    ) : null}
                  </span>
                  <span className="chat-attachment-size">{formatBytes(attachment.size)}</span>
                  <button
                    type="button"
                    className="chat-attachment-remove"
                    aria-label={`Remove ${attachment.name}`}
                    onClick={() => removeAttachment(attachment.id)}
                    disabled={attachment.uploading}
                  >
                    <Icon name="x" size={12} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}

        {attachmentError ? (
          <p className="chat-attachment-error" role="status" aria-live="polite">
            {attachmentError}
          </p>
        ) : null}

        <textarea
          id="chat-message-input"
          ref={textareaRef}
          className="chat-input-textarea"
          placeholder={placeholder}
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          rows={1}
          disabled={isTyping}
        />

        <input
          ref={fileInputRef}
          className="chat-attachment-input"
          style={{ display: 'none' }}
          type="file"
          accept={filePickerAccept}
          multiple
          onChange={handleAttachmentChange}
        />

        <div className="chat-input-toolbar">
          <div className="chat-input-toolbar-left">
            <button
              id="chat-attach-btn"
              className="chat-input-icon-btn attach-btn"
              type="button"
              aria-label="Attach file"
              onClick={openAttachmentPicker}
              disabled={isTyping}
            >
              <Icon name="plus" size={20} />
            </button>

            {isAuthenticated ? (
              <div className="chat-input-selectors">
                <CustomDropdown
                  value={provider}
                  options={providers.length > 0 ? providers : [provider]}
                  onChange={handleProviderChange}
                  labelFormatter={formatProviderName}
                  disabled={providers.length === 0 || isTyping}
                />

                <CustomDropdown
                  value={model}
                  options={
                    availableModels.length > 0 ? availableModels : model ? [model] : ['Loading...']
                  }
                  onChange={(val) => setModel(val)}
                  disabled={providers.length === 0 || isTyping}
                />

                {mode === 'side-by-side' ? (
                  <div
                    className="chat-input-rag-toggle pill-control disabled active"
                    title="Evaluating RAG comparison side-by-side"
                    style={{ cursor: 'not-allowed', opacity: 0.8 }}
                  >
                    <span className="rag-status-dot" />
                    <span className="rag-label-content">RAG</span>
                  </div>
                ) : (
                  <label
                    className={`chat-input-rag-toggle pill-control ${ragEnabled ? 'active' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={ragEnabled}
                      onChange={(e) => setRagEnabled(e.target.checked)}
                      disabled={isTyping}
                    />
                    <span className="rag-status-dot" />
                    <span className="rag-label-content">RAG</span>
                  </label>
                )}

                {ragEnabled || mode === 'side-by-side' ? (
                  <>
                    <button
                      id="chat-doc-select-btn"
                      className={`chat-input-doc-select-btn pill-control ${selectedDocIds.length > 0 ? 'active' : ''}`}
                      type="button"
                      onClick={() => setIsDocDialogOpen(true)}
                      disabled={isTyping}
                    >
                      {selectedDocIds.length === 0
                        ? 'All Documents'
                        : `${selectedDocIds.length} Selected`}
                    </button>
                    {isDocDialogOpen ? (
                      <DocSelectionDialog
                        onClose={() => setIsDocDialogOpen(false)}
                        selectedDocIds={selectedDocIds}
                        onChange={setSelectedDocIds}
                      />
                    ) : null}
                  </>
                ) : null}

                {mode !== 'side-by-side' ? (
                  <label
                    className={`chat-input-compaction-toggle pill-control ${compactionEnabled ? 'active' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={compactionEnabled}
                      onChange={(e) => setCompactionEnabled(e.target.checked)}
                      disabled={isTyping}
                    />
                    <span className="compaction-status-dot" />
                    <span className="compaction-label-content">Compaction</span>
                  </label>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="chat-input-toolbar-right">
            <button
              id="chat-send-btn"
              className={`chat-input-icon-btn send-btn${canSend || isTyping ? ' active' : ''}`}
              type="button"
              aria-label={isTyping ? 'Stop generation' : 'Send message'}
              onClick={isTyping ? stopStreaming : handleSend}
              disabled={!(canSend || isTyping)}
            >
              <Icon name={isTyping ? 'stop' : 'arrow-up'} size={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

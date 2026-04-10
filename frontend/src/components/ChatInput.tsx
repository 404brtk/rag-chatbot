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
import './ChatInput.css';

interface ChatInputProps {
  placeholder?: string;
  onSend?: (message: string, attachments?: MessageAttachment[]) => void;
  disabled?: boolean;
}

interface AttachmentComposerState {
  attachments: MessageAttachment[];
  error: string | null;
}

const MAX_HEIGHT = 200;
const MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_DOCUMENT_TYPES = [
  'application/pdf',
  'text/plain',
  'text/markdown',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];
const ACCEPTED_DOCUMENT_EXTENSIONS = ['.pdf', '.txt', '.md', '.docx'];
const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const ACCEPTED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp'];

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`;
  const kb = size / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function extensionOf(fileName: string) {
  const parts = fileName.toLowerCase().split('.');
  if (parts.length < 2) return '';
  return `.${parts[parts.length - 1]}`;
}

function fileNameParts(fileName: string) {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex <= 0 || dotIndex === fileName.length - 1) {
    return { baseName: fileName, extension: '' };
  }

  return {
    baseName: fileName.slice(0, dotIndex),
    extension: fileName.slice(dotIndex),
  };
}

function isAllowedDocument(file: File) {
  const extension = extensionOf(file.name);
  if (extension !== '') {
    return ACCEPTED_DOCUMENT_EXTENSIONS.includes(extension);
  }

  return ACCEPTED_DOCUMENT_TYPES.includes(file.type);
}

function isAllowedImage(file: File) {
  const extension = extensionOf(file.name);
  if (extension !== '') {
    return ACCEPTED_IMAGE_EXTENSIONS.includes(extension);
  }

  return ACCEPTED_IMAGE_TYPES.includes(file.type);
}

function addFilesToState(currentAttachments: MessageAttachment[], files: File[]) {
  const nextAttachments = [...currentAttachments];
  let nextError: string | null = null;

  for (const file of files) {
    const extension = extensionOf(file.name);
    const isImage = file.type.startsWith('image/') || ACCEPTED_IMAGE_EXTENSIONS.includes(extension);

    if (isImage && !isAllowedImage(file)) {
      nextError = 'Only PNG, JPG, JPEG, WEBP images are supported.';
      continue;
    }

    if (!isImage && !isAllowedDocument(file)) {
      nextError = 'Only PDF, TXT, MD, DOCX, PNG, JPG, JPEG, WEBP files are supported.';
      continue;
    }

    if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
      nextError = 'Each file must be 10 MB or smaller.';
      continue;
    }

    if (
      nextAttachments.some(
        (attachment) => attachment.name === file.name && attachment.size === file.size
      )
    ) {
      continue;
    }

    nextAttachments.push({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      mimeType: file.type,
      kind: isImage ? 'image' : 'document',
    });
  }

  return {
    attachments: nextAttachments,
    error: nextError,
  };
}

export function ChatInput({
  placeholder = 'Message...',
  onSend,
  disabled = false,
}: ChatInputProps) {
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

  const hasMessage = message.trim().length > 0;
  const canSend = hasMessage && !disabled;
  const filePickerAccept = [
    ...ACCEPTED_DOCUMENT_EXTENSIONS,
    ...ACCEPTED_DOCUMENT_TYPES,
    ...ACCEPTED_IMAGE_EXTENSIONS,
    ...ACCEPTED_IMAGE_TYPES,
  ].join(',');

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
    if (disabled) {
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
    addFiles(files);
  };

  const handleSend = () => {
    if (!canSend) return;
    onSend?.(message.trim(), attachments);
    setMessage('');
    setAttachmentState({ attachments: [], error: null });
    resetTextarea();
  };

  const openAttachmentPicker = () => {
    fileInputRef.current?.click();
  };

  const addFiles = (files: File[]) => {
    setAttachmentState((prev) => addFilesToState(prev.attachments, files));
  };

  const handleAttachmentChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files ? Array.from(e.target.files) : [];
    e.target.value = '';

    if (selectedFiles.length === 0) {
      return;
    }

    addFiles(selectedFiles);
  };

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (disabled) return;
    dragDepthRef.current += 1;
    setIsDragActive(true);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (disabled) return;
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (disabled) return;
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (disabled) return;
    dragDepthRef.current = 0;
    setIsDragActive(false);
    const droppedFiles = Array.from(e.dataTransfer.files ?? []);
    if (droppedFiles.length === 0) {
      return;
    }
    addFiles(droppedFiles);
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
        {attachments.length > 0 && (
          <div className="chat-attachment-list" role="list" aria-label="Selected attachments">
            {attachments.map((attachment) => {
              const { baseName, extension } = fileNameParts(attachment.name);

              return (
                <div className="chat-attachment-chip" role="listitem" key={attachment.id}>
                  <span className="chat-attachment-icon" aria-hidden>
                    <Icon name={attachment.kind === 'image' ? 'image' : 'file'} size={12} />
                  </span>
                  <span className="chat-attachment-name-wrap" title={attachment.name}>
                    <span className="chat-attachment-name">{baseName}</span>
                    {extension !== '' && (
                      <span className="chat-attachment-extension">{extension}</span>
                    )}
                  </span>
                  <span className="chat-attachment-size">{formatBytes(attachment.size)}</span>
                  <button
                    type="button"
                    className="chat-attachment-remove"
                    aria-label={`Remove ${attachment.name}`}
                    onClick={() => removeAttachment(attachment.id)}
                  >
                    <Icon name="x" size={12} />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {attachmentError && (
          <p className="chat-attachment-error" role="status" aria-live="polite">
            {attachmentError}
          </p>
        )}

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
        />

        <input
          ref={fileInputRef}
          className="chat-attachment-input"
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
              disabled={disabled}
            >
              <Icon name="plus" size={20} />
            </button>
          </div>

          <div className="chat-input-toolbar-right">
            <button
              id="chat-mic-btn"
              className="chat-input-icon-btn"
              type="button"
              aria-label="Voice input"
            >
              <Icon name="mic" size={20} />
            </button>

            <button
              id="chat-send-btn"
              className={`chat-input-icon-btn send-btn${canSend ? ' active' : ''}`}
              type="button"
              aria-label="Send message"
              onClick={handleSend}
              disabled={!canSend}
            >
              <Icon name="arrow-up" size={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

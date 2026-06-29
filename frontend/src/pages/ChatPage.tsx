import { ChatInput } from '../components/ChatInput';
import { MessageList } from '../components/MessageList';
import { useAppRouteContext } from '../hooks/useAppRouteContext';
import './ChatPage.css';

export function ChatPage() {
  const {
    messages,
    isTyping,
    handleSend,
    handleStop,
    provider,
    model,
    setProvider,
    setModel,
    models,
    ragEnabled,
    setRagEnabled,
    compactionEnabled,
    setCompactionEnabled,
    isAuthenticated,
    openAuthDialog,
    activeChatId,
    mode,
    selectedDocIds,
    setSelectedDocIds,
  } = useAppRouteContext();

  const isEmpty = messages.length === 0;

  const handleSendWrapper = (
    text: string,
    attachments?: Parameters<typeof handleSend>[1],
    selectedDocIds?: string[]
  ) => {
    if (!isAuthenticated) {
      openAuthDialog('login');
      return;
    }
    handleSend(text, attachments, selectedDocIds);
  };

  const handleAuthRequired = () => {
    openAuthDialog('login');
  };

  const chatInputProps = {
    placeholder: 'Ask anything...' as const,
    onSend: handleSendWrapper,
    onStop: handleStop,
    onAuthRequired: handleAuthRequired,
    disabled: isTyping,
    isTyping,
    provider,
    model,
    setProvider,
    setModel,
    models,
    ragEnabled,
    setRagEnabled,
    compactionEnabled,
    setCompactionEnabled,
    activeChatId,
    mode,
    selectedDocIds,
    setSelectedDocIds,
    isAuthenticated,
  };

  if (isEmpty) {
    return (
      <div className="chat-page-empty-state-wrapper">
        <div className="hero-section">
          <h1 className="hero-greeting">What do you want to know?</h1>
        </div>
        <div className="chat-page-empty-input-region input-region">
          <ChatInput {...chatInputProps} />
        </div>
      </div>
    );
  }

  return (
    <>
      <MessageList messages={messages} />
      <div className="input-region">
        <ChatInput {...chatInputProps} />
      </div>
    </>
  );
}

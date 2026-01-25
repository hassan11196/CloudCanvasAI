import { useState, useRef, useEffect } from 'react';
import { apiService } from '../services/api';
import './Chat.css';

const STORAGE_KEY = 'zephior_chats';

const createNewChat = () => ({
  id: Date.now().toString(),
  sessionId: null,
  messages: [],
  title: 'New Chat',
});

const loadChatsFromStorage = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (e) {
    console.error('Failed to load chats from storage:', e);
  }
  return [createNewChat()];
};

const saveChatsToStorage = (chats) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
  } catch (e) {
    console.error('Failed to save chats to storage:', e);
  }
};

function Chat() {
  const [chats, setChats] = useState(() => loadChatsFromStorage());
  const [activeChatId, setActiveChatId] = useState(() => {
    const loaded = loadChatsFromStorage();
    return loaded[0]?.id || createNewChat().id;
  });
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [toolActivity, setToolActivity] = useState([]);
  const [thinkingSteps, setThinkingSteps] = useState([]);
  const [streamingContent, setStreamingContent] = useState('');
  const messagesEndRef = useRef(null);
  const toolsRef = useRef([]);
  const thinkingRef = useRef([]);

  const activeChat = chats.find((c) => c.id === activeChatId) || chats[0];

  // Save to localStorage whenever chats change
  useEffect(() => {
    saveChatsToStorage(chats);
  }, [chats]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeChat?.messages, toolActivity, streamingContent, thinkingSteps]);

  useEffect(() => { toolsRef.current = toolActivity; }, [toolActivity]);
  useEffect(() => { thinkingRef.current = thinkingSteps; }, [thinkingSteps]);

  const updateActiveChat = (updates) => {
    setChats((prev) => prev.map((c) => (c.id === activeChatId ? { ...c, ...updates } : c)));
  };

  const handleNewChat = () => {
    const newChat = createNewChat();
    setChats((prev) => [newChat, ...prev]);
    setActiveChatId(newChat.id);
    setToolActivity([]);
    setThinkingSteps([]);
    setStreamingContent('');
  };

  const handleSwitchChat = (chatId) => {
    if (isLoading) return;
    setActiveChatId(chatId);
    setToolActivity([]);
    setThinkingSteps([]);
    setStreamingContent('');
  };

  const handleDeleteChat = (chatId) => {
    if (chats.length === 1) {
      handleNewChat();
      setChats((prev) => prev.filter((c) => c.id !== chatId));
    } else {
      const remaining = chats.filter((c) => c.id !== chatId);
      setChats(remaining);
      if (activeChatId === chatId) {
        setActiveChatId(remaining[0].id);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = { role: 'user', content: input };
    updateActiveChat({ messages: [...activeChat.messages, userMessage] });
    
    // Update title from first message
    if (activeChat.messages.length === 0) {
      updateActiveChat({ title: input.slice(0, 30) + (input.length > 30 ? '...' : '') });
    }

    const currentInput = input;
    setInput('');
    setIsLoading(true);
    setToolActivity([]);
    setThinkingSteps([]);
    toolsRef.current = [];
    thinkingRef.current = [];
    setStreamingContent('');

    await apiService.streamChatMessage(
      currentInput,
      activeChat.sessionId,
      (event) => {
        if (event.type === 'session') {
          updateActiveChat({ sessionId: event.session_id });
        } else if (event.type === 'thinking') {
          setThinkingSteps((prev) => [...prev, event.content]);
        } else if (event.type === 'tool_use') {
          setToolActivity((prev) => [...prev, { name: event.tool_name, input: event.tool_input }]);
        } else if (event.type === 'tool_result') {
          setToolActivity((prev) => {
            const updated = [...prev];
            if (updated.length > 0) updated[updated.length - 1].result = event.result;
            return updated;
          });
        } else if (event.type === 'text_delta') {
          setStreamingContent((prev) => prev + event.content);
          setThinkingSteps((prev) => [...prev, event.content]);
        } else if (event.type === 'error') {
          setChats((prev) => prev.map((c) => 
            c.id === activeChatId 
              ? { ...c, messages: [...c.messages, { role: 'error', content: event.content, tools: [...toolsRef.current], thinking: [...thinkingRef.current] }] }
              : c
          ));
          setIsLoading(false);
        }
      },
      (content) => {
        setChats((prev) => prev.map((c) => 
          c.id === activeChatId 
            ? { ...c, messages: [...c.messages, { role: 'assistant', content, tools: [...toolsRef.current], thinking: [...thinkingRef.current] }] }
            : c
        ));
        setIsLoading(false);
        setToolActivity([]);
        setThinkingSteps([]);
        setStreamingContent('');
      },
      (error) => {
        setChats((prev) => prev.map((c) => 
          c.id === activeChatId 
            ? { ...c, messages: [...c.messages, { role: 'error', content: error.message, tools: [...toolsRef.current], thinking: [...thinkingRef.current] }] }
            : c
        ));
        setIsLoading(false);
        setToolActivity([]);
        setThinkingSteps([]);
        setStreamingContent('');
      }
    );
  };

  const getToolIcon = (name) => ({ Read: '📄', Edit: '✏️', Write: '💾', Glob: '🔍', Grep: '🔎', Bash: '⚡' }[name] || '🔧');

  const ThinkingAccordion = ({ steps }) => {
    const [isOpen, setIsOpen] = useState(false);
    if (!steps?.length) return null;
    return (
      <div className="thinking-accordion">
        <button className="thinking-toggle" onClick={() => setIsOpen(!isOpen)}>
          🧠 Thinking ({steps.length} steps) {isOpen ? '▼' : '▶'}
        </button>
        {isOpen && (
          <div className="thinking-content">
            {steps.map((step, i) => <div key={i} className="thinking-step">{step}</div>)}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="chat-layout">
      {/* Sidebar */}
      <div className="chat-sidebar">
        <button className="new-chat-btn" onClick={handleNewChat}>+ New Chat</button>
        <div className="chat-list">
          {chats.map((chat) => (
            <div
              key={chat.id}
              className={`chat-item ${chat.id === activeChatId ? 'active' : ''}`}
              onClick={() => handleSwitchChat(chat.id)}
            >
              <span className="chat-title">{chat.title}</span>
              <button
                className="delete-chat-btn"
                onClick={(e) => { e.stopPropagation(); handleDeleteChat(chat.id); }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="chat-container">
        <header className="chat-header">
          <h1>Zephior</h1>
          {activeChat.sessionId && <span className="session-badge">{activeChat.sessionId.slice(0, 8)}</span>}
        </header>

        <div className="messages-container">
          {activeChat.messages.length === 0 && (
            <div className="empty-state">
              <p>👋 I can read files, run commands, and help with coding tasks.</p>
            </div>
          )}
          
          {activeChat.messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              <span className="message-role">{msg.role === 'user' ? 'You' : 'Zephior'}</span>
              <ThinkingAccordion steps={msg.thinking} />
              {msg.tools?.length > 0 && (
                <div className="tool-activity">
                  {msg.tools.map((t, j) => (
                    <div key={j} className="tool-card">
                      <div className="tool-header">{getToolIcon(t.name)} {t.name}</div>
                      <code className="tool-input">{JSON.stringify(t.input, null, 2)}</code>
                      {t.result && <pre className="tool-result">{t.result}</pre>}
                    </div>
                  ))}
                </div>
              )}
              <pre className="message-content">{msg.content}</pre>
            </div>
          ))}

          {isLoading && (
            <div className="message assistant loading">
              <span className="message-role">Zephior</span>
              {thinkingSteps.length > 0 && (
                <div className="thinking-live">
                  🧠 <span className="thinking-text">{thinkingSteps[thinkingSteps.length - 1]?.slice(0, 100)}...</span>
                </div>
              )}
              {toolActivity.map((t, i) => (
                <div key={i} className="tool-card">
                  <div className="tool-header">{getToolIcon(t.name)} {t.name}</div>
                  <code className="tool-input">{JSON.stringify(t.input, null, 2)}</code>
                  {t.result && <pre className="tool-result">{t.result}</pre>}
                </div>
              ))}
              {streamingContent && <pre className="message-content streaming">{streamingContent}</pre>}
              {!streamingContent && toolActivity.length === 0 && thinkingSteps.length === 0 && <p className="status-text">Processing...</p>}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSubmit} className="input-form">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask me anything..."
            disabled={isLoading}
          />
          <button type="submit" disabled={isLoading || !input.trim()}>Send</button>
        </form>
      </div>
    </div>
  );
}

export default Chat;
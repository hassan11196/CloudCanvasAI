import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { apiService, API_BASE_URL, getAuthHeader } from '../services/api';
import DocumentPreview from '../components/DocumentPreview';
import FileList from '../components/FileList';
import {
  auth,
  googleProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  onAuthStateChanged,
} from '../services/firebase';
import './Chat.css';

const STORAGE_KEY = 'zephior_chats';
const ARTIFACT_EXTENSIONS = ['docx', 'pdf', 'pptx', 'xlsx', 'txt', 'md'];

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

const isArtifactPath = (path) => {
  if (!path) return false;
  const ext = path.split('.').pop()?.toLowerCase();
  return ARTIFACT_EXTENSIONS.includes(ext);
};

const cleanAssistantContent = (content = '') => {
  // Strip status noise like "doc_generation_requested: file.docx"
  return content
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim().toLowerCase();
      return trimmed && !trimmed.startsWith('doc_generation_requested');
    })
    .join('\n')
    .trim();
};

// Normalize and label tool actions for display
const getToolDescription = (tool) => {
  const { name: rawName = '', input } = tool;
  const name = rawName.replace(/^mcp__(sandbox|remote)?__/, '') || rawName;
  const lowerName = name.toLowerCase();
  const isSandbox = rawName.includes('__sandbox__');
  const filePath = input?.file_path || input?.path || input?.pattern || input?.TargetFile || '';
  const fileName = filePath.split('/').pop() || '';

  if (lowerName === 'write' || lowerName === 'write_to_file') {
    const scope = isSandbox ? ' in sandbox' : '';
    return { action: `Writing${scope}`, fileName, icon: '📝' };
  }

  if (lowerName === 'edit' || lowerName === 'replace_file_content' || lowerName === 'multi_replace_file_content') {
    const scope = isSandbox ? ' in sandbox' : '';
    return { action: `Editing${scope}`, fileName, icon: '✏️' };
  }

  if (lowerName === 'read') {
    const scope = isSandbox ? ' in sandbox' : '';
    return { action: `Reading${scope}`, fileName, icon: '📄' };
  }

  if (lowerName === 'bash' || lowerName === 'run_command') {
    const cmd = (input?.command || input?.CommandLine || 'command').split(' ')[0];
    const scope = isSandbox ? ' on sandbox' : '';
    return { action: `Running bash command${scope}`, fileName: cmd, icon: '⚡' };
  }

  if (lowerName === 'glob') {
    return { action: 'Searching', fileName: input?.pattern || 'files', icon: '🔍' };
  }

  if (lowerName === 'grep') {
    return { action: 'Searching for', fileName: input?.pattern || 'pattern', icon: '🔎' };
  }

  return { action: 'Using', fileName: name, icon: '🔧' };
};

// Collapsible tool step component
function ToolStep({ tool, isStreaming = false }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { action, fileName, icon } = getToolDescription(tool);
  // Only show spinner if streaming AND no result yet
  const showSpinner = isStreaming && tool.result === undefined;
  const isComplete = tool.result !== undefined;
  const isBash = tool.name === 'Bash' || tool.name === 'run_command';
  const outputPreview = isBash && tool.result
    ? tool.result.split('\n').slice(0, 10).join('\n')
    : '';

  return (
    <div className={`tool-step ${isComplete ? 'completed' : ''}`}>
      <div className="tool-step-header" onClick={() => setIsExpanded(!isExpanded)}>
        <div className="tool-step-left">
          <span className="tool-step-icon">{icon}</span>
          <span className="tool-step-action">{action}</span>
          {fileName && <span className="tool-step-file">{fileName}</span>}
        </div>
        <div className="tool-step-right">
          {showSpinner && <span className="tool-step-spinner" />}
          {isComplete && <span className="tool-step-check">✓</span>}
          <span className={`tool-step-chevron ${isExpanded ? 'expanded' : ''}`}>›</span>
        </div>
      </div>
      {isBash && tool.result && !isExpanded && (
        <div className="tool-step-preview">
          <pre>{outputPreview}</pre>
        </div>
      )}
      {isExpanded && (
        <div className="tool-step-details">
          {tool.input && (
            <div className="tool-step-input">
              <pre>{JSON.stringify(tool.input, null, 2)}</pre>
            </div>
          )}
          {tool.result && (
            <div className="tool-step-result">
              <pre>{tool.result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Grouped steps component
function ToolSteps({ tools, isStreaming = false }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const completedCount = tools.filter(t => t.result !== undefined).length;

  if (tools.length === 0) return null;

  if (tools.length === 1) {
    return <ToolStep tool={tools[0]} isStreaming={isStreaming} />;
  }

  return (
    <div className="tool-steps-group">
      <div className="tool-steps-header" onClick={() => setIsExpanded(!isExpanded)}>
        <span className={`tool-steps-chevron ${isExpanded ? 'expanded' : ''}`}>›</span>
        <span className="tool-steps-count">{completedCount} of {tools.length} steps</span>
      </div>
      {isExpanded && (
        <div className="tool-steps-list">
          {tools.map((tool, i) => (
            <ToolStep key={i} tool={tool} isStreaming={isStreaming} />
          ))}
        </div>
      )}
    </div>
  );
}

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
  const [docStatus, setDocStatus] = useState(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [usageSummary, setUsageSummary] = useState(null);
  const [currentUser, setCurrentUser] = useState(() => auth.currentUser);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Document preview state
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [artifactRevision, setArtifactRevision] = useState(0);
  const [creatingFile, setCreatingFile] = useState(null);

  // Sidebar state
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const messagesEndRef = useRef(null);
  const toolsRef = useRef([]);
  const thinkingRef = useRef([]);

  const activeChat = chats.find((c) => c.id === activeChatId) || chats[0];

  useEffect(() => {
    saveChatsToStorage(chats);
  }, [chats]);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setCurrentUser(user);
      setAuthError('');
      setIsAuthChecking(false);
    });
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeChat?.messages, toolActivity, streamingContent, thinkingSteps]);

  useEffect(() => { toolsRef.current = toolActivity; }, [toolActivity]);
  useEffect(() => { thinkingRef.current = thinkingSteps; }, [thinkingSteps]);

  const bumpPreviewRevision = () => {
    setPreviewRevision((prev) => prev + 1);
  };
  const bumpArtifactRevision = () => {
    setArtifactRevision((prev) => prev + 1);
  };

  // Auto-open preview when a file is selected
  useEffect(() => {
    if (selectedFile && !previewOpen) {
      setPreviewOpen(true);
    }
  }, [selectedFile, previewOpen]);

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
    setSelectedFile(null);
    setPreviewOpen(false);
    setArtifactRevision(0);
  };

  const handleSwitchChat = (chatId) => {
    if (isLoading) return;
    setActiveChatId(chatId);
    setToolActivity([]);
    setThinkingSteps([]);
    setStreamingContent('');
    setSelectedFile(null);
    setArtifactRevision(0);
  };

  const handleDeleteChat = async (chatId) => {
    // Find chat to get session ID
    const chatToDelete = chats.find(c => c.id === chatId);
    if (chatToDelete?.sessionId) {
      try {
        await apiService.deleteSession(chatToDelete.sessionId);
      } catch (e) {
        console.error('Failed to delete session:', e);
        // Continue with local deletion anyway
      }
    }

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

  const handleFileChange = (event) => {
    // Always open preview and select file when agent creates/modifies files
    if (!isArtifactPath(event.path)) return;
    setSelectedFile(event.path);
    setPreviewOpen(true);
    bumpPreviewRevision();
    bumpArtifactRevision();
    if (creatingFile === event.path) {
      setCreatingFile(null);
    }
    setDocStatus({
      state: 'ready',
      file: event.path,
      message: `Ready: "${event.path}"`,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = { role: 'user', content: input };
    updateActiveChat({ messages: [...activeChat.messages, userMessage] });

    if (activeChat.messages.length === 0) {
      updateActiveChat({ title: input.slice(0, 30) + (input.length > 30 ? '...' : '') });
    }

    const currentInput = input;
    setInput('');
    setIsLoading(true);
    setToolActivity([]);
    setThinkingSteps([]);
    setStatusMessage('');
    setDocStatus(null);
    setUsageSummary(null);
    toolsRef.current = [];
    thinkingRef.current = [];
    setStreamingContent('');

    await apiService.streamChatMessage(
      currentInput,
      activeChat.sessionId,
      (event) => {
        if (event.type === 'session') {
          updateActiveChat({ sessionId: event.session_id });
        } else if (event.type === 'status') {
          if (event.content === 'doc_generation_requested') {
            const docPath = event.path || '';
            if (docPath && isArtifactPath(docPath)) {
              setSelectedFile(docPath);
              bumpPreviewRevision();
              setCreatingFile(docPath);
            }
            // Kick the artifacts list to re-fetch when a document is requested,
            // even if the backend hasn't emitted a file_change yet.
            bumpArtifactRevision();
            if (docPath && isArtifactPath(docPath)) {
              setDocStatus({
                state: 'creating',
                file: docPath,
                message: docPath ? `Creating "${docPath}"` : 'Generating artifact',
              });
              setStatusMessage(docPath ? `Creating ${docPath}...` : 'Artifact generation requested');
              setPreviewOpen(true);
            }
            // Even if path is missing, surface the preview so user sees artifacts list populate
            if (!previewOpen) {
              setPreviewOpen(true);
            }
          } else if (event.content === 'doc_generation_failed') {
            const docPath = event.path || selectedFile || '';
            if (docPath && isArtifactPath(docPath)) {
              setDocStatus({
                state: 'failed',
                file: docPath,
                message: docPath ? `Creation failed for "${docPath}"` : 'Artifact generation failed',
              });
              setStatusMessage(docPath ? `Creation failed for ${docPath}` : 'Artifact generation failed');
              setCreatingFile(null);
            }
          } else {
            setStatusMessage(event.content || '');
          }
        } else if (event.type === 'usage') {
          setUsageSummary({
            totalCost: event.total_cost_usd,
            usage: event.usage || {},
          });
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
          // Nudge preview to pull the latest version after a tool finishes
          if (selectedFile || creatingFile) {
            bumpPreviewRevision();
          }
          if (selectedFile || creatingFile) {
            bumpArtifactRevision();
          }
        } else if (event.type === 'text_delta') {
          // Filter out raw status lines that shouldn't show as user-facing text
          const trimmed = (event.content || '').trim().toLowerCase();
          if (trimmed.startsWith('doc_generation_requested') || trimmed.startsWith('doc_generation_failed')) {
            return;
          }
          setStreamingContent((prev) => prev + event.content);
        } else if (event.type === 'file_change') {
          handleFileChange(event);
        } else if (event.type === 'error') {
          setChats((prev) => prev.map((c) =>
            c.id === activeChatId
              ? { ...c, messages: [...c.messages, { role: 'error', content: event.content, tools: [...toolsRef.current] }] }
              : c
          ));
          setIsLoading(false);
          setStatusMessage('');
          setUsageSummary(null);
        }
      },
      (content) => {
        const cleanedContent = cleanAssistantContent(content);
        setChats((prev) => prev.map((c) =>
          c.id === activeChatId
            ? { ...c, messages: [...c.messages, { role: 'assistant', content: cleanedContent, tools: [...toolsRef.current] }] }
            : c
        ));
        setIsLoading(false);
        setToolActivity([]);
        setThinkingSteps([]);
        setStatusMessage('');
        setUsageSummary(null);
        setStreamingContent('');
        setCreatingFile(null);
        // Ensure preview reflects final state after chat completes
        if (selectedFile || creatingFile) {
          bumpPreviewRevision();
          bumpArtifactRevision();
        }
      },
      (error) => {
        setChats((prev) => prev.map((c) =>
          c.id === activeChatId
            ? { ...c, messages: [...c.messages, { role: 'error', content: error.message, tools: [...toolsRef.current] }] }
            : c
        ));
        setIsLoading(false);
        setToolActivity([]);
        setThinkingSteps([]);
        setStatusMessage('');
        setUsageSummary(null);
        setStreamingContent('');
        setCreatingFile(null);
        if (selectedFile || creatingFile) {
          bumpPreviewRevision();
          bumpArtifactRevision();
        }
      }
    );
  };

  const handleGoogleLogin = async () => {
    try {
      setAuthError('');
      await signInWithPopup(auth, googleProvider);
    } catch (error) {
      setAuthError(error.message);
    }
  };

  const handleEmailLogin = async (e) => {
    e.preventDefault();
    try {
      setAuthError('');
      await signInWithEmailAndPassword(auth, authEmail, authPassword);
    } catch (error) {
      setAuthError(error.message);
    }
  };

  const handleEmailSignup = async (e) => {
    e.preventDefault();
    try {
      setAuthError('');
      await createUserWithEmailAndPassword(auth, authEmail, authPassword);
    } catch (error) {
      setAuthError(error.message);
    }
  };

  const handleDownloadSelected = async () => {
    if (!activeChat.sessionId || !selectedFile) return;
    try {
      const authHeader = await getAuthHeader();
      const response = await fetch(
        `${API_BASE_URL}/files/${activeChat.sessionId}/content/${encodeURIComponent(selectedFile)}?t=${Date.now()}`,
        { headers: authHeader, cache: 'no-store' }
      );
      if (!response.ok) {
        throw new Error(`Failed to download file (HTTP ${response.status})`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = selectedFile.split('/').pop();
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      console.error('Download failed:', err);
    }
  };

  const userInitial = (currentUser?.displayName || currentUser?.email || 'U')?.[0]?.toUpperCase() || 'U';
  const userName = currentUser?.displayName || currentUser?.email || 'Signed in';

  if (isAuthChecking) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-title">Loading your workspace</div>
          <p className="auth-subtitle">Hold tight while we check your sign-in status.</p>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-title">Sign in to Zephior Canvas</div>
          <p className="auth-subtitle">Use Google or email to continue</p>
          <button className="auth-google" onClick={handleGoogleLogin}>
            Continue with Google
          </button>
          <div className="auth-divider">or</div>
          <form className="auth-form">
            <input
              type="email"
              placeholder="Email"
              value={authEmail}
              onChange={(e) => setAuthEmail(e.target.value)}
            />
            <input
              type="password"
              placeholder="Password"
              value={authPassword}
              onChange={(e) => setAuthPassword(e.target.value)}
            />
            <div className="auth-actions">
              <button type="submit" onClick={handleEmailLogin}>
                Sign In
              </button>
              <button type="button" onClick={handleEmailSignup}>
                Sign Up
              </button>
            </div>
          </form>
          {authError && <div className="auth-error">{authError}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className={`chat-layout ${previewOpen ? 'with-preview' : ''} ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      {/* Sidebar */}
      <div className={`chat-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={handleNewChat}>
            <span className="new-chat-icon">+</span>
            {sidebarOpen && <span>New Chat</span>}
          </button>
          <button className="sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)} title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}>
            {sidebarOpen ? '‹' : '›'}
          </button>
        </div>
        {sidebarOpen && (
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
        )}
        <div className="sidebar-footer">
          {currentUser && (
            <div className={`sidebar-user ${sidebarOpen ? '' : 'collapsed'}`}>
              {currentUser.photoURL ? (
                <img
                  src={currentUser.photoURL}
                  alt={userName}
                  className="sidebar-avatar-img"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="sidebar-avatar-fallback">{userInitial}</div>
              )}
              {sidebarOpen && (
                <div className="sidebar-user-text">
                  <div className="sidebar-user-name">{userName}</div>
                  {currentUser.email && <div className="sidebar-user-email">{currentUser.email}</div>}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main Chat */}
      <div className="chat-main">
        <div className="chat-container">
          <div className="messages-container">
            {activeChat.messages.length === 0 && !isLoading && (
              <div className="empty-state">
                <div className="empty-state-icon">✨</div>
                <h2>What would you like to create?</h2>
                <p>I can help you create documents, write code, and more.</p>
                <div className="suggestions">
                  <button onClick={() => setInput('Create a project proposal document')}>
                    📄 Project proposal
                  </button>
                  <button onClick={() => setInput('Create a resume template')}>
                    📋 Resume template
                  </button>
                  <button onClick={() => setInput('Write a business plan')}>
                    📊 Business plan
                  </button>
                </div>
              </div>
            )}

            {activeChat.messages.map((msg, i) => (
              <div key={i} className={`message ${msg.role}`}>
                {msg.role === 'user' ? (
                  <div className="message-content user-content">{msg.content}</div>
                ) : (
                  <>
                    {msg.tools?.length > 0 && (
                      <div className="message-tools">
                        {msg.tools.length <= 3 ? (
                          msg.tools.map((tool, j) => (
                            <ToolStep key={j} tool={tool} isStreaming={false} />
                          ))
                        ) : (
                          <ToolSteps tools={msg.tools} isStreaming={false} />
                        )}
                      </div>
                    )}
                    <div className="message-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </>
                )}
              </div>
            ))}

            {isLoading && (
              <div className="message assistant streaming-message">
                {(statusMessage || usageSummary) && (
                  <div className="status-indicator">
                    <span className="status-dot" />
                    <span>{statusMessage || 'Working...'}</span>
                    {usageSummary && (
                      <span className="status-usage">
                        ${usageSummary.totalCost?.toFixed(4) || '0.0000'}
                      </span>
                    )}
                  </div>
                )}
                {docStatus && (
                  <div className={`doc-status doc-status-${docStatus.state}`}>
                    <div className="doc-status-main">
                      <span className="doc-status-icon">
                        {docStatus.state === 'creating' && '🛠️'}
                        {docStatus.state === 'ready' && '✅'}
                        {docStatus.state === 'failed' && '⚠️'}
                      </span>
                      <div>
                        <div className="doc-status-label">Document status</div>
                        <div className="doc-status-text">{docStatus.message}</div>
                      </div>
                    </div>
                    {docStatus.file && (
                      <span className="doc-status-file">
                        {docStatus.file.split('/').pop()}
                      </span>
                    )}
                  </div>
                )}
                {thinkingSteps.length > 0 && (
                  <div className="thinking-indicator">
                    <span className="thinking-dot" />
                    <span>Thinking...</span>
                  </div>
                )}
                {toolActivity.length > 0 && (
                  <div className="message-tools">
                    {toolActivity.map((tool, i) => (
                      <ToolStep key={i} tool={tool} isStreaming={true} />
                    ))}
                  </div>
                )}
                {streamingContent && (
                  <div className="message-content streaming">
                    <ReactMarkdown>{streamingContent}</ReactMarkdown>
                  </div>
                )}
                {!streamingContent && toolActivity.length === 0 && thinkingSteps.length === 0 && (
                  <div className="typing-indicator">
                    <span></span><span></span><span></span>
                  </div>
                )}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSubmit} className="input-form">
            <div className="input-wrapper">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Message Zephior Canvas..."
                disabled={isLoading}
              />
              <button type="submit" className="send-btn" disabled={isLoading || !input.trim()}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Preview Panel */}
      {previewOpen && (
        <div className="preview-panel">
          <div className="preview-panel-header">
            <div className="preview-title">
              <div className="preview-label">Document Preview</div>
              <div className="preview-filename">
                {selectedFile ? selectedFile.split('/').pop() : 'Waiting for a document'}
              </div>
            </div>
            <div className="preview-actions">
              {selectedFile && (
                <button onClick={handleDownloadSelected} title="Download file">
                  ⬇
                </button>
              )}
              <button onClick={bumpPreviewRevision} title="Refresh preview">
                ↻
              </button>
              <button onClick={() => setPreviewOpen(false)} title="Close preview">
                ×
              </button>
            </div>
          </div>
          <FileList
            sessionId={activeChat.sessionId}
            onFileSelect={setSelectedFile}
            selectedFile={selectedFile}
            refreshToken={artifactRevision}
            onListUpdate={(files) => {
              if (!files || files.length === 0) return;
              const hasSelected = files.some((f) => f.path === selectedFile);
              if (!hasSelected) {
                setSelectedFile(files[0].path);
              }
              if (!previewOpen) {
                setPreviewOpen(true);
              }
            }}
          />
          <DocumentPreview
            sessionId={activeChat.sessionId}
            filePath={selectedFile}
            creatingFile={creatingFile}
            refreshToken={previewRevision}
          />
        </div>
      )}

      {/* Preview toggle when closed */}
      {!previewOpen && activeChat.sessionId && (
        <button className="preview-toggle-fab" onClick={() => setPreviewOpen(true)} title="Show Preview">
          📄
        </button>
      )}
    </div>
  );
}

export default Chat;

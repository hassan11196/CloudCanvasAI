

if (import.meta.env.DEV) {
  API_BASE_URL = 'http://localhost:8000';
} else {
  API_BASE_URL = 'https://zephior-claude-canvas.up.railway.app'
}

export const apiService = {
  async streamChatMessage(message, sessionId, onEvent, onComplete, onError) {
    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: sessionId }),
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let content = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        for (const line of decoder.decode(value).split('\n')) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              onEvent(data);
              if (data.type === 'text_delta') content += data.content;
              if (data.type === 'complete') onComplete(content || data.content);
            } catch {
              // Ignore JSON parse errors
              console.warn('Failed to parse stream line:', line);
            }
          }
        }
      }
    } catch (error) {
      onError(error);
    }
  },

  async deleteSession(sessionId) {
    const response = await fetch(`${API_BASE_URL}/chat/${sessionId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },
};
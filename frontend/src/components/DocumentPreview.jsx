import { useState, useEffect } from 'react';
import mammoth from 'mammoth';
import './DocumentPreview.css';
import { API_BASE_URL, getAuthHeader } from '../services/api';

function DocumentPreview({ sessionId, filePath, creatingFile, onClose, refreshTrigger }) {
  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fileType, setFileType] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const maxRetries = 3;
  const retryDelay = 1500; // ms

  useEffect(() => {
    if (!sessionId || !filePath) {
      setContent(null);
      setError(null);
      setLoading(false);
      setRetryCount(0);
      return;
    }

    const ext = filePath.split('.').pop()?.toLowerCase();
    setFileType(ext);

    // Add a small delay for newly created files to ensure they're fully written
    const isNewFile = creatingFile === filePath;
    const delay = isNewFile ? 500 : 0;

    const timeoutId = setTimeout(() => {
      loadDocument(ext);
    }, delay);

    return () => clearTimeout(timeoutId);
  }, [sessionId, filePath, refreshTrigger]);

  const loadDocument = async (ext, currentRetry = 0) => {
    setLoading(true);
    setError(null);

    try {
      const url = `${API_BASE_URL}/files/${sessionId}/content/${filePath}`;
      const authHeader = await getAuthHeader();
      const response = await fetch(url, { headers: authHeader });

      if (!response.ok) {
        if (response.status === 404) {
          // File not found - might still be generating, retry if we haven't exceeded limit
          if (currentRetry < maxRetries) {
            setRetryCount(currentRetry + 1);
            setTimeout(() => loadDocument(ext, currentRetry + 1), retryDelay);
            return;
          }
          throw new Error('Document is not available yet. The file may still be generating.');
        }
        throw new Error(`Failed to load file: ${response.statusText}`);
      }

      if (ext === 'docx') {
        const arrayBuffer = await response.arrayBuffer();

        // Check if file is too small (likely still being written or corrupt)
        if (arrayBuffer.byteLength < 100) {
          if (currentRetry < maxRetries) {
            setRetryCount(currentRetry + 1);
            setTimeout(() => loadDocument(ext, currentRetry + 1), retryDelay);
            return;
          }
          throw new Error('Document appears to be empty or still generating.');
        }

        try {
          const result = await mammoth.convertToHtml({ arrayBuffer });
          setContent({ type: 'html', data: result.value });
          setRetryCount(0);
        } catch (conversionError) {
          // Mammoth failed - file might not be fully written yet, retry
          if (currentRetry < maxRetries) {
            console.log(`DOCX conversion failed, retrying (${currentRetry + 1}/${maxRetries})...`);
            setRetryCount(currentRetry + 1);
            setTimeout(() => loadDocument(ext, currentRetry + 1), retryDelay);
            return;
          }
          throw new Error('Unable to preview DOCX. The file might still be generating or is not a valid document.');
        }
      } else if (['txt', 'md', 'json', 'py', 'js', 'jsx', 'ts', 'tsx', 'css', 'html'].includes(ext)) {
        const text = await response.text();
        setContent({ type: 'text', data: text });
        setRetryCount(0);
      } else if (ext === 'pdf') {
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        setContent({ type: 'pdf', data: objectUrl });
        setRetryCount(0);
      } else {
        setContent({ type: 'unsupported', data: ext });
        setRetryCount(0);
      }
    } catch (err) {
      setError(err.message);
      setRetryCount(0);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    const url = `${API_BASE_URL}/files/${sessionId}/content/${filePath}`;
    const authHeader = await getAuthHeader();
    const response = await fetch(url, { headers: authHeader });
    if (!response.ok) {
      setError(`Failed to download file: ${response.statusText}`);
      return;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filePath.split('/').pop();
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
  };

  if (!sessionId || !filePath) {
    return (
      <div className="document-preview empty">
        <div className="empty-state">
          <span className="empty-icon">📄</span>
          <p>No artifact selected</p>
          <p className="empty-hint">Create an artifact to preview it here</p>
        </div>
      </div>
    );
  }

  const isCreating = creatingFile && creatingFile === filePath;

  return (
    <div className="document-preview">
      {isCreating && !content && !loading && !error && (
        <div className="creation-banner">
          <span className="creation-dot" />
          <span>Artifact is being created...</span>
        </div>
      )}
      <div className="preview-content">
        {loading && (
          <div className="loading-state">
            <div className="spinner"></div>
            <p>
              {retryCount > 0
                ? `Loading document (attempt ${retryCount + 1}/${maxRetries + 1})...`
                : 'Loading document...'}
            </p>
          </div>
        )}

        {error && (
          <div className="error-state">
            <span className="error-icon">⚠️</span>
            <p>{error}</p>
            <div className="error-actions">
              <button onClick={() => loadDocument(fileType, 0)}>Retry</button>
              {filePath && (
                <button onClick={handleDownload}>Download</button>
              )}
            </div>
          </div>
        )}

        {!loading && !error && content && (
          <>
            {content.type === 'html' && (
              <div
                className="docx-content"
                dangerouslySetInnerHTML={{ __html: content.data }}
              />
            )}

            {content.type === 'text' && (
              <pre className="text-content">{content.data}</pre>
            )}

            {content.type === 'pdf' && (
              <iframe
                src={content.data}
                className="pdf-frame"
                title="PDF Preview"
              />
            )}

            {content.type === 'unsupported' && (
              <div className="unsupported-state">
                <p>Preview not available for .{content.data} files</p>
                <button onClick={handleDownload}>Download File</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default DocumentPreview;

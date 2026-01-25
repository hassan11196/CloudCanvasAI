import { useState, useEffect } from 'react';
import mammoth from 'mammoth';
import './DocumentPreview.css';
import { API_BASE_URL, getAuthHeader } from '../services/api';

function DocumentPreview({ sessionId, filePath, onClose }) {
  const [content, setContent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [fileType, setFileType] = useState(null);

  useEffect(() => {
    if (!sessionId || !filePath) {
      setContent(null);
      setError(null);
      setLoading(false);
      return;
    }

    const ext = filePath.split('.').pop()?.toLowerCase();
    setFileType(ext);
    loadDocument(ext);
  }, [sessionId, filePath]);

  const loadDocument = async (ext) => {
    setLoading(true);
    setError(null);

    try {
      const url = `${API_BASE_URL}/files/${sessionId}/content/${filePath}`;
      const authHeader = await getAuthHeader();
      const response = await fetch(url, { headers: authHeader });

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Document is not available yet. Waiting for generation...');
        }
        throw new Error(`Failed to load file: ${response.statusText}`);
      }

      if (ext === 'docx') {
        const arrayBuffer = await response.arrayBuffer();
        try {
          const result = await mammoth.convertToHtml({ arrayBuffer });
          setContent({ type: 'html', data: result.value });
        } catch (conversionError) {
          throw new Error('Unable to preview DOCX. The file might still be generating or is not a valid document.');
        }
      } else if (['txt', 'md', 'json', 'py', 'js', 'jsx', 'ts', 'tsx', 'css', 'html'].includes(ext)) {
        const text = await response.text();
        setContent({ type: 'text', data: text });
      } else if (ext === 'pdf') {
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        setContent({ type: 'pdf', data: objectUrl });
      } else {
        setContent({ type: 'unsupported', data: ext });
      }
    } catch (err) {
      setError(err.message);
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
          <p>No document selected</p>
          <p className="empty-hint">Create a document to preview it here</p>
        </div>
      </div>
    );
  }

  return (
    <div className="document-preview">
      <div className="preview-content">
        {loading && (
          <div className="loading-state">
            <div className="spinner"></div>
            <p>Loading document...</p>
          </div>
        )}

        {error && (
          <div className="error-state">
            <span className="error-icon">⚠️</span>
            <p>{error}</p>
            <div className="error-actions">
              <button onClick={() => loadDocument(fileType)}>Retry</button>
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

import { useState, useEffect, useRef, useCallback } from 'react';
import mammoth from 'mammoth';
import './DocumentPreview.css';
import { API_BASE_URL, getAuthHeader } from '../services/api';

const TEXT_EXTENSIONS = ['txt', 'md', 'json', 'py', 'js', 'jsx', 'ts', 'tsx', 'css', 'html'];
const BINARY_EXTENSIONS = new Set(['docx', 'pptx', 'xlsx', 'pdf']);
const MIN_BINARY_SIZE = 120;
const MAX_AUTO_RETRIES = 6;
const BASE_RETRY_DELAY = 1200; // ms

function DocumentPreview({ sessionId, filePath, creatingFile, refreshToken }) {
  const [content, setContent] = useState(null);
  const [viewState, setViewState] = useState({ status: 'idle', message: '' });
  const [attempt, setAttempt] = useState(0);
  const retryTimeoutRef = useRef(null);
  const controllerRef = useRef(null);
  const pdfUrlRef = useRef(null);

  const clearPending = useCallback(() => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }
  }, []);

  const clearPdfUrl = useCallback(() => {
    if (pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current);
      pdfUrlRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearPending();
      clearPdfUrl();
    };
  }, [clearPending, clearPdfUrl]);

  const loadDocument = useCallback(
    (attemptNumber = 0) => {
      if (!sessionId || !filePath) return;

      clearPending();
      const controller = new AbortController();
      controllerRef.current = controller;

      const ext = filePath.split('.').pop()?.toLowerCase() || '';
      const retryLater = (message) => {
        if (attemptNumber >= MAX_AUTO_RETRIES) {
          setViewState({
            status: 'error',
            message: message || 'Document is not available yet.',
          });
          return false;
        }
        const nextAttempt = attemptNumber + 1;
        retryTimeoutRef.current = setTimeout(
          () => loadDocument(nextAttempt),
          Math.min(BASE_RETRY_DELAY * nextAttempt, 4000)
        );
        setAttempt(nextAttempt);
        setViewState({
          status: 'loading',
          message: message || 'Waiting for updated file...',
        });
        return true;
      };

      setAttempt(attemptNumber);
      if (attemptNumber === 0) {
        setContent(null);
      }
      setViewState({
        status: 'loading',
        message:
          creatingFile && creatingFile === filePath
            ? 'Waiting for the agent to finish writing...'
            : attemptNumber
            ? 'Updating preview...'
            : 'Loading document...',
      });

      (async () => {
        try {
          const authHeader = await getAuthHeader();
          const response = await fetch(
            `${API_BASE_URL}/files/${sessionId}/content/${encodeURIComponent(filePath)}?t=${Date.now()}`,
            {
              headers: authHeader,
              cache: 'no-store',
              signal: controller.signal,
            }
          );

          if (!response.ok) {
            if (response.status === 404) {
              retryLater('Document is not ready yet. Checking again...');
              return;
            }
            throw new Error(`Failed to load file (HTTP ${response.status})`);
          }

          if (ext === 'docx') {
            const buffer = await response.arrayBuffer();
            if (buffer.byteLength < MIN_BINARY_SIZE || BINARY_EXTENSIONS.has(ext) && buffer.byteLength === 0) {
              retryLater('Waiting for document contents...');
              return;
            }
            try {
              const result = await mammoth.convertToHtml({ arrayBuffer: buffer });
              setContent({ type: 'docx', data: result.value });
            } catch (conversionError) {
              retryLater('Document is still being finalized...');
              return;
            }
          } else if (ext === 'pdf') {
            const blob = await response.blob();
            if (blob.size < MIN_BINARY_SIZE) {
              retryLater('Waiting for document contents...');
              return;
            }
            clearPdfUrl();
            const url = URL.createObjectURL(blob);
            pdfUrlRef.current = url;
            setContent({ type: 'pdf', data: url });
          } else if (TEXT_EXTENSIONS.includes(ext)) {
            const text = await response.text();
            setContent({ type: 'text', data: text });
          } else {
            setContent({ type: 'unsupported', data: ext });
          }

          setViewState({ status: 'ready', message: 'Live preview' });
        } catch (err) {
          if (controller.signal.aborted) return;
          console.error('Document preview load error:', err);
          const scheduled = retryLater(err.message || 'Retrying...');
          if (!scheduled) {
            setViewState({
              status: 'error',
              message: err.message || 'Unable to preview document.',
            });
          }
        }
      })();
    },
    [sessionId, filePath, creatingFile, clearPending, clearPdfUrl]
  );

  useEffect(() => {
    if (!sessionId || !filePath) {
      clearPending();
      setContent(null);
      setViewState({ status: 'idle', message: '' });
      setAttempt(0);
      return;
    }
    loadDocument(0);
  }, [sessionId, filePath, refreshToken, loadDocument, clearPending]);

  const handleDownload = async () => {
    try {
      const authHeader = await getAuthHeader();
      const response = await fetch(
        `${API_BASE_URL}/files/${sessionId}/content/${encodeURIComponent(filePath)}?t=${Date.now()}`,
        {
          headers: authHeader,
          cache: 'no-store',
        }
      );
      if (!response.ok) {
        throw new Error(`Failed to download file (HTTP ${response.status})`);
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
    } catch (err) {
      setViewState({ status: 'error', message: err.message });
    }
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

  const isLoading = viewState.status === 'loading';
  const isError = viewState.status === 'error';

  return (
    <div className="document-preview">
      <div className="preview-content">
        {isLoading && (
          <div className="loading-state">
            <div className="spinner"></div>
            <p>{viewState.message || 'Loading document...'}</p>
          </div>
        )}

        {isError && (
          <div className="error-state">
            <span className="error-icon">⚠️</span>
            <p>{viewState.message || 'Unable to preview document.'}</p>
            <div className="error-actions">
              <button onClick={() => loadDocument(0)}>Retry now</button>
              {filePath && <button onClick={handleDownload}>Download</button>}
            </div>
          </div>
        )}

        {!isLoading && !isError && content && (
          <>
            {content.type === 'docx' && (
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

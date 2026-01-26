import { useState, useEffect, useCallback, useRef } from 'react';
import './FileList.css';
import { API_BASE_URL, getAuthHeader } from '../services/api';

const FILE_ICONS = {
  docx: '📄',
  doc: '📄',
  pdf: '📕',
  pptx: '📊',
  ppt: '📊',
  xlsx: '📈',
  xls: '📈',
  txt: '📝',
  md: '📝',
  json: '📋',
  py: '🐍',
  js: '📜',
  jsx: '⚛️',
  ts: '📘',
  tsx: '⚛️',
  css: '🎨',
  html: '🌐',
  folder: '📁',
  default: '📄'
};

function FileList({ sessionId, onFileSelect, selectedFile, refreshToken, onListUpdate }) {
  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const inFlightRef = useRef(false);

  const loadArtifacts = useCallback(async (silent = false) => {
    if (!sessionId) {
      setArtifacts([]);
      return;
    }
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    if (!silent) {
      setLoading(true);
      setError(null);
    }

    try {
      const authHeader = await getAuthHeader();
      const response = await fetch(`${API_BASE_URL}/files/${sessionId}/artifacts`, {
        headers: authHeader,
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error('Failed to load artifacts');
      }
      const data = await response.json();
      setArtifacts(data);
      if (onListUpdate) {
        onListUpdate(data);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      inFlightRef.current = false;
      if (!silent) {
        setLoading(false);
      }
    }
  }, [sessionId, onListUpdate]);

  useEffect(() => {
    if (sessionId) {
      loadArtifacts();
    } else {
      setArtifacts([]);
    }
  }, [sessionId, refreshToken, loadArtifacts]);

  // Auto-select an artifact when none (or a stale one) is selected
  useEffect(() => {
    const docFiles = artifacts.filter((file) => !file.is_dir && isDocumentFile(file.name));
    if (docFiles.length === 0) return;

    const selectedStillExists = docFiles.some((file) => file.path === selectedFile);
    if (!selectedFile || !selectedStillExists) {
      onFileSelect(docFiles[0].path);
    }
  }, [artifacts, selectedFile, onFileSelect]);

  const getFileIcon = (file) => {
    if (file.is_dir) return FILE_ICONS.folder;
    const ext = file.name.split('.').pop()?.toLowerCase();
    return FILE_ICONS[ext] || FILE_ICONS.default;
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const isDocumentFile = (filename) => {
    const ext = filename.split('.').pop()?.toLowerCase();
    return ['docx', 'pdf', 'pptx', 'xlsx', 'txt', 'md'].includes(ext);
  };

  if (!sessionId) {
    return (
      <div className="file-list empty">
        <p>No active session</p>
      </div>
    );
  }

  return (
    <div className="file-list">
      <div className="file-list-header">
        <span>Artifacts</span>
      </div>

      {loading && (
        <div className="file-list-loading">
          <span>Loading artifacts...</span>
        </div>
      )}

      {error && (
        <div className="file-list-error">
          <span>⚠️ {error}</span>
          <button onClick={loadArtifacts}>Retry</button>
        </div>
      )}

      {!loading && !error && artifacts.length === 0 && (
        <div className="file-list-empty">
          <p>No artifacts yet</p>
        </div>
      )}

      {!loading && !error && artifacts.length > 0 && (
        <div className="file-list-items">
          {artifacts.map((file) => (
            <div
              key={file.path}
              className={`file-item ${file.path === selectedFile ? 'selected' : ''} ${!isDocumentFile(file.name) || file.is_dir ? 'disabled' : ''}`}
              onClick={() => {
                if (!file.is_dir && isDocumentFile(file.name)) {
                  onFileSelect(file.path);
                }
              }}
            >
              <span className="file-item-icon">{getFileIcon(file)}</span>
              <span className="file-item-name">{file.name}</span>
              {!file.is_dir && (
                <span className="file-item-size">{formatSize(file.size)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default FileList;

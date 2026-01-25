import { useState, useEffect } from 'react';
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

function FileList({ sessionId, onFileSelect, selectedFile, refreshTrigger }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (sessionId) {
      loadFiles();
    } else {
      setFiles([]);
    }
  }, [sessionId, refreshTrigger]);

  const loadFiles = async () => {
    setLoading(true);
    setError(null);

    try {
      const authHeader = await getAuthHeader();
      const response = await fetch(`${API_BASE_URL}/files/${sessionId}/list`, {
        headers: authHeader,
      });
      if (!response.ok) {
        throw new Error('Failed to load files');
      }
      const data = await response.json();
      setFiles(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

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
    return ['docx', 'pdf', 'pptx', 'xlsx', 'txt', 'md', 'json', 'py', 'js', 'jsx', 'ts', 'tsx', 'css', 'html'].includes(ext);
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
        <span>Files</span>
        <button className="refresh-btn" onClick={loadFiles} title="Refresh">
          🔄
        </button>
      </div>

      {loading && (
        <div className="file-list-loading">
          <span>Loading...</span>
        </div>
      )}

      {error && (
        <div className="file-list-error">
          <span>⚠️ {error}</span>
          <button onClick={loadFiles}>Retry</button>
        </div>
      )}

      {!loading && !error && files.length === 0 && (
        <div className="file-list-empty">
          <p>No files yet</p>
        </div>
      )}

      {!loading && !error && files.length > 0 && (
        <div className="file-list-items">
          {files.map((file) => (
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

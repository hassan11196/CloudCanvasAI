import { Routes, Route, Link } from 'react-router-dom'
import Chat from './pages/Chat'
import './App.css'

function Home() {
  return (
    <div className="home">
      <div className="home-hero">
        <div className="home-icon">⚡</div>
        <h1 className="home-title">Zephior</h1>
        <p className="home-subtitle">Your AI-powered coding assistant</p>
        <div className="home-features">
          <div className="feature">
            <span className="feature-icon">📄</span>
            <span>Read & analyze files</span>
          </div>
          <div className="feature">
            <span className="feature-icon">✏️</span>
            <span>Edit & write code</span>
          </div>
          <div className="feature">
            <span className="feature-icon">⚡</span>
            <span>Run commands</span>
          </div>
        </div>
        <Link to="/chat" className="home-cta">Start Chatting →</Link>
      </div>
    </div>
  )
}

function App() {
  return (
    <div className="app">
      <nav className="nav">
        <Link to="/">Home</Link>
        <Link to="/chat">Chat</Link>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
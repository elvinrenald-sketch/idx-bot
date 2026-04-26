import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import IdxDashboard from './pages/IdxDashboard'
import PolymarketDashboard from './pages/PolymarketDashboard'
import './App.css'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/idx" element={<IdxDashboard />} />
        <Route path="/polymarket" element={<PolymarketDashboard />} />
      </Routes>
    </Router>
  )
}

export default App

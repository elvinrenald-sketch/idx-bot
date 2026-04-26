import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './IdxDashboard.css';

interface Holding {
  ticker: string;
  name: string;
  avgPrice: number;
  lots: number;
  currentPrice: number;
  allocation: number;
  color: string;
}

interface AiMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

const MOCK_HOLDINGS: Holding[] = [
  { ticker: 'BBCA', name: 'Bank Central Asia', avgPrice: 9800, lots: 100, currentPrice: 10250, allocation: 35, color: '#00d4aa' },
  { ticker: 'AMMN', name: 'Amman Mineral', avgPrice: 8500, lots: 50, currentPrice: 9100, allocation: 20, color: '#00aaff' },
  { ticker: 'BREN', name: 'Barito Renewables', avgPrice: 10000, lots: 30, currentPrice: 9400, allocation: 15, color: '#8b5cf6' },
  { ticker: 'BMRI', name: 'Bank Mandiri', avgPrice: 6200, lots: 80, currentPrice: 6550, allocation: 15, color: '#f59e0b' },
];

const IdxDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);
  const [modalAction, setModalAction] = useState<'BUY' | 'SELL'>('BUY');
  const [formTicker, setFormTicker] = useState('');
  const [formPrice, setFormPrice] = useState('');
  const [formLots, setFormLots] = useState('');
  const [holdings, setHoldings] = useState<Holding[]>(MOCK_HOLDINGS);
  const [aiInput, setAiInput] = useState('');
  const [aiTyping, setAiTyping] = useState(false);
  const [aiMessages, setAiMessages] = useState<AiMessage[]>([
    { role: 'system', content: '🤖 AI Fund Manager aktif. Saya siap menganalisis portofolio dan memberikan saran alokasi. Ketik nama saham atau pertanyaan Anda.' }
  ]);

  const totalEquity = holdings.reduce((sum, h) => sum + h.currentPrice * h.lots * 100, 0);
  const totalCost = holdings.reduce((sum, h) => sum + h.avgPrice * h.lots * 100, 0);
  const totalPnl = totalEquity - totalCost;
  const totalPnlPercent = totalCost > 0 ? ((totalPnl / totalCost) * 100) : 0;

  const formatRp = (val: number) => {
    if (val >= 1_000_000_000) return `Rp ${(val / 1_000_000_000).toFixed(2)}B`;
    if (val >= 1_000_000) return `Rp ${(val / 1_000_000).toFixed(1)}M`;
    return `Rp ${val.toLocaleString('id-ID')}`;
  };

  const handleAddTrade = () => {
    if (!formTicker || !formPrice || !formLots) return;

    const ticker = formTicker.toUpperCase();
    const price = parseFloat(formPrice);
    const lots = parseInt(formLots);

    if (modalAction === 'BUY') {
      const existing = holdings.find(h => h.ticker === ticker);
      if (existing) {
        const newTotalLots = existing.lots + lots;
        const newAvgPrice = ((existing.avgPrice * existing.lots) + (price * lots)) / newTotalLots;
        setHoldings(prev => prev.map(h =>
          h.ticker === ticker
            ? { ...h, avgPrice: Math.round(newAvgPrice), lots: newTotalLots }
            : h
        ));
      } else {
        const colors = ['#00d4aa', '#00aaff', '#8b5cf6', '#f59e0b', '#ef4444'];
        setHoldings(prev => [...prev, {
          ticker,
          name: ticker,
          avgPrice: price,
          lots,
          currentPrice: price,
          allocation: 0,
          color: colors[prev.length % colors.length]
        }]);
      }
    } else {
      setHoldings(prev => prev.map(h => {
        if (h.ticker !== ticker) return h;
        const newLots = h.lots - lots;
        if (newLots <= 0) return null as unknown as Holding;
        return { ...h, lots: newLots };
      }).filter(Boolean));
    }

    setShowModal(false);
    setFormTicker('');
    setFormPrice('');
    setFormLots('');
  };

  const handleAiSend = () => {
    if (!aiInput.trim()) return;

    const userMsg: AiMessage = { role: 'user', content: aiInput };
    setAiMessages(prev => [...prev, userMsg]);
    setAiInput('');
    setAiTyping(true);

    // Simulate AI response
    setTimeout(() => {
      const ticker = aiInput.toUpperCase().match(/[A-Z]{4}/)?.[0] || '';
      const found = holdings.find(h => h.ticker === ticker);
      let response = '';

      if (found) {
        const pnl = ((found.currentPrice - found.avgPrice) / found.avgPrice * 100).toFixed(1);
        const allocPct = ((found.currentPrice * found.lots * 100) / totalEquity * 100).toFixed(1);
        response = `📊 **Analisis ${found.ticker}:**\n\n` +
          `Posisi saat ini: ${found.lots} lot @ Rp ${found.avgPrice.toLocaleString()}\n` +
          `PnL: ${Number(pnl) >= 0 ? '+' : ''}${pnl}% | Alokasi: ${allocPct}% dari total portofolio.\n\n` +
          `💡 **Saran:** ${Number(pnl) > 5 ? 'Pertimbangkan profit-taking sebagian (50%) untuk mengamankan keuntungan.' : Number(pnl) < -5 ? 'Cutloss mungkin diperlukan jika tidak ada katalis positif. Atur stop-loss ketat.' : 'Posisi masih sehat. Hold dan monitor support terdekat.'}`;
      } else if (ticker) {
        const suggestedAlloc = Math.min(10, Math.max(3, 100 / (holdings.length + 1)));
        response = `🔍 **${ticker}** belum ada di portofolio Anda.\n\n` +
          `Dengan total equity ${formatRp(totalEquity)}, saya sarankan entry **maksimal ${suggestedAlloc.toFixed(0)}%** (${formatRp(totalEquity * suggestedAlloc / 100)}).\n\n` +
          `⚠️ Pastikan diversifikasi sektor terjaga. Anda sudah memiliki ${holdings.length} posisi aktif.`;
      } else {
        response = `Saya adalah AI Fund Manager Anda. Saya bisa membantu:\n\n` +
          `• Ketik **nama saham** (contoh: BBCA) untuk analisis posisi\n` +
          `• Tanya "berapa alokasi untuk GOTO?" untuk saran entry\n` +
          `• Tanya "review portofolio" untuk ringkuan keseluruhan`;
      }

      setAiMessages(prev => [...prev, { role: 'assistant', content: response }]);
      setAiTyping(false);
    }, 1500);
  };

  return (
    <div className="idx-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo" onClick={() => navigate('/')}>A</div>
        <div className="sidebar-icon active" title="Dashboard">📊</div>
        <div className="sidebar-icon" title="Portfolio">💼</div>
        <div className="sidebar-icon" title="Signals">📡</div>
        <div className="sidebar-icon" title="News">📰</div>
        <div className="sidebar-bottom">
          <div className="sidebar-icon" title="Settings">⚙️</div>
          <div className="sidebar-icon" title="Back" onClick={() => navigate('/')}>◀</div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="dashboard-main">
        {/* Top Bar */}
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">IDX INTELLIGENCE</span>
            <span className="topbar-tag">● LIVE</span>
          </div>
          <div className="topbar-search">
            <span className="topbar-search-icon">🔍</span>
            <input type="text" placeholder="Search ticker..." />
          </div>
          <div className="topbar-right">
            <button className="topbar-icon-btn" title="Notifications">🔔</button>
            <button className="topbar-icon-btn" title="Filter">⊞</button>
          </div>
        </header>

        {/* Dashboard Body */}
        <div className="dashboard-body">
          {/* Portfolio Overview Stats */}
          <div className="portfolio-overview" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.1s forwards' }}>
            <div className="stat-card">
              <div className="stat-label">Total Equity</div>
              <div className="stat-value">{formatRp(totalEquity)}</div>
              <span className={`stat-change ${totalPnl >= 0 ? 'positive' : 'negative'}`}>
                {totalPnl >= 0 ? '▲' : '▼'} {totalPnlPercent.toFixed(2)}%
              </span>
            </div>
            <div className="stat-card">
              <div className="stat-label">Unrealized PnL</div>
              <div className="stat-value" style={{ color: totalPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                {totalPnl >= 0 ? '+' : ''}{formatRp(totalPnl)}
              </div>
              <span className={`stat-change ${totalPnl >= 0 ? 'positive' : 'negative'}`}>
                {totalPnl >= 0 ? '▲' : '▼'} Floating
              </span>
            </div>
            <div className="stat-card">
              <div className="stat-label">Active Positions</div>
              <div className="stat-value">{holdings.length}</div>
              <span className="stat-change positive">● Active</span>
            </div>
            <div className="stat-card">
              <div className="stat-label">Win Rate</div>
              <div className="stat-value">{((holdings.filter(h => h.currentPrice >= h.avgPrice).length / Math.max(holdings.length, 1)) * 100).toFixed(0)}%</div>
              <span className="stat-change positive">
                {holdings.filter(h => h.currentPrice >= h.avgPrice).length}W / {holdings.filter(h => h.currentPrice < h.avgPrice).length}L
              </span>
            </div>
          </div>

          {/* Main Grid: Holdings + AI Advisor */}
          <div className="dashboard-grid" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.3s forwards' }}>
            {/* Holdings Panel */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">📋 Current Holdings</span>
                <div className="panel-actions">
                  <button className="panel-action-btn active" onClick={() => { setModalAction('BUY'); setShowModal(true); }}>+ Add Trade</button>
                </div>
              </div>
              <div className="panel-body">
                <table className="holdings-table">
                  <thead>
                    <tr>
                      <th>Ticker</th>
                      <th>Avg Price</th>
                      <th>Current</th>
                      <th>Lots</th>
                      <th>PnL</th>
                      <th>Allocation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((h) => {
                      const pnl = (h.currentPrice - h.avgPrice) * h.lots * 100;
                      const pnlPct = ((h.currentPrice - h.avgPrice) / h.avgPrice * 100);
                      const allocPct = (h.currentPrice * h.lots * 100) / totalEquity * 100;
                      return (
                        <tr key={h.ticker}>
                          <td>
                            <div className="ticker-cell">
                              <div className="ticker-dot" style={{ background: h.color }}></div>
                              <div>
                                <div className="ticker-name">{h.ticker}</div>
                                <div className="ticker-fullname">{h.name}</div>
                              </div>
                            </div>
                          </td>
                          <td className="value-cell">Rp {h.avgPrice.toLocaleString()}</td>
                          <td className="value-cell">Rp {h.currentPrice.toLocaleString()}</td>
                          <td className="value-cell">{h.lots}</td>
                          <td>
                            <span className={pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                              {pnl >= 0 ? '+' : ''}{formatRp(pnl)} ({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)
                            </span>
                          </td>
                          <td>
                            <div className="alloc-bar-container">
                              <div className="alloc-bar">
                                <div className="alloc-bar-fill" style={{ width: `${allocPct}%`, background: h.color }}></div>
                              </div>
                              <span className="alloc-text">{allocPct.toFixed(1)}%</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* AI Advisor */}
            <div className="panel ai-panel">
              <div className="panel-header">
                <span className="panel-title">🧠 AI Fund Manager</span>
                <span className="topbar-tag">● Gemini Pro</span>
              </div>
              <div className="ai-messages">
                {aiMessages.map((msg, i) => (
                  <div key={i} className={`ai-msg ${msg.role}`}>
                    <div className={`ai-msg-label ${msg.role === 'system' ? 'green' : msg.role === 'assistant' ? 'purple' : 'blue'}`}>
                      {msg.role === 'system' ? '⚡ SYSTEM' : msg.role === 'user' ? '👤 YOU' : '🤖 AI ADVISOR'}
                    </div>
                    {msg.content.split('\n').map((line, j) => (
                      <div key={j}>{line}</div>
                    ))}
                  </div>
                ))}
                {aiTyping && (
                  <div className="ai-msg assistant">
                    <div className="ai-msg-label purple">🤖 AI ADVISOR</div>
                    <div className="typing-indicator">
                      <div className="typing-dot"></div>
                      <div className="typing-dot"></div>
                      <div className="typing-dot"></div>
                    </div>
                  </div>
                )}
              </div>
              <div className="ai-input-area">
                <input
                  className="ai-input"
                  placeholder="Ketik: BBCA, atau 'review portofolio'..."
                  value={aiInput}
                  onChange={(e) => setAiInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleAiSend(); }}
                />
                <button className="ai-send-btn" onClick={handleAiSend} disabled={aiTyping}>
                  Send
                </button>
              </div>
            </div>
          </div>

          {/* Bottom Grid: Signals, Allocation, Actions */}
          <div className="bottom-grid" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.5s forwards' }}>
            {/* Corporate Action Signals */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">📡 Corporate Signals</span>
              </div>
              <div className="panel-body">
                <div className="signal-list">
                  <div className="signal-item">
                    <span className="signal-badge ma">M&A</span>
                    <span className="signal-text">BREN akuisisi aset renewables baru</span>
                    <span className="signal-time">14:30</span>
                  </div>
                  <div className="signal-item">
                    <span className="signal-badge dividend">Dividen</span>
                    <span className="signal-text">BBCA dividen interim Rp 125/lembar</span>
                    <span className="signal-time">10:15</span>
                  </div>
                  <div className="signal-item">
                    <span className="signal-badge insider">Insider</span>
                    <span className="signal-text">Direksi AMMN beli 2M lembar</span>
                    <span className="signal-time">09:45</span>
                  </div>
                  <div className="signal-item">
                    <span className="signal-badge warning">Warning</span>
                    <span className="signal-text">GOTO laporan keuangan terlambat</span>
                    <span className="signal-time">08:30</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Allocation Visual */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">🎯 Allocation</span>
              </div>
              <div className="panel-body">
                <div className="allocation-visual">
                  <div className="pie-chart">
                    <div className="pie-center">
                      <div className="pie-center-value">{holdings.length}</div>
                      <div className="pie-center-label">Stocks</div>
                    </div>
                  </div>
                  <div className="pie-legend">
                    {holdings.map(h => (
                      <div className="legend-item" key={h.ticker}>
                        <div className="legend-dot" style={{ background: h.color }}></div>
                        <span className="legend-label">{h.ticker}</span>
                        <span className="legend-value">{((h.currentPrice * h.lots * 100) / totalEquity * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                    <div className="legend-item">
                      <div className="legend-dot" style={{ background: 'rgba(255,255,255,0.1)' }}></div>
                      <span className="legend-label">Cash</span>
                      <span className="legend-value">15%</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Disclosure Intelligence */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">📄 Disclosure Intel</span>
              </div>
              <div className="panel-body">
                <div className="signal-list">
                  <div className="signal-item">
                    <span className="signal-badge insider">Form 4</span>
                    <span className="signal-text">BBCA - CEO beli 50K lembar</span>
                    <span className="signal-time">11:25</span>
                  </div>
                  <div className="signal-item">
                    <span className="signal-badge ma">Filing</span>
                    <span className="signal-text">AMMN - Laporan Tahunan 2025</span>
                    <span className="signal-time">10:50</span>
                  </div>
                  <div className="signal-item">
                    <span className="signal-badge dividend">Buyback</span>
                    <span className="signal-text">BMRI - Program buyback 1.2M lembar</span>
                    <span className="signal-time">10:30</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Add Trade Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="modal-title">📝 Record Trade</h2>
            <div className="form-group">
              <label className="form-label">Action</label>
              <div className="action-toggle">
                <button
                  className={`action-toggle-btn ${modalAction === 'BUY' ? 'active-buy' : ''}`}
                  onClick={() => setModalAction('BUY')}
                >
                  BUY
                </button>
                <button
                  className={`action-toggle-btn ${modalAction === 'SELL' ? 'active-sell' : ''}`}
                  onClick={() => setModalAction('SELL')}
                >
                  SELL
                </button>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Ticker</label>
              <input
                className="form-input"
                placeholder="e.g. BBCA"
                value={formTicker}
                onChange={(e) => setFormTicker(e.target.value)}
              />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Price (Rp)</label>
                <input
                  className="form-input"
                  type="number"
                  placeholder="9800"
                  value={formPrice}
                  onChange={(e) => setFormPrice(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Lots</label>
                <input
                  className="form-input"
                  type="number"
                  placeholder="100"
                  value={formLots}
                  onChange={(e) => setFormLots(e.target.value)}
                />
              </div>
            </div>
            <div className="form-actions">
              <button className="btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={handleAddTrade}>
                {modalAction === 'BUY' ? '✓ Record Buy' : '✓ Record Sell'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IdxDashboard;

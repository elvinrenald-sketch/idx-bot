import React from 'react';
import { useNavigate } from 'react-router-dom';
import './PolymarketDashboard.css';

interface Market {
  id: number;
  question: string;
  probability: number;
  volume: string;
  position: string;
  pnl: number;
  status: 'active' | 'resolved';
  color: string;
}

const MOCK_MARKETS: Market[] = [
  { id: 1, question: 'Will Bitcoin reach $150K by Dec 2026?', probability: 68, volume: '$2.4M', position: '50 YES @ $0.62', pnl: 3.10, status: 'active', color: '#00aaff' },
  { id: 2, question: 'US Fed rate cut in Q3 2026?', probability: 42, volume: '$890K', position: '30 YES @ $0.38', pnl: 1.20, status: 'active', color: '#8b5cf6' },
  { id: 3, question: 'ETH ETF approval before Aug 2026?', probability: 75, volume: '$1.8M', position: '20 YES @ $0.71', pnl: -0.80, status: 'active', color: '#00d4aa' },
  { id: 4, question: 'SOL flips BNB in market cap?', probability: 31, volume: '$560K', position: '40 NO @ $0.65', pnl: 2.60, status: 'active', color: '#f59e0b' },
  { id: 5, question: 'Trump wins 2028 nomination?', probability: 55, volume: '$4.1M', position: '—', pnl: 0, status: 'active', color: '#ef4444' },
];

const MOCK_TRADES = [
  { type: 'buy', market: 'BTC $150K by Dec 2026', amount: '$3.10', time: '14:32' },
  { type: 'sell', market: 'US Fed rate cut Q3', amount: '$1.50', time: '13:15' },
  { type: 'buy', market: 'ETH ETF approval', amount: '$1.42', time: '11:45' },
  { type: 'sell', market: 'SOL flips BNB', amount: '$2.60', time: '10:20' },
  { type: 'buy', market: 'Trump 2028 nomination', amount: '$0.55', time: '09:05' },
];

const MOCK_NEWS = [
  { title: 'Bitcoin surges past $120K as ETF inflows hit record', source: 'CoinDesk', time: '2h ago' },
  { title: 'Fed signals potential rate cut amid cooling inflation', source: 'Reuters', time: '4h ago' },
  { title: 'Solana TVL reaches all-time high of $28B', source: 'The Block', time: '6h ago' },
  { title: 'Polymarket volume exceeds $500M in April', source: 'DeFi Pulse', time: '8h ago' },
];

const PolymarketDashboard: React.FC = () => {
  const navigate = useNavigate();

  const totalEquity = 9.31;
  const totalPnl = -1.23;
  const winRate = 67;
  const totalTrades = 48;

  return (
    <div className="poly-container">
      {/* Sidebar - reused structure */}
      <aside className="sidebar">
        <div className="sidebar-logo" onClick={() => navigate('/')}>A</div>
        <div className="sidebar-icon active" title="Markets">📈</div>
        <div className="sidebar-icon" title="Portfolio">💰</div>
        <div className="sidebar-icon" title="ML Model">🧪</div>
        <div className="sidebar-icon" title="News">📰</div>
        <div className="sidebar-bottom">
          <div className="sidebar-icon" title="Settings">⚙️</div>
          <div className="sidebar-icon" title="Back" onClick={() => navigate('/')}>◀</div>
        </div>
      </aside>

      <div className="poly-main">
        {/* Top Bar */}
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">POLYMARKET SCANNER</span>
            <span className="topbar-tag" style={{ background: 'var(--accent-purple-dim)', color: 'var(--accent-purple)' }}>● AI MODE</span>
          </div>
          <div className="topbar-search">
            <span className="topbar-search-icon">🔍</span>
            <input type="text" placeholder="Search markets..." />
          </div>
          <div className="topbar-right">
            <button className="topbar-icon-btn" title="Notifications">🔔</button>
            <button className="topbar-icon-btn" title="Grid">⊞</button>
          </div>
        </header>

        <div className="poly-body">
          {/* Stats */}
          <div className="poly-stats" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.1s forwards' }}>
            <div className="poly-stat-card">
              <div className="stat-label">Account Equity</div>
              <div className="stat-value">${totalEquity.toFixed(2)}</div>
              <span className={`stat-change ${totalPnl >= 0 ? 'positive' : 'negative'}`}>
                {totalPnl >= 0 ? '▲' : '▼'} ${Math.abs(totalPnl).toFixed(2)}
              </span>
            </div>
            <div className="poly-stat-card">
              <div className="stat-label">Total PnL</div>
              <div className="stat-value" style={{ color: totalPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                {totalPnl >= 0 ? '+' : '-'}${Math.abs(totalPnl).toFixed(2)}
              </div>
              <span className={`stat-change ${totalPnl >= 0 ? 'positive' : 'negative'}`}>
                All time
              </span>
            </div>
            <div className="poly-stat-card">
              <div className="stat-label">Win Rate</div>
              <div className="stat-value">{winRate}%</div>
              <span className="stat-change positive">ML Confidence</span>
            </div>
            <div className="poly-stat-card">
              <div className="stat-label">Total Trades</div>
              <div className="stat-value">{totalTrades}</div>
              <span className="stat-change positive">● Running</span>
            </div>
          </div>

          {/* Main Grid */}
          <div className="poly-grid" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.3s forwards' }}>
            {/* Active Markets */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">🎯 Active Markets</span>
                <div className="panel-actions">
                  <button className="panel-action-btn active">All</button>
                  <button className="panel-action-btn">My Positions</button>
                  <button className="panel-action-btn">Watchlist</button>
                </div>
              </div>
              <div className="panel-body">
                <div className="market-list">
                  {MOCK_MARKETS.map((m) => (
                    <div className="market-card" key={m.id}>
                      <div
                        className="market-prob-ring"
                        style={{
                          background: `conic-gradient(${m.color} 0% ${m.probability}%, rgba(255,255,255,0.08) ${m.probability}% 100%)`
                        }}
                      >
                        <div className="market-prob-inner" style={{ color: m.color }}>
                          {m.probability}%
                        </div>
                      </div>
                      <div className="market-info">
                        <div className="market-question">{m.question}</div>
                        <div className="market-meta">
                          <span className="market-volume">Vol: {m.volume}</span>
                          <span className="market-status">
                            <span className="market-status-dot"></span>
                            {m.status === 'active' ? 'Active' : 'Resolved'}
                          </span>
                        </div>
                      </div>
                      <div className="market-action-area">
                        <span className={`market-pnl ${m.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
                          {m.pnl > 0 ? '+' : ''}{m.pnl !== 0 ? `$${m.pnl.toFixed(2)}` : '—'}
                        </span>
                        <span className="market-position">{m.position}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ML Model Performance */}
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">🧠 ML Model</span>
                <span className="topbar-tag" style={{ background: 'var(--accent-green-dim)', color: 'var(--accent-green)' }}>v2.1</span>
              </div>
              <div className="ml-panel-body">
                <div>
                  <div className="ml-metric">
                    <span className="ml-metric-label">Confidence Threshold</span>
                    <span className="ml-metric-value" style={{ color: 'var(--accent-green)' }}>60%</span>
                  </div>
                  <div className="ml-bar">
                    <div className="ml-bar-fill" style={{ width: '60%', background: 'var(--accent-green)' }}></div>
                  </div>
                </div>

                <div>
                  <div className="ml-metric">
                    <span className="ml-metric-label">Prediction Accuracy</span>
                    <span className="ml-metric-value" style={{ color: 'var(--accent-blue)' }}>67%</span>
                  </div>
                  <div className="ml-bar">
                    <div className="ml-bar-fill" style={{ width: '67%', background: 'var(--accent-blue)' }}></div>
                  </div>
                </div>

                <div>
                  <div className="ml-metric">
                    <span className="ml-metric-label">Training Data Points</span>
                    <span className="ml-metric-value">48 / 300</span>
                  </div>
                  <div className="ml-bar">
                    <div className="ml-bar-fill" style={{ width: '16%', background: 'var(--accent-amber)' }}></div>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem', marginTop: '0.5rem' }}>
                  <div className="ml-metric" style={{ marginBottom: '0.75rem' }}>
                    <span className="ml-metric-label" style={{ fontWeight: 700 }}>Feature Importance</span>
                  </div>
                  <div className="feature-list">
                    {[
                      { name: 'Liquidity Depth', value: 0.34, color: '#00d4aa' },
                      { name: 'Volume 24h', value: 0.28, color: '#00aaff' },
                      { name: 'Price Momentum', value: 0.19, color: '#8b5cf6' },
                      { name: 'News Sentiment', value: 0.12, color: '#f59e0b' },
                      { name: 'Spread Width', value: 0.07, color: '#ef4444' },
                    ].map((f, i) => (
                      <div className="feature-item" key={f.name}>
                        <span className="feature-rank">{i + 1}</span>
                        <span className="feature-name">{f.name}</span>
                        <div className="feature-bar-wrap">
                          <div className="feature-bar-fill" style={{ width: `${f.value * 100}%`, background: f.color }}></div>
                        </div>
                        <span className="feature-value">{(f.value * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom: Trade History + News */}
          <div className="poly-bottom" style={{ opacity: 0, animation: 'fadeIn 0.5s ease 0.5s forwards' }}>
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">📜 Recent Trades</span>
              </div>
              <div className="panel-body">
                <div className="trade-history-list">
                  {MOCK_TRADES.map((t, i) => (
                    <div className="trade-row" key={i}>
                      <span className={`trade-type ${t.type}`}>{t.type}</span>
                      <span className="trade-market-name">{t.market}</span>
                      <span className={`trade-amount ${t.type === 'buy' ? 'pnl-positive' : 'pnl-negative'}`}>{t.amount}</span>
                      <span className="trade-time">{t.time}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">📰 News Intelligence</span>
              </div>
              <div className="panel-body">
                <div className="news-list">
                  {MOCK_NEWS.map((n, i) => (
                    <div className="news-item" key={i}>
                      <div className="news-title">{n.title}</div>
                      <div className="news-source">
                        <span>{n.source}</span>
                        <span>{n.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PolymarketDashboard;

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './Home.css';

const Home: React.FC = () => {
  const navigate = useNavigate();
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    setIsLoaded(true);
  }, []);

  return (
    <div className="home-container">
      {/* Dynamic Backgrounds */}
      <div className="stars-bg"></div>
      <div className="ambient-glow-left"></div>
      <div className="ambient-glow-right"></div>

      {/* Navigation */}
      <nav className={`navbar ${isLoaded ? 'animate-fade-in' : ''}`}>
        <div className="logo-container">
          <div className="logo-icon">A</div>
          <span>AURA INTELLIGENCE</span>
        </div>
        <div className="nav-links">
          <a href="#" className="nav-link active">Intelligence</a>
          <a href="#" className="nav-link">Markets</a>
          <a href="#" className="nav-link">Analysis</a>
        </div>
        <button className="sign-in-btn">Settings</button>
      </nav>

      {/* Main Content */}
      <main className="main-content">
        <div className={`hero-text ${isLoaded ? 'animate-fade-in delay-1' : ''}`}>
          <h1 className="hero-title">
            The Future of Market Intelligence:<br/>
            <span>AI-Powered Insights</span>
          </h1>
          <p className="hero-subtitle">
            A unified analytical dashboard designed for your financial and crypto intelligence. 
            Choose your engine to begin predicting and tracking.
          </p>
        </div>

        <div className={`portals-grid ${isLoaded ? 'animate-slide-up delay-2' : ''}`}>
          
          {/* Polymarket Portal */}
          <div className="portal-card card-poly">
            <div className="card-content">
              <div className="card-header">
                <div className="card-icon" style={{ borderColor: 'rgba(0,170,255,0.3)', color: '#00aaff' }}>
                  ✧
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '12px' }}>Charts</span>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '12px' }}>Tokens</span>
                </div>
              </div>
              <h2 className="card-title">POLYMARKET</h2>
              <div style={{ color: '#00aaff', fontSize: '0.85rem', fontWeight: 600, marginTop: '4px', letterSpacing: '1px' }}>
                CRYPTO PREDICTION AI
              </div>
              
              <div className="card-visual">
                <div className="poly-circle">
                  <div className="poly-inner text-accent" style={{ color: '#00aaff' }}>
                    ₿
                  </div>
                </div>
                {/* Mock chart lines */}
                <svg width="100%" height="40" style={{ position: 'absolute', bottom: 10, left: 0, opacity: 0.5 }}>
                  <path d="M0 30 Q 30 10, 60 25 T 120 15 T 180 25 T 240 5 T 300 20 L 300 40 L 0 40 Z" fill="none" stroke="#00aaff" strokeWidth="2"/>
                </svg>
              </div>

              <div style={{ marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#8892a8', marginBottom: '8px' }}>
                  <span>Probability Accuracy</span>
                  <span style={{ color: '#00aaff' }}>68%</span>
                </div>
                <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px' }}>
                  <div style={{ width: '68%', height: '100%', background: '#00aaff', borderRadius: '2px' }}></div>
                </div>
              </div>

              <button className="card-btn btn-poly" onClick={() => navigate('/polymarket')}>
                Launch Prediction AI
              </button>
            </div>
          </div>

          {/* IDX Portal */}
          <div className="portal-card card-idx">
            <div className="card-content">
              <div className="card-header">
                <div className="card-icon" style={{ borderColor: 'rgba(0,212,170,0.3)', color: '#00d4aa' }}>
                  ◈
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '12px', color: '#00d4aa' }}>Bulls</span>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '12px', color: '#ef4444' }}>Bears</span>
                </div>
              </div>
              <h2 className="card-title">IDX STOCK</h2>
              <div style={{ color: '#00d4aa', fontSize: '0.85rem', fontWeight: 600, marginTop: '4px', letterSpacing: '1px' }}>
                MARKET INTELLIGENCE & PORTFOLIO
              </div>
              
              <div className="card-visual">
                <div className="idx-chart">
                  <div className="idx-bar" style={{ height: '40%' }}></div>
                  <div className="idx-bar down" style={{ height: '20%' }}></div>
                  <div className="idx-bar" style={{ height: '50%' }}></div>
                  <div className="idx-bar" style={{ height: '30%' }}></div>
                  <div className="idx-bar down" style={{ height: '60%' }}></div>
                  <div className="idx-bar" style={{ height: '70%' }}></div>
                  <div className="idx-bar" style={{ height: '85%' }}></div>
                  <div className="idx-bar" style={{ height: '65%' }}></div>
                </div>
              </div>

              <div style={{ marginBottom: '1.5rem', display: 'flex', gap: '1rem', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem' }}>BBRI</span>
                  <span style={{ color: '#00d4aa', fontSize: '0.9rem', fontWeight: 600 }}>+1.8%</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem' }}>AMMN</span>
                  <span style={{ color: '#00d4aa', fontSize: '0.9rem', fontWeight: 600 }}>+2.1%</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ color: '#8892a8', fontSize: '0.8rem' }}>BREN</span>
                  <span style={{ color: '#ef4444', fontSize: '0.9rem', fontWeight: 600 }}>-0.5%</span>
                </div>
              </div>

              <button className="card-btn btn-idx" onClick={() => navigate('/idx')}>
                Explore Stock Analysis
              </button>
            </div>
          </div>

        </div>

        <div className={`footer-features ${isLoaded ? 'animate-fade-in delay-3' : ''}`}>
          <div className="feature-item">
            <span style={{ color: '#00d4aa' }}>✓</span> Personal AI Advisor
          </div>
          <div className="feature-item">
            <span style={{ color: '#00d4aa' }}>✓</span> Real-Time PnL Tracker
          </div>
          <div className="feature-item">
            <span style={{ color: '#00d4aa' }}>✓</span> Institutional Signals
          </div>
        </div>
      </main>
    </div>
  );
};

export default Home;

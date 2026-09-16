/**
 * AegisWatch Terminal HUD Client Application.
 * Connects to high-frequency WebSocket event bus, renders real-time LOB depth,
 * microstructure telemetry, live alerts, and manages regulatory audit dossiers.
 */

(function () {
  'use strict';

  // DOM Elements
  const headerMidPrice = document.getElementById('header-mid-price');
  const headerSpread = document.getElementById('header-spread');
  const telemetryLatency = document.getElementById('telemetry-latency');
  const telemetryTicks = document.getElementById('telemetry-ticks');
  const headerThreatBar = document.getElementById('header-threat-bar');
  const headerThreatVal = document.getElementById('header-threat-val');
  const btnReset = document.getElementById('btn-reset');

  // Microstructure DOM
  const valOfi = document.getElementById('val-ofi');
  const barOfi = document.getElementById('bar-ofi');
  const valCtr = document.getElementById('val-ctr');
  const barCtr = document.getElementById('bar-ctr');
  const valFlashing = document.getElementById('val-flashing');
  const barFlashing = document.getElementById('bar-flashing');
  const valVpin = document.getElementById('val-vpin');
  const barVpin = document.getElementById('bar-vpin');
  const valTradeVel = document.getElementById('val-trade-vel');
  const valCancelVel = document.getElementById('val-cancel-vel');
  const valDepthImb = document.getElementById('val-depth-imb');
  const valMicroprice = document.getElementById('val-microprice');
  const attrBarsList = document.getElementById('attr-bars-list');

  // Order Book DOM
  const asksLadder = document.getElementById('asks-ladder');
  const bidsLadder = document.getElementById('bids-ladder');
  const bannerMid = document.getElementById('banner-mid');
  const bannerSpread = document.getElementById('banner-spread');
  const bannerMicro = document.getElementById('banner-micro');
  const tradesTbody = document.getElementById('trades-tbody');

  // Alerts DOM
  const alertsStream = document.getElementById('alerts-stream');
  const emptyAlertsState = document.getElementById('empty-alerts-state');
  const badgeAlertCount = document.getElementById('badge-alert-count');

  // Modal DOM
  const dossierModal = document.getElementById('dossier-modal');
  const modalCaseNo = document.getElementById('modal-case-no');
  const modalBodyContent = document.getElementById('modal-body-content');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnCopyJson = document.getElementById('btn-copy-json');

  let currentDossierJson = null;
  let activeAlerts = new Map();
  let socket = null;
  let reconnectTimer = null;

  // Initialize WebSocket Connection
  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/stream`;

    socket = new WebSocket(wsUrl);

    socket.onopen = function () {
      console.log('[AegisWatch] WebSocket connection established.');
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
    };

    socket.onmessage = function (event) {
      try {
        const packet = JSON.parse(event.data);
        if (packet.type === 'MARKET_TICK') {
          handleMarketTick(packet);
        }
      } catch (err) {
        console.error('[AegisWatch] Error parsing tick:', err);
      }
    };

    socket.onclose = function () {
      console.warn('[AegisWatch] WebSocket closed. Reconnecting in 1.5s...');
      if (!reconnectTimer) {
        reconnectTimer = setInterval(initWebSocket, 1500);
      }
    };

    socket.onerror = function (err) {
      console.error('[AegisWatch] WebSocket error:', err);
      socket.close();
    };
  }

  // Handle incoming market tick packet
  function handleMarketTick(packet) {
    const mid = packet.mid_price || 180.00;
    const spread = packet.spread || 0.01;
    const micro = packet.microprice || mid;
    const features = packet.features || {};
    const surv = packet.surveillance || {};
    const stats = packet.system_stats || {};

    // 1. Header Updates
    headerMidPrice.textContent = `$${mid.toFixed(2)}`;
    headerSpread.textContent = `Spread: $${spread.toFixed(2)}`;
    bannerMid.textContent = `$${mid.toFixed(2)}`;
    bannerSpread.textContent = `$${spread.toFixed(2)}`;
    bannerMicro.textContent = `$${micro.toFixed(3)}`;

    if (stats.median_latency_ms !== undefined) {
      telemetryLatency.textContent = `${stats.median_latency_ms.toFixed(2)} ms`;
    }
    if (stats.total_evaluated_ticks !== undefined) {
      telemetryTicks.textContent = `${stats.total_evaluated_ticks} ticks`;
    }

    // Threat Score
    const threatScore = surv.anomaly_score !== undefined ? surv.anomaly_score : 0.15;
    const threatPct = Math.round(threatScore * 100);
    headerThreatVal.textContent = `${threatPct}%`;
    headerThreatBar.style.width = `${threatPct}%`;

    // 2. Microstructure Updates
    // OFI (-1.0 to 1.0)
    const ofi = features.ofi !== undefined ? features.ofi : 0.0;
    valOfi.textContent = ofi > 0 ? `+${ofi.toFixed(2)}` : ofi.toFixed(2);
    if (ofi >= 0) {
      barOfi.className = 'ofi-bar';
      barOfi.style.left = '50%';
      barOfi.style.width = `${Math.min(50, ofi * 50)}%`;
    } else {
      barOfi.className = 'ofi-bar negative';
      const w = Math.min(50, Math.abs(ofi) * 50);
      barOfi.style.left = `${50 - w}%`;
      barOfi.style.width = `${w}%`;
    }

    // CTR
    const ctr = features.ctr !== undefined ? features.ctr : 0.0;
    valCtr.textContent = `${ctr.toFixed(1)}x`;
    const ctrWidth = Math.min(100, (ctr / 20.0) * 100);
    barCtr.style.width = `${ctrWidth}%`;
    if (ctr > 15.0) {
      barCtr.className = 'progress-fill danger-fill';
      valCtr.className = 'metric-num danger-text';
    } else if (ctr > 5.0) {
      barCtr.className = 'progress-fill warning-fill';
      valCtr.className = 'metric-num warning-text';
    } else {
      barCtr.className = 'progress-fill';
      valCtr.className = 'metric-num';
    }

    // Flashing (< 50ms)
    const flashing = features.flashing_ratio !== undefined ? features.flashing_ratio : 0.0;
    const flashingPct = Math.round(flashing * 100);
    valFlashing.textContent = `${flashingPct}%`;
    barFlashing.style.width = `${Math.min(100, flashingPct * 2)}%`;

    // VPIN Toxicity
    const vpin = features.vpin !== undefined ? features.vpin : 0.18;
    valVpin.textContent = vpin.toFixed(2);
    barVpin.style.width = `${Math.min(100, vpin * 100)}%`;

    // Velocities & Skew
    valTradeVel.textContent = `${Math.round(features.trade_velocity || 0)} /s`;
    valCancelVel.textContent = `${Math.round(features.cancel_velocity || 0)} /s`;
    const depthImb = features.depth_imbalance || 0.0;
    valDepthImb.textContent = `${(depthImb * 100).toFixed(1)}%`;
    valMicroprice.textContent = `$${micro.toFixed(2)}`;

    // Attributions (SHAP)
    if (surv.attributions) {
      renderAttributionBars(surv.attributions);
    }

    // 3. Order Book Render (L2 Depth)
    if (packet.depth) {
      renderOrderBook(packet.depth);
    }

    // 4. Time & Sales (Trades)
    if (packet.recent_trades) {
      renderTradesTape(packet.recent_trades);
    }

    // 5. Surveillance Alerts
    if (surv.new_alerts && surv.new_alerts.length > 0) {
      surv.new_alerts.forEach((alert) => addAlertToConsole(alert));
    }
  }

  // Render Factor Attribution Breakdown
  function renderAttributionBars(attributions) {
    const sorted = Object.entries(attributions).sort((a, b) => b[1] - a[1]).slice(0, 4);
    attrBarsList.innerHTML = sorted
      .map(([factor, score]) => {
        const pct = Math.round(score * 100);
        return `
          <div class="attr-item">
            <span class="attr-name" title="${factor}">${factor}</span>
            <div class="attr-track"><div class="attr-fill" style="width: ${pct}%;"></div></div>
            <span class="attr-pct">${pct}%</span>
          </div>
        `;
      })
      .join('');
  }

  // Render L2 Order Book Ladder
  function renderOrderBook(depth) {
    const bids = depth.bids || [];
    const asks = depth.asks || [];

    // Calculate cumulative depth
    let cumAsk = 0;
    const askRows = asks.map(([price, size]) => {
      cumAsk += size;
      return { price, size, cum: cumAsk };
    });

    let cumBid = 0;
    const bidRows = bids.map(([price, size]) => {
      cumBid += size;
      return { price, size, cum: cumBid };
    });

    const maxCum = Math.max(cumAsk, cumBid, 1);

    // Asks: displayed reversed so best ask (lowest price) is closest to spread banner
    const reversedAsks = [...askRows].reverse();
    asksLadder.innerHTML = reversedAsks
      .map((row) => {
        const depthPct = Math.round((row.cum / maxCum) * 100);
        return `
          <div class="lob-row ask-row">
            <div class="depth-bg" style="width: ${depthPct}%;"></div>
            <span class="price">$${row.price.toFixed(2)}</span>
            <span class="size">${row.size.toLocaleString()}</span>
            <span class="cum">${row.cum.toLocaleString()}</span>
          </div>
        `;
      })
      .join('');

    // Bids: highest bid closest to spread banner
    bidsLadder.innerHTML = bidRows
      .map((row) => {
        const depthPct = Math.round((row.cum / maxCum) * 100);
        return `
          <div class="lob-row bid-row">
            <div class="depth-bg" style="width: ${depthPct}%;"></div>
            <span class="price">$${row.price.toFixed(2)}</span>
            <span class="size">${row.size.toLocaleString()}</span>
            <span class="cum">${row.cum.toLocaleString()}</span>
          </div>
        `;
      })
      .join('');
  }

  // Render Recent Trades Tape
  function renderTradesTape(trades) {
    tradesTbody.innerHTML = trades
      .slice(-8)
      .reverse()
      .map((t) => {
        const isBuy = t.aggressor_side === 'BUY';
        const rowClass = isBuy ? 'trade-buy' : 'trade-sell';
        return `
          <tr class="${rowClass}">
            <td>${t.time_iso}</td>
            <td>${t.trade_id.substring(0, 10)}</td>
            <td class="trade-price">$${t.price.toFixed(2)}</td>
            <td>${t.quantity.toLocaleString()}</td>
            <td>${t.aggressor_side}</td>
          </tr>
        `;
      })
      .join('');
  }

  // Add Alert to Watchdog Console
  function addAlertToConsole(alert) {
    if (activeAlerts.has(alert.alert_id)) return;
    activeAlerts.set(alert.alert_id, alert);

    if (emptyAlertsState) {
      emptyAlertsState.style.display = 'none';
    }

    badgeAlertCount.textContent = `${activeAlerts.size} ALERTS`;

    const alertCard = document.createElement('div');
    alertCard.className = `alert-card severity-${alert.severity}`;
    alertCard.dataset.alertId = alert.alert_id;

    const timeStr = alert.timestamp_iso || new Date().toISOString().substring(11, 19);

    alertCard.innerHTML = `
      <div class="alert-card-header">
        <span class="alert-type-badge">${alert.abuse_type}</span>
        <span class="alert-time">${timeStr}</span>
      </div>
      <div class="alert-desc">${alert.description}</div>
      <div class="alert-footer-meta">
        <span class="alert-trader">Participant: ${alert.target_trader_id || 'UNKNOWN'}</span>
        <button class="btn-inspect-dossier" data-alert-id="${alert.alert_id}">Inspect Dossier &rarr;</button>
      </div>
    `;

    alertCard.addEventListener('click', function (e) {
      inspectDossier(alert.alert_id);
    });

    alertsStream.insertBefore(alertCard, alertsStream.firstChild);
  }

  // Inspect Regulatory Dossier Modal
  async function inspectDossier(alertId) {
    try {
      const res = await fetch(`/api/dossier/${alertId}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const dossier = await res.json();
      currentDossierJson = dossier;
      renderDossierModal(dossier);
      dossierModal.style.display = 'flex';
    } catch (err) {
      console.error('[AegisWatch] Error fetching dossier:', err);
      alert(`Could not fetch evidentiary dossier for ${alertId}`);
    }
  }

  // Render Dossier Modal Content
  function renderDossierModal(dossier) {
    modalCaseNo.textContent = `${dossier.case_number} · ${dossier.alert_summary.abuse_type}`;

    const summary = dossier.alert_summary;
    const rules = dossier.statutory_violations || [];
    const attributions = dossier.forensic_attribution || {};
    const action = dossier.enforcement_recommendation || {};
    const evidence = dossier.evidentiary_data || {};

    modalBodyContent.innerHTML = `
      <!-- SUMMARY SECTION -->
      <div class="dossier-section">
        <div class="dossier-sec-title"><span>🏛️</span> INCIDENT JURISDICTION & VENUE</div>
        <div class="dossier-meta-grid">
          <div class="dossier-meta-row"><span>Exchange Matching Engine:</span><strong>${dossier.exchange_venue}</strong></div>
          <div class="dossier-meta-row"><span>Regulatory Authority:</span><strong>${dossier.jurisdiction}</strong></div>
          <div class="dossier-meta-row"><span>Timestamp (UTC):</span><strong>${dossier.generated_at}</strong></div>
          <div class="dossier-meta-row"><span>Subject Participant:</span><strong style="color:var(--color-cyan);">${summary.target_participant}</strong></div>
        </div>
      </div>

      <!-- STATUTORY VIOLATIONS -->
      <div class="dossier-section">
        <div class="dossier-sec-title"><span>⚖️</span> STATUTORY RULE VIOLATIONS</div>
        <ul class="dossier-rules-list">
          ${rules.map((r) => `<li>• ${r}</li>`).join('')}
        </ul>
      </div>

      <!-- FORENSIC FACTOR ATTRIBUTION -->
      <div class="dossier-section">
        <div class="dossier-sec-title"><span>📊</span> QUANTITATIVE MICROSTRUCTURE ATTRIBUTION (SHAP DECOMPOSITION)</div>
        <div class="dossier-meta-grid">
          ${Object.entries(attributions)
            .map(([factor, pct]) => `<div class="dossier-meta-row"><span>${factor}:</span><strong>${pct}</strong></div>`)
            .join('')}
        </div>
      </div>

      <!-- RECOMMENDED ENFORCEMENT ACTION -->
      <div class="dossier-action-box">
        <div class="dossier-action-tier">${action.tier || 'ENFORCEMENT DISCIPLINARY REFERRAL'}</div>
        <p style="margin-bottom:6px; color:#fff;">${action.action || ''}</p>
        <small style="color:var(--text-muted);">${action.statutory_remedy || ''}</small>
      </div>
    `;
  }

  // Attack Injection Handlers
  document.querySelectorAll('.btn-attack').forEach((btn) => {
    btn.addEventListener('click', async function () {
      const attackType = this.dataset.attack;
      const originalText = this.querySelector('strong').textContent;
      this.querySelector('strong').textContent = 'Injecting Flow...';
      this.style.opacity = '0.7';

      try {
        const res = await fetch('/api/attack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: attackType, params: {} }),
        });
        const data = await res.json();
        console.log('[AegisWatch] Attack response:', data);
      } catch (err) {
        console.error('[AegisWatch] Attack failed:', err);
      } finally {
        setTimeout(() => {
          this.querySelector('strong').textContent = originalText;
          this.style.opacity = '1';
        }, 500);
      }
    });
  });

  // Reset Book Button Handler
  btnReset.addEventListener('click', async function () {
    try {
      await fetch('/api/reset', { method: 'POST' });
      activeAlerts.clear();
      badgeAlertCount.textContent = '0 ALERTS';
      alertsStream.innerHTML = '';
      if (emptyAlertsState) {
        alertsStream.appendChild(emptyAlertsState);
        emptyAlertsState.style.display = 'block';
      }
    } catch (err) {
      console.error('[AegisWatch] Reset failed:', err);
    }
  });

  // Modal Close & Copy Handlers
  btnCloseModal.addEventListener('click', () => {
    dossierModal.style.display = 'none';
  });

  dossierModal.addEventListener('click', (e) => {
    if (e.target === dossierModal) {
      dossierModal.style.display = 'none';
    }
  });

  btnCopyJson.addEventListener('click', () => {
    if (currentDossierJson) {
      navigator.clipboard.writeText(JSON.stringify(currentDossierJson, null, 2));
      btnCopyJson.textContent = 'Copied to Clipboard!';
      setTimeout(() => {
        btnCopyJson.textContent = 'Copy JSON Audit Record';
      }, 1500);
    }
  });

  // Start WebSocket client on page load
  window.addEventListener('DOMContentLoaded', initWebSocket);
})();

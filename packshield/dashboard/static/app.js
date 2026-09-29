// ---------- Custom cursor ----------
const cursor = document.getElementById('custom-cursor');
document.addEventListener('mousemove', e => {
  cursor.style.left = e.clientX + 'px';
  cursor.style.top = e.clientY + 'px';
});
document.addEventListener('mouseover', e => {
  cursor.classList.toggle('hover', !!e.target.closest('a, button, tr, input, .graph-node'));
});

// ---------- Particle background ----------
const canvas = document.getElementById('particle-bg');
const ctx = canvas.getContext('2d');
let particles = [];
const mouse = { x: -1000, y: -1000 };

function resizeCanvas() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

document.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });

for (let i = 0; i < 60; i++) {
  particles.push({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
  });
}

function animateParticles() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  particles.forEach(p => {
    p.x += p.vx; p.y += p.vy;
    if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
    if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

    const dx = mouse.x - p.x, dy = mouse.y - p.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 150) { p.x -= dx * 0.01; p.y -= dy * 0.01; }

    ctx.beginPath();
    ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(88,166,255,0.5)';
    ctx.fill();
  });

  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x, dy = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 100) {
        ctx.beginPath();
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.strokeStyle = `rgba(88,166,255,${0.1 * (1 - dist / 100)})`;
        ctx.stroke();
      }
    }
  }
  requestAnimationFrame(animateParticles);
}
animateParticles();

// ---------- Router ----------
const routes = {
  overview: renderOverview,
  live: renderLive,
  graph: renderGraph,
  threats: renderThreats,
  forensics: renderForensics,
  history: renderHistory,
  settings: renderSettings,
};

let activePollInterval = null;

function stopPolling() {
  if (activePollInterval) {
    clearInterval(activePollInterval);
    activePollInterval = null;
  }
}

function navigate() {
  stopPolling();
  const hash = window.location.hash.replace('#/', '') || 'overview';
  const parts = hash.split('/');
  const routeName = parts[0];
  document.querySelectorAll('.nav-links a').forEach(a => {
    a.classList.toggle('active', a.dataset.route === routeName);
  });
  const renderFn = routes[routeName] || renderOverview;
  renderFn(parts.slice(1));
}
window.addEventListener('hashchange', navigate);

function placeholder(title, note) {
  return `<h1>${title}</h1><div class="subtitle">${note}</div>
    <div class="placeholder-panel">This view is planned but not yet built. No fabricated data is shown here.</div>`;
}

// ---------- Shim status (sidebar) ----------
async function loadShimStatus() {
  try {
    const res = await fetch('/api/shim_status');
    const data = await res.json();
    document.getElementById('shim-indicator').classList.toggle('armed', data.armed);
    document.getElementById('shim-label').textContent = data.armed ? 'Shim armed' : 'Shim not installed';
  } catch (e) {
    document.getElementById('shim-label').textContent = 'Status unknown';
  }
}

// ---------- Overview page ----------
async function renderOverview() {
  const page = document.getElementById('page');
  page.innerHTML = '<h1>Overview</h1><div class="subtitle">Loading real stats from history.jsonl...</div>';
  const res = await fetch('/api/stats');
  const stats = await res.json();

  if (!stats.total_scans) {
    page.innerHTML = placeholder('Overview', 'No scans recorded yet — run `npm install <pkg>` or `pip install <pkg>` with the shim armed.');
    return;
  }

  page.innerHTML = `
    <h1>Overview</h1>
    <div class="subtitle">Real aggregate stats from ${stats.total_scans} recorded scan(s).</div>
    <div class="panel">
      <h2>Verdict Breakdown</h2>
      <div class="stat-grid">
        <div class="stat-card"><div class="value">${stats.total_scans}</div><div class="label">Total Scans</div></div>
        <div class="stat-card"><div class="value" style="color:var(--allow)">${stats.verdict_counts.ALLOW || 0}</div><div class="label">Allow</div></div>
        <div class="stat-card"><div class="value" style="color:var(--warn)">${stats.verdict_counts.WARN || 0}</div><div class="label">Warn</div></div>
        <div class="stat-card"><div class="value" style="color:var(--block)">${stats.verdict_counts.BLOCK || 0}</div><div class="label">Block</div></div>
      </div>
    </div>
    <div class="panel">
      <h2>Most Frequently Flagged Packages</h2>
      <table><thead><tr><th>Package</th><th>Times flagged as worst offender</th></tr></thead><tbody>
        ${stats.top_flagged_packages.map(([name, count]) => `<tr><td>${name}</td><td>${count}</td></tr>`).join('')}
      </tbody></table>
    </div>
    <div class="panel">
      <h2>Likely Attack Pattern <span class="sim-badge">inferred from worst signal, not a real classifier</span></h2>
      <table><thead><tr><th>Pattern</th><th>Count</th></tr></thead><tbody>
        ${Object.entries(stats.likely_attack_type_counts).map(([t, c]) => `<tr><td>${t}</td><td>${c}</td></tr>`).join('')}
      </tbody></table>
    </div>
  `;
}

// ---------- History page ----------
let historyEntries = [];
async function renderHistory() {
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>History</h1>
    <div class="subtitle">Every recorded scan, most recent first.</div>
    <div class="panel">
      <table id="history-table">
        <thead><tr><th>Package</th><th>PM</th><th>Verdict</th><th>Final Score</th><th>Stage-1</th><th>S2</th><th>Worst Node</th><th>Overridden</th><th>Timestamp</th><th></th></tr></thead>
        <tbody id="history-body"></tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Dependency Tree — select a scan above</h2>
      <div id="tree-detail" class="node-list">Select a row above to see its per-package signal breakdown.</div>
    </div>
  `;

  const res = await fetch('/api/history');
  const data = await res.json();
  historyEntries = data.entries;
  const tbody = document.getElementById('history-body');
  tbody.innerHTML = historyEntries.map((entry, idx) => `
    <tr>
      <td onclick="showTreeDetail(${idx})">${entry.package}</td><td>${entry.pm}</td>
      <td><span class="tag tag-${entry.verdict}">${entry.verdict}</span></td>
      <td>${entry.final_score}</td><td>${entry.stage1_score}</td>
      <td>${entry.s2_score !== null ? entry.s2_score + ' <span class="fake-badge">fake</span>' : 'n/a'}</td>
      <td><a href="#/forensics/${entry.pm}/${(entry.worst_node || '').split('@')[0]}" style="color:var(--accent);">${entry.worst_node || '-'}</a></td>
      <td>${entry.overridden ? 'yes: ' + (entry.override_reason || '') : 'no'}</td>
      <td>${entry.timestamp || '-'}</td>
      <td>${entry.node_scores && entry.node_scores.length ? `<a href="#/live/replay/${idx}" style="color:var(--accent); font-size:11px;">Replay</a>` : ''}</td>
    </tr>
  `).join('');
}

function showTreeDetail(idx) {
  const entry = historyEntries[idx];
  const container = document.getElementById('tree-detail');
  if (!entry.node_scores || entry.node_scores.length === 0) {
    container.innerHTML = '<em>No per-node data recorded for this scan (older entry).</em>';
    return;
  }
  const sorted = [...entry.node_scores].sort((a, b) => Math.max(b.stage1_score, b.s2_fake_score) - Math.max(a.stage1_score, a.s2_fake_score));
  container.innerHTML = sorted.map(n => {
    const worst = Math.max(n.stage1_score, n.s2_fake_score);
    const cls = worst >= 7 ? 'high' : worst >= 4 ? 'mid' : '';
    return `<div class="node-row ${cls}"><a href="#/forensics/${entry.pm}/${n.name}" style="color:inherit; text-decoration:none; border-bottom:1px dotted var(--dim);">${n.name}@${n.version}</a> — S1: ${n.s1_score}, Stage-1: ${n.stage1_score}, S3: ${n.s3_score}, S2(fake): ${n.s2_fake_score}</div>`;
  }).join('');
}

// ---------- Dependency Graph page ----------
async function renderGraph() {
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>Dependency Graph</h1>
    <div class="subtitle">Interactive force-directed graph of a scan's resolved dependency tree.</div>
    <div class="panel" style="padding:12px 20px;">
      <label style="font-size:12px; color:var(--dim); margin-right:10px;">Scan:</label>
      <select id="graph-scan-select"></select>
      <span id="graph-note" class="sim-badge" style="margin-left:10px; display:none;"></span>
    </div>
    <div class="panel" style="padding:0; overflow:hidden;">
      <svg id="graph-svg" width="100%" height="560"></svg>
    </div>
    <div class="panel" id="graph-detail-panel" style="display:none;">
      <h2 id="graph-detail-title"></h2>
      <div id="graph-detail-body" class="node-list"></div>
    </div>
  `;

  const res = await fetch('/api/history');
  const data = await res.json();
  const scans = data.entries.filter(e => e.node_scores && e.node_scores.length > 0);

  if (scans.length === 0) {
    document.querySelector('#page .panel').outerHTML = '<div class="placeholder-panel">No scans with per-node data yet. Run a scan first (older history entries predate this field).</div>';
    return;
  }

  const select = document.getElementById('graph-scan-select');
  select.innerHTML = scans.map((s, i) => `<option value="${i}">${s.package} (${s.pm}) — ${s.verdict} — ${s.timestamp || 'no timestamp'}</option>`).join('');
  select.onchange = () => drawGraph(scans[select.value]);

  drawGraph(scans[0]);
}

function scoreColor(score) {
  if (score >= 7) return '#f85149';
  if (score >= 4) return '#d29922';
  return '#3fb950';
}

function drawGraph(scan) {
  const svgEl = document.getElementById('graph-svg');
  svgEl.innerHTML = '';
  const width = svgEl.clientWidth || 900;
  const height = 560;

  const noteEl = document.getElementById('graph-note');
  if (scan.pm === 'pip') {
    noteEl.style.display = 'inline';
    noteEl.textContent = 'pip: no edge data available — flat star layout (honest limitation, see PROJECT.md log)';
  } else {
    noteEl.style.display = 'inline';
    noteEl.textContent = 'edges reconstructed from npm install paths — hoisted packages link to root (deduplication makes true logical parent unrecoverable)';
  }

  const rootId = `${scan.package}@ROOT`;
  const nodes = [{ id: rootId, name: scan.package, version: '', isRoot: true, s1_score: 0, stage1_score: 0, s3_score: 0, s2_fake_score: 0, parent: null }];
  const nodeIndex = {};
  scan.node_scores.forEach(n => { nodeIndex[n.name] = `${n.name}@${n.version}`; });

  scan.node_scores.forEach(n => {
    const id = `${n.name}@${n.version}`;
    if (id === rootId) return;
    nodes.push({ id, name: n.name, version: n.version, isRoot: false, ...n });
  });

  const links = [];
  nodes.forEach(n => {
    if (n.isRoot) return;
    const parentId = n.parent && nodeIndex[n.parent] ? nodeIndex[n.parent] : rootId;
    if (parentId !== n.id) links.push({ source: parentId, target: n.id });
  });

  const svg = d3.select('#graph-svg').attr('viewBox', [0, 0, width, height]);
  const g = svg.append('g');

  svg.call(d3.zoom().scaleExtent([0.3, 4]).on('zoom', (event) => g.attr('transform', event.transform)));

  const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', 'rgba(88,166,255,0.25)')
    .attr('stroke-width', 1.2);

  const node = g.append('g')
    .selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('class', 'graph-node')
    .attr('r', d => d.isRoot ? 16 : 6 + Math.max(d.stage1_score, d.s2_fake_score))
    .attr('fill', d => d.isRoot ? '#58a6ff' : scoreColor(Math.max(d.stage1_score, d.s2_fake_score)))
    .attr('stroke', d => d.isRoot ? '#fff' : 'rgba(0,0,0,0.3)')
    .attr('stroke-width', d => d.isRoot ? 2 : 0.5)
    .style('cursor', 'none')
    .call(d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended))
    .on('click', (event, d) => showGraphDetail(d));

  node.append('title').text(d => `${d.name}${d.version ? '@' + d.version : ''}`);

  const labels = g.append('g')
    .selectAll('text')
    .data(nodes)
    .join('text')
    .text(d => d.name)
    .attr('font-size', 9)
    .attr('fill', '#8b949e')
    .attr('dx', 10)
    .attr('dy', 3)
    .style('pointer-events', 'none');

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(60))
    .force('charge', d3.forceManyBody().strength(-180))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(d => (d.isRoot ? 16 : 6 + Math.max(d.stage1_score, d.s2_fake_score)) + 4))
    .on('tick', ticked);

  function ticked() {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('cx', d => d.x).attr('cy', d => d.y);
    labels.attr('x', d => d.x).attr('y', d => d.y);
  }

  function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
  }
  function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
  function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null; d.fy = null;
  }
}

function showGraphDetail(d) {
  const panel = document.getElementById('graph-detail-panel');
  panel.style.display = 'block';
  document.getElementById('graph-detail-title').textContent = d.isRoot ? `${d.name} (install target)` : `${d.name}@${d.version}`;
  if (d.isRoot) {
    document.getElementById('graph-detail-body').innerHTML = '<em>Root install target — see the overall verdict in History for this scan.</em>';
    return;
  }
  document.getElementById('graph-detail-body').innerHTML = `
    <div class="node-row">S1 (name similarity): ${d.s1_score}</div>
    <div class="node-row">Stage-1 (S1+S3+S4): ${d.stage1_score}</div>
    <div class="node-row">S3 (update-diff): ${d.s3_score}</div>
    <div class="node-row">S2: ${d.s2_fake_score} <span class="fake-badge">fake stub</span></div>
    <div class="node-row">Parent in tree: ${d.parent || '(root, or hoisted/unrecoverable — see note above graph)'}</div>
  `;
}

// ---------- Live Scan page ----------
let pollCount = 0;
let pollInFlight = false;
let pollInFlightSince = 0;

function renderLive(pathParts) {
  if (pathParts && pathParts[0] === 'replay' && pathParts[1] !== undefined) {
    renderReplay(parseInt(pathParts[1]));
    return;
  }

  pollCount = 0;
  pollInFlight = false;
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>Live Scan</h1>
    <div class="subtitle">Polls /api/live_status about every 500ms. The CLI and this dashboard are separate processes, so some latency is inherent.</div>
    <div class="panel">
      <div id="live-body">Checking for an active scan...</div>
      <div id="poll-diag" style="font-size:10px; color:var(--dim); margin-top:10px; border-top:1px solid var(--border); padding-top:6px;">Starting...</div>
    </div>
    <div class="panel">
      <h2>Activity Log</h2>
      <div id="live-log" class="node-list" style="max-height:420px;"></div>
    </div>
  `;

  pollLiveStatus();
  activePollInterval = setInterval(pollLiveStatus, 500);
}

async function pollLiveStatus() {
  const body = document.getElementById('live-body');
  if (!body) { stopPolling(); return; }
  const logEl = document.getElementById('live-log');
  const diagEl = document.getElementById('poll-diag');

  if (pollInFlight) {
    const waited = ((Date.now() - pollInFlightSince) / 1000).toFixed(1);
    diagEl.textContent = `Poll #${pollCount} - previous request still pending after ${waited}s`;
    return;
  }

  pollInFlight = true;
  pollInFlightSince = Date.now();
  pollCount++;
  const t0 = performance.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 5000);

  try {
    const res = await fetch(`/api/live_status?t=${Date.now()}`, { cache: 'no-store', signal: ctrl.signal });
    const status = await res.json();
    const latency = Math.round(performance.now() - t0);
    const ageTxt = status.file_age_seconds !== undefined
      ? `status file last written ${status.file_age_seconds}s ago`
      : 'no status file yet';
    diagEl.style.color = 'var(--dim)';
    diagEl.textContent = `Poll #${pollCount} - HTTP ${res.status} in ${latency}ms - ${ageTxt}`;

    if (status._read_error) {
      diagEl.textContent += ` - transient read error, keeping previous view (${status._read_error})`;
      return;
    }

    if (!status.active && !status.stage) {
      body.innerHTML = '<em>No scan running. Start one with `npm install &lt;pkg&gt;` or `pip install &lt;pkg&gt;` in a terminal with the shim armed.</em>';
      logEl.innerHTML = '';
      return;
    }

    const pct = status.total_packages ? Math.round((status.completed_packages / status.total_packages) * 100) : 0;

    if (status.active) {
      const unit = status.stage === 'resolving' ? 'integrity hashes fetched' : 'packages scored';
      const stuck = status.file_age_seconds > 90
        ? `<div style="color:var(--warn); font-size:11px; margin-top:8px;">No update for ${Math.round(status.file_age_seconds)}s - the scan may be on a slow package, or the CLI process may have died.</div>`
        : '';
      body.innerHTML = `
        <div style="margin-bottom:12px;"><strong>${status.package}</strong> (${status.pm}) - stage: ${status.stage}</div>
        <div style="background:rgba(255,255,255,0.05); border-radius:6px; height:10px; overflow:hidden;">
          <div style="background:var(--accent); height:100%; width:${pct}%; transition: width 0.3s; box-shadow: 0 0 8px var(--accent-glow);"></div>
        </div>
        <div style="font-size:11px; color:var(--dim); margin-top:6px;">${status.completed_packages || 0} / ${status.total_packages || '?'} ${unit} - currently: ${status.current_package || '...'}</div>
        ${stuck}
      `;
    } else {
      body.innerHTML = `
        <div>Last scan: <strong>${status.package || ''}</strong> - <span class="tag tag-${status.verdict}">${status.verdict}</span>
        (final score ${status.final_score}, took ${status.elapsed_seconds ?? '?'}s)</div>
      `;
    }

    const wasNearBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    logEl.innerHTML = (status.log || []).map(l => `<div class="node-row">${l}</div>`).join('');
    if (wasNearBottom) logEl.scrollTop = logEl.scrollHeight;
  } catch (err) {
    const msg = err.name === 'AbortError' ? 'request timed out after 5s - dashboard server not responding' : err.message;
    diagEl.style.color = 'var(--block)';
    diagEl.textContent = `Poll #${pollCount} - ERROR: ${msg}`;
  } finally {
    clearTimeout(timer);
    pollInFlight = false;
  }
}

// ---------- Scan Replay (client-side animation over stored data) ----------
async function renderReplay(idx) {
  const page = document.getElementById('page');
  if (historyEntries.length === 0) {
    const res = await fetch('/api/history');
    historyEntries = (await res.json()).entries;
  }
  const entry = historyEntries[idx];
  if (!entry || !entry.node_scores) {
    page.innerHTML = placeholder('Scan Replay', 'That scan has no per-node data to replay (older entry).');
    return;
  }

  page.innerHTML = `
    <h1>Scan Replay <span class="sim-badge">replaying stored data, not a live scan</span></h1>
    <div class="subtitle">${entry.package} (${entry.pm}) — recorded ${entry.timestamp || 'unknown time'}</div>
    <div class="panel">
      <div id="replay-body">Starting replay...</div>
      <div style="background:rgba(255,255,255,0.05); border-radius:6px; height:10px; overflow:hidden; margin-top:12px;">
        <div id="replay-bar" style="background:var(--accent); height:100%; width:0%; transition: width 0.2s;"></div>
      </div>
    </div>
    <div class="panel">
      <h2>Replay Log</h2>
      <div id="replay-log" class="node-list"></div>
    </div>
    <button onclick="window.location.hash='#/history'">Back to History</button>
  `;

  const logEl = document.getElementById('replay-log');
  const bodyEl = document.getElementById('replay-body');
  const barEl = document.getElementById('replay-bar');
  const nodes = entry.node_scores;
  let i = 0;

  bodyEl.innerHTML = `Resolving dependency tree for <strong>${entry.package}</strong>...`;
  await sleep(500);

  logEl.innerHTML = '';
  for (i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    bodyEl.innerHTML = `Stage 1 (S1+S3+S4) scoring: <strong>${n.name}@${n.version}</strong>`;
    barEl.style.width = `${Math.round(((i + 1) / nodes.length) * 60)}%`;
    const worst = Math.max(n.stage1_score, n.s3_score);
    const cls = worst >= 7 ? 'high' : worst >= 4 ? 'mid' : '';
    logEl.innerHTML += `<div class="node-row ${cls}">${n.name}@${n.version} — Stage-1: ${n.stage1_score}, S3: ${n.s3_score}</div>`;
    logEl.scrollTop = logEl.scrollHeight;
    await sleep(40);
  }

  const escalated = entry.s2_score !== null;
  bodyEl.innerHTML = `Stage-1 tree-max: ${entry.stage1_score} — ${escalated ? 'ESCALATING to S2...' : 'below threshold, skipping S2'}`;
  barEl.style.width = '75%';
  await sleep(600);

  if (escalated) {
    for (i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      bodyEl.innerHTML = `S2 (fake stub) scoring: <strong>${n.name}@${n.version}</strong>`;
      barEl.style.width = `${75 + Math.round(((i + 1) / nodes.length) * 20)}%`;
      const cls = n.s2_fake_score >= 7 ? 'high' : n.s2_fake_score >= 4 ? 'mid' : '';
      logEl.innerHTML += `<div class="node-row ${cls}">${n.name}@${n.version} — S2(fake): ${n.s2_fake_score}</div>`;
      logEl.scrollTop = logEl.scrollHeight;
      await sleep(30);
    }
  }

  barEl.style.width = '100%';
  bodyEl.innerHTML = `<strong>Final verdict:</strong> <span class="tag tag-${entry.verdict}">${entry.verdict}</span> (final score ${entry.final_score}, worst offender: ${entry.worst_node})`;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ---------- Package Forensics page ----------
async function renderForensics(pathParts) {
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>Package Forensics</h1>
    <div class="subtitle">Look up a package's real version history and every scan that mentioned it.</div>
    <div class="panel" style="padding:12px 20px;">
      <select id="forensics-pm" style="margin-right:8px;">
        <option value="npm">npm</option>
        <option value="pip">pip</option>
      </select>
      <input id="forensics-name" type="text" placeholder="package name, e.g. etag" style="background:var(--bg-panel); border:1px solid var(--border); color:var(--text); padding:6px 10px; border-radius:6px; font-family:inherit; font-size:12px; width:220px;">
      <button id="forensics-search">Look up</button>
    </div>
    <div id="forensics-results"></div>
  `;

  const pmSelect = document.getElementById('forensics-pm');
  const nameInput = document.getElementById('forensics-name');
  document.getElementById('forensics-search').onclick = () => lookupPackage(pmSelect.value, nameInput.value.trim());
  nameInput.addEventListener('keydown', e => { if (e.key === 'Enter') lookupPackage(pmSelect.value, nameInput.value.trim()); });

  if (pathParts && pathParts.length >= 2 && pathParts[1]) {
    pmSelect.value = pathParts[0];
    nameInput.value = pathParts[1];
    lookupPackage(pathParts[0], pathParts[1]);
  }
}

async function lookupPackage(pm, name) {
  const results = document.getElementById('forensics-results');
  if (!name) {
    results.innerHTML = '<div class="placeholder-panel">Enter a package name above.</div>';
    return;
  }
  results.innerHTML = '<div class="placeholder-panel">Looking up...</div>';

  const res = await fetch(`/api/package/${encodeURIComponent(pm)}/${encodeURIComponent(name)}`);
  const data = await res.json();

  if ((!data.version_history || data.version_history.length === 0) && (!data.scan_mentions || data.scan_mentions.length === 0)) {
    results.innerHTML = `<div class="placeholder-panel">No record of ${pm}/${name} yet. It hasn't shown up in any scan's S3 diff or dependency tree so far.</div>`;
    return;
  }

  const latestMention = data.scan_mentions.length
    ? data.scan_mentions[data.scan_mentions.length - 1]
    : null;

  results.innerHTML = `
    <div class="panel">
      <h2>${pm} / ${name}</h2>
      ${latestMention ? `
        <div class="node-list">
          <div class="node-row">Last seen in a scan of: <strong>${latestMention.scan_package}</strong> (${latestMention.timestamp || 'no timestamp'})</div>
          <div class="node-row">That scan's overall verdict: <span class="tag tag-${latestMention.scan_verdict}">${latestMention.scan_verdict}</span></div>
          <div class="node-row">This package's own signals there — S1: ${latestMention.node_scores.s1_score}, Stage-1: ${latestMention.node_scores.stage1_score}, S3: ${latestMention.node_scores.s3_score}, S2(fake): ${latestMention.node_scores.s2_fake_score}</div>
        </div>
      ` : '<div class="placeholder-panel">Never appeared as a scored node in any recorded scan — version history below comes only from S3 diffs run directly against it.</div>'}
    </div>

    <div class="panel">
      <h2>Version History <span class="sim-badge">from S3's stored diffs, most recent first — not a full registry changelog</span></h2>
      ${data.version_history.length === 0 ? '<div class="placeholder-panel">No S3 diff history recorded for this package yet.</div>' : `
        <table>
          <thead><tr><th>Version</th><th>Recorded</th><th>S3 diff score</th><th>Reasons</th></tr></thead>
          <tbody>
            ${[...data.version_history].reverse().map(v => `
              <tr>
                <td>${v.version}</td>
                <td>${v.stored_at || '-'}</td>
                <td>${v.diff_score !== null && v.diff_score !== undefined ? v.diff_score : '-'}</td>
                <td>${(v.diff_reasons || []).join('; ') || '-'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `}
    </div>

    <div class="panel">
      <h2>Every Scan That Included This Package</h2>
      ${data.scan_mentions.length === 0 ? '<div class="placeholder-panel">No scans on record included this package.</div>' : `
        <table>
          <thead><tr><th>Scan (install target)</th><th>Verdict</th><th>Timestamp</th><th>S1</th><th>Stage-1</th><th>S3</th><th>S2(fake)</th></tr></thead>
          <tbody>
            ${[...data.scan_mentions].reverse().map(m => `
              <tr>
                <td>${m.scan_package}</td>
                <td><span class="tag tag-${m.scan_verdict}">${m.scan_verdict}</span></td>
                <td>${m.timestamp || '-'}</td>
                <td>${m.node_scores.s1_score}</td>
                <td>${m.node_scores.stage1_score}</td>
                <td>${m.node_scores.s3_score}</td>
                <td>${m.node_scores.s2_fake_score}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `}
    </div>
  `;
}

// ---------- Threats page ----------
async function renderThreats() {
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>Threats</h1>
    <div class="subtitle">T1-T5 attack-type breakdown, inferred from which signal produced each scan's worst score. <span class="sim-badge">not a real per-scan classifier</span></div>
    <div id="threats-content"><div class="placeholder-panel">Loading...</div></div>
  `;

  const res = await fetch('/api/threats');
  const data = await res.json();
  const content = document.getElementById('threats-content');

  const order = ['T1', 'T2', 'T3', 'T1/T4 (mixed S1+S4)', 'UNKNOWN'];
  const total = Object.values(data.buckets).reduce((sum, arr) => sum + arr.length, 0);

  if (total === 0) {
    content.innerHTML = '<div class="placeholder-panel">No scans recorded yet.</div>';
    return;
  }

  content.innerHTML = `
    <div class="panel">
      <h2>Attack Radar</h2>
      <svg id="threat-radar" width="100%" height="320"></svg>
    </div>
    <div class="panel">
      <h2>Threat Matrix</h2>
      ${order.map(key => `
        <div style="margin-bottom:18px;">
          <div style="display:flex; justify-content:space-between; align-items:center; cursor:none;" onclick="toggleThreatBucket('${key.replace(/'/g, "\\'")}')">
            <strong>${key}${key === 'UNKNOWN' ? '' : ''} <span style="color:var(--dim); font-weight:normal; font-size:12px;">— ${data.definitions[key.startsWith('T1/T4') ? 'T4' : key] || 'Not classifiable from current signals'}</span></strong>
            <span class="tag" style="background:rgba(88,166,255,0.12); color:var(--accent);">${data.buckets[key].length} scan(s)</span>
          </div>
          <div id="bucket-${cssSafe(key)}" class="node-list" style="display:none; margin-top:8px;">
            ${data.buckets[key].length === 0 ? '<em>No scans in this category.</em>' : data.buckets[key].map(s => `
              <div class="node-row"><a href="#/forensics/${s.pm}/${(s.worst_node || '').split('@')[0]}" style="color:inherit;">${s.package}</a> — <span class="tag tag-${s.verdict}">${s.verdict}</span> (score ${s.final_score}, ${s.timestamp || 'no timestamp'})</div>
            `).join('')}
          </div>
        </div>
      `).join('')}
      <div class="placeholder-panel" style="margin-top:10px;">
        T5 (dependency confusion) has no row above because it is explicitly out of scope per PROJECT.md Sec 2 — nothing in this tool attempts to detect it, so there is nothing to count.
      </div>
    </div>
  `;

  drawThreatRadar(data.buckets, order);
}

function cssSafe(key) {
  return key.replace(/[^a-zA-Z0-9]/g, '');
}

function toggleThreatBucket(key) {
  const el = document.getElementById(`bucket-${cssSafe(key)}`);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function drawThreatRadar(buckets, order) {
  const svg = d3.select('#threat-radar');
  svg.selectAll('*').remove();
  const width = document.getElementById('threat-radar').clientWidth || 600;
  const height = 320;
  const cx = width / 2, cy = height / 2, radius = 110;

  const labels = order.filter(k => k !== 'UNKNOWN');
  const counts = labels.map(k => buckets[k].length);
  const maxCount = Math.max(1, ...counts);
  const angleStep = (Math.PI * 2) / labels.length;

  // grid rings
  for (let r = 1; r <= 4; r++) {
    svg.append('circle')
      .attr('cx', cx).attr('cy', cy).attr('r', (radius / 4) * r)
      .attr('fill', 'none').attr('stroke', 'rgba(88,166,255,0.12)');
  }

  const points = labels.map((label, i) => {
    const value = counts[i] / maxCount;
    const angle = i * angleStep - Math.PI / 2;
    return {
      label,
      x: cx + Math.cos(angle) * radius * value,
      y: cy + Math.sin(angle) * radius * value,
      labelX: cx + Math.cos(angle) * (radius + 30),
      labelY: cy + Math.sin(angle) * (radius + 15),
      count: counts[i],
    };
  });

  // spokes
  labels.forEach((label, i) => {
    const angle = i * angleStep - Math.PI / 2;
    svg.append('line')
      .attr('x1', cx).attr('y1', cy)
      .attr('x2', cx + Math.cos(angle) * radius).attr('y2', cy + Math.sin(angle) * radius)
      .attr('stroke', 'rgba(88,166,255,0.15)');
  });

  const lineGen = d3.line().x(d => d.x).y(d => d.y).curve(d3.curveLinearClosed);
  svg.append('path')
    .attr('d', lineGen(points))
    .attr('fill', 'rgba(248,81,73,0.15)')
    .attr('stroke', 'var(--block)')
    .attr('stroke-width', 1.5);

  svg.selectAll('.radar-point')
    .data(points)
    .join('circle')
    .attr('cx', d => d.x).attr('cy', d => d.y).attr('r', 3)
    .attr('fill', '#f85149');

  svg.selectAll('.radar-label')
    .data(points)
    .join('text')
    .attr('x', d => d.labelX).attr('y', d => d.labelY)
    .attr('text-anchor', 'middle')
    .attr('font-size', 11)
    .attr('fill', '#8b949e')
    .text(d => `${d.label} (${d.count})`);
}

// ---------- Settings page ----------
async function renderSettings() {
  const page = document.getElementById('page');
  page.innerHTML = `
    <h1>Settings</h1>
    <div class="subtitle">Persistent config — writes to config.json, never affects an install in progress.</div>
    <div class="panel">
      <h2>Paranoid Mode (ShieldMax default)</h2>
      <div style="display:flex; align-items:center; gap:12px;">
        <button id="btn-off">OFF</button>
        <button id="btn-on">ON</button>
        <span id="config-status" style="color: var(--dim); font-size: 12px;"></span>
      </div>
    </div>
  `;
  const res = await fetch('/api/config');
  const cfg = await res.json();
  updateToggleUI(cfg.shieldmax_default);

  document.getElementById('btn-on').onclick = async () => {
    const r = await fetch('/api/config/shieldmax/on', { method: 'POST' });
    const d = await r.json();
    updateToggleUI(d.shieldmax_default);
    document.getElementById('config-status').textContent = 'Saved.';
  };
  document.getElementById('btn-off').onclick = async () => {
    const r = await fetch('/api/config/shieldmax/off', { method: 'POST' });
    const d = await r.json();
    updateToggleUI(d.shieldmax_default);
    document.getElementById('config-status').textContent = 'Saved.';
  };
}
function updateToggleUI(isOn) {
  document.getElementById('btn-on').classList.toggle('active', isOn);
  document.getElementById('btn-off').classList.toggle('active', !isOn);
}

// ---------- Command palette ----------
const cpOverlay = document.getElementById('command-palette-overlay');
const cpInput = document.getElementById('cp-input');
const cpResults = document.getElementById('cp-results');
let cpSelectedIdx = 0;
let cpMatches = [];

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    cpOverlay.classList.remove('hidden');
    cpInput.value = '';
    cpInput.focus();
    renderCpResults('');
  } else if (e.key === 'Escape') {
    cpOverlay.classList.add('hidden');
  }
});
cpOverlay.addEventListener('click', e => { if (e.target === cpOverlay) cpOverlay.classList.add('hidden'); });

cpInput.addEventListener('input', () => renderCpResults(cpInput.value));
cpInput.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown') { cpSelectedIdx = Math.min(cpSelectedIdx + 1, cpMatches.length - 1); highlightCp(); }
  if (e.key === 'ArrowUp') { cpSelectedIdx = Math.max(cpSelectedIdx - 1, 0); highlightCp(); }
  if (e.key === 'Enter' && cpMatches[cpSelectedIdx]) {
    window.location.hash = `#/history`;
    cpOverlay.classList.add('hidden');
  }
});

async function renderCpResults(query) {
  if (historyEntries.length === 0) {
    const res = await fetch('/api/history');
    historyEntries = (await res.json()).entries;
  }
  const q = query.toLowerCase();
  cpMatches = historyEntries.filter(e => e.package.toLowerCase().includes(q)).slice(0, 8);
  cpSelectedIdx = 0;
  cpResults.innerHTML = cpMatches.map((e, i) =>
    `<div class="cp-result ${i === 0 ? 'selected' : ''}">${e.package} — <span class="tag tag-${e.verdict}">${e.verdict}</span></div>`
  ).join('') || '<div class="cp-result">No matches</div>';
}
function highlightCp() {
  document.querySelectorAll('.cp-result').forEach((el, i) => el.classList.toggle('selected', i === cpSelectedIdx));
}

// ---------- Init ----------
loadShimStatus();
navigate();
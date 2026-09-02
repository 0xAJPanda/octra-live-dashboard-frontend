const $ = id => document.getElementById(id);
const cpuHistory = [];
let address = '';

function num(value, digits = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(number);
}

function fixed(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number);
}

function usdPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return '$—';
  const digits = number < 0.1 ? 5 : number < 1 ? 4 : 2;
  return `$${new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number)}`;
}

function bytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const units = ['B', 'GB', 'TB'];
  const index = number > 1e12 ? 2 : number > 1e9 ? 1 : 0;
  return `${(number / Math.pow(1000, index * 3)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function duration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return '—';
  const days = Math.floor(value / 86400);
  const hours = Math.floor(value % 86400 / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function setGauge(id, value) {
  const number = Number(value);
  $(id).style.setProperty('--pct', Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : 0);
}

function drawCPUChart() {
  const canvas = $('cpu-chart');
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const padX = 22;
  const padY = 16;

  context.clearRect(0, 0, width, height);
  context.strokeStyle = '#d9d9fa';
  context.lineWidth = 1;
  context.setLineDash([2, 4]);
  for (let index = 1; index < 4; index++) {
    const y = padY + (height - padY * 2) * index / 4;
    context.beginPath();
    context.moveTo(padX, y);
    context.lineTo(width - padX, y);
    context.stroke();
  }
  context.setLineDash([]);
  if (cpuHistory.length < 2) return;

  const span = 30;
  context.beginPath();
  cpuHistory.forEach((value, index) => {
    const x = padX + (width - padX * 2) * (index + span - cpuHistory.length + 1) / span;
    const y = height - padY - (height - padY * 2) * Math.max(0, Math.min(100, value)) / 100;
    if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
  });
  context.strokeStyle = '#0000db';
  context.lineWidth = 2;
  context.stroke();

  const lastX = width - padX;
  context.lineTo(lastX, height - padY);
  context.lineTo(padX, height - padY);
  context.closePath();
  const gradient = context.createLinearGradient(0, padY, 0, height - padY);
  gradient.addColorStop(0, 'rgba(0,0,219,.18)');
  gradient.addColorStop(1, 'rgba(0,0,219,0)');
  context.fillStyle = gradient;
  context.fill();
}

function update(data) {
  const status = data.status || {};
  const host = data.host || {};
  const validator = data.validator || {};
  const enrollment = data.enrollment || {};
  const consensus = data.peers || {};
  const peerCount = Number(consensus.p2p_connected || 0);

  address = status.validator || address;
  $('address').textContent = address || 'unknown identity';

  const activeMember = validator.active === true;
  const scheduledMember = validator.scheduled === true;
  const validatorState = activeMember ? 'active' : scheduledMember ? 'scheduled' : 'observer';

  $('role-label').textContent = `${validatorState === 'observer' ? 'observer' : `${validatorState} validator`} / devnet`;
  $('validator-status').textContent = activeMember ? 'active consensus validator' : scheduledMember ? `scheduled for epoch ${num(validator.activation_epoch)}` : 'observer node';
  $('validator-strip').className = `validator-strip ${validatorState}`;
  $('validator-bond').textContent = enrollment.bond ? `${fixed(Number(enrollment.bond) / 1e6)} OCT` : '—';
  $('validator-enrollment').textContent = enrollment.state || '—';
  $('ready-epoch').textContent = num(enrollment.ready_epoch);
  $('consensus-peer-count').textContent = num(consensus.consensus_peers);
  $('p2p-peer-count').textContent = num(consensus.p2p_connected);

  const roundState = consensus.round_state || {};
  const roundPeers = Number(consensus.round_peers_count || 0);
  const round = roundState.round;
  const stage = String(roundState.step || 'waiting').toLowerCase();
  $('voting-status').textContent = consensus.voting ? 'voting enabled · live consensus' : `voting unavailable${status.voting_reason ? ` · ${status.voting_reason}` : ''}`;

  $('epoch').textContent = num(status.current_epoch);
  $('accounts').textContent = num(status.total_accounts);
  $('active-accounts').textContent = 'network accounts';
  $('tx-index').textContent = num(status.txid_hi);
  $('last-epoch-txs').textContent = 'confirmed transaction index';

  const lag = Math.max(0, Number(status.current_epoch || 0) - Number(status.head_epoch || 0));
  $('head-gap-kpi').textContent = num(lag);
  $('restart-count').textContent = num(status.restarts);
  $('peer-count').textContent = num(peerCount);
  $('sync-label').textContent = activeMember ? 'live consensus' : 'network sync';
  $('sync-state').textContent = activeMember && round !== undefined ? `ROUND ${num(round)}` : scheduledMember ? 'SCHEDULED' : lag <= 2 ? 'SYNCHRONIZED' : 'CATCHING UP';
  $('head-lag').textContent = activeMember ? `${stage} · ${roundPeers} participants · ${peerCount} peers` : lag ? `${lag} epoch behind head` : 'at network head';
  $('sync-ring').style.setProperty('--pct', Math.min(100, peerCount / 24 * 100));

  $('memory-pct').textContent = Number.isFinite(Number(host.memory_used_pct)) ? `${num(host.memory_used_pct)}%` : '—';
  $('memory-detail').textContent = `${bytes(host.memory_used_bytes)} / ${bytes(host.memory_total_bytes)}`;
  setGauge('memory-gauge', host.memory_used_pct);
  $('disk-pct').textContent = Number.isFinite(Number(host.disk_used_pct)) ? `${num(host.disk_used_pct)}%` : '—';
  $('disk-detail').textContent = `${bytes(host.disk_used_bytes)} / ${bytes(host.disk_total_bytes)}`;
  setGauge('disk-gauge', host.disk_used_pct);
  const cpu = Number(host.cpu_used_pct);
  $('cpu-pct').textContent = Number.isFinite(cpu) ? `${fixed(cpu)}%` : '—';
  cpuHistory.push(Number.isFinite(cpu) ? cpu : 0);
  if (cpuHistory.length > 31) cpuHistory.shift();
  drawCPUChart();
  $('load').textContent = Number.isFinite(Number(host.load_1m)) ? Number(host.load_1m).toFixed(2) : '—';
  $('uptime').textContent = duration(host.uptime_seconds);
  $('process-status').textContent = status.process || '—';
  $('rpc-status').textContent = status.rpc || '—';

  $('connection').textContent = data.online ? 'LIVE' : 'DEGRADED';
  $('live-dot').className = `live-dot ${data.online ? 'online' : 'offline'}`;
}

function isoTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown time' : date.toISOString().replace('T', ' ').replace('.000Z', ' UTC');
}

function networkCell(row, value, className = '') {
  const cell = document.createElement('td');
  cell.textContent = value;
  if (className) cell.className = className;
  row.appendChild(cell);
}

function renderNetwork(network) {
  const summary = network.summary || {};
  const validators = Array.isArray(network.validators) ? network.validators : [];
  $('network-active-count').textContent = num(summary.active_validators);
  $('network-scheduled-count').textContent = num(summary.scheduled_validators);
  $('network-total-weight').textContent = num(summary.total_weight);
  $('network-observed-at').textContent = network.fresh ? `Observed ${isoTime(network.observed_at)} · refreshed ${num(network.age_seconds)}s ago` : 'Network observation is stale; values may be outdated.';
  const limitations = network.limitations || {};
  $('network-remote-uptime-note').textContent = `${limitations.remote_uptime || 'Remote host uptime is not available.'} ${limitations.continuity || ''}`.trim();
  const body = $('network-validator-rows');
  body.replaceChildren();
  if (!validators.length) {
    const row = document.createElement('tr');
    networkCell(row, 'No public validator-set data is available yet.');
    row.firstChild.colSpan = 6;
    body.appendChild(row);
    return;
  }
  validators.forEach(validator => {
    const row = document.createElement('tr');
    if (validator.is_local === true) row.className = 'local-row';
    networkCell(row, validator.address || 'unknown');
    const state = validator.active ? 'active' : validator.scheduled ? 'scheduled' : 'not active';
    networkCell(row, state, `network-state ${state === 'scheduled' ? 'scheduled' : ''}`);
    networkCell(row, num(validator.weight));
    networkCell(row, `${fixed(validator.weight_share_pct)}%`);
    networkCell(row, validator.consensus_observed ? `observed${Number.isFinite(Number(validator.consensus_age_seconds)) ? ` · ${fixed(validator.consensus_age_seconds, 1)}s ago` : ''}` : 'not recently observed', validator.consensus_observed ? 'network-state observed' : '');
    networkCell(row, Number.isFinite(Number(validator.continuity_pct)) ? `${fixed(validator.continuity_pct)}%` : 'collecting');
    body.appendChild(row);
  });
}

async function refresh() {
  try {
    const response = await fetch('/api/snapshot', { cache: 'no-store' });
    if (!response.ok) throw new Error(response.status);
    update(await response.json());
  } catch (error) {
    $('connection').textContent = 'OFFLINE';
    $('live-dot').className = 'live-dot offline';
  }
}

async function refreshNetwork() {
  try {
    const response = await fetch('/api/network', { cache: 'no-store' });
    if (!response.ok) throw new Error(response.status);
    renderNetwork(await response.json());
  } catch (error) {
    $('network-observed-at').textContent = 'Network validator-set data is temporarily unavailable.';
  }
}

$('copy').addEventListener('click', async () => {
  if (!address) return;
  await navigator.clipboard.writeText(address);
  $('copy').textContent = 'copied';
  setTimeout(() => { $('copy').textContent = 'copy'; }, 1200);
});

function tick() {
  $('clock').textContent = `${new Date().toISOString().slice(11, 19)} UTC`;
}

window.addEventListener('resize', drawCPUChart);
tick();
setInterval(tick, 1000);
refresh();
refreshNetwork();
setInterval(refresh, 10000);
setInterval(refreshNetwork, 30000);

const $ = id => document.getElementById(id);
let networkTimer;
let networkBusy = false;
const refreshMs = 30_000;

function num(value) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—'; }
function fixed(value, digits = 2) { return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—'; }
function isoTime(value) { return value ? new Date(value).toLocaleString() : 'unknown time'; }
function stateOf(validator) { return validator.active ? 'active' : validator.scheduled ? 'scheduled' : 'not active'; }
function validatorLink(address) { const link = document.createElement('a'); link.href = `/validator/${encodeURIComponent(address)}`; link.textContent = address; return link; }
function cell(row, value) { const node = document.createElement('td'); node.textContent = value; row.appendChild(node); }

function renderLocalSpotlight(validators) {
  const local = validators.find(validator => validator.is_local === true);
  const spotlight = $('local-spotlight');
  if (!local) { spotlight.hidden = true; return; }
  spotlight.hidden = false;
  spotlight.href = `/validator/${encodeURIComponent(local.address)}`;
  $('local-spotlight-address').textContent = local.address;
  $('local-spotlight-state').textContent = `${stateOf(local)} · weight ${num(local.weight)} · ${fixed(local.weight_share_pct)}% active-set share`;
}

function renderNetwork(network) {
  const summary = network.summary || {};
  const validators = Array.isArray(network.validators) ? network.validators : [];
  $('network-active-count').textContent = num(summary.active_validators);
  $('network-scheduled-count').textContent = num(summary.scheduled_validators);
  $('network-total-weight').textContent = num(summary.total_weight);
  $('chain-id').textContent = network.chain_id || 'public chain observation';
  $('network-observed-at').textContent = network.fresh ? `Observed ${isoTime(network.observed_at)} · refreshed ${num(network.age_seconds)}s ago` : 'Network observation is stale; values may be outdated.';
  $('network-remote-uptime-note').textContent = 'This page contains chain-reported validator-set data only. Host resources, addresses, ports, logs, and operational telemetry are not published.';
  renderLocalSpotlight(validators);
  const body = $('network-validator-rows'); body.replaceChildren();
  if (!validators.length) { const row = document.createElement('tr'); cell(row, 'No public validator-set data is available yet.'); row.firstChild.colSpan = 6; body.appendChild(row); return; }
  validators.forEach(validator => {
    const row = document.createElement('tr'); if (validator.is_local === true) row.className = 'local-row';
    const address = document.createElement('td'); address.appendChild(validatorLink(validator.address)); row.appendChild(address);
    cell(row, stateOf(validator)); cell(row, num(validator.weight)); cell(row, `${fixed(validator.weight_share_pct)}%`);
    cell(row, validator.consensus_observed ? 'observed' : 'not observed'); cell(row, `${fixed(validator.continuity_pct)}%`); body.appendChild(row);
  });
}

async function refreshNetwork() {
  if (networkBusy) return; networkBusy = true;
  try {
    const response = await fetch('/api/network', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderNetwork(await response.json());
    $('connection').textContent = 'live'; $('live-dot').classList.add('online'); $('refresh-state').textContent = 'public data only';
  } catch (_) { $('connection').textContent = 'unavailable'; $('live-dot').classList.remove('online'); $('refresh-state').textContent = 'retrying…'; }
  finally { networkBusy = false; clearTimeout(networkTimer); networkTimer = setTimeout(refreshNetwork, document.hidden ? refreshMs * 6 : refreshMs); }
}

async function renderDetail() {
  const address = decodeURIComponent(location.pathname.removeprefix('/validator/'));
  if (!address || location.pathname === '/') return false;
  $('validator-detail').hidden = false; document.querySelector('.network-explorer').hidden = true; document.querySelector('.network-hero').hidden = true;
  const response = await fetch(`/api/validators/${encodeURIComponent(address)}`, { cache: 'no-store' });
  if (!response.ok) throw new Error('validator not found');
  const payload = await response.json(); const validator = payload.validator;
  $('detail-address').textContent = validator.address; $('detail-observed-at').textContent = `Observed ${isoTime(payload.observed_at)}`;
  $('detail-state').textContent = stateOf(validator); $('detail-weight').textContent = num(validator.weight); $('detail-share').textContent = `${fixed(validator.weight_share_pct)}%`;
  $('detail-continuity').textContent = `${fixed(validator.continuity_pct)}%`; $('detail-consensus').textContent = validator.consensus_observed ? 'observed' : 'not observed'; $('detail-first-observed').textContent = isoTime(validator.first_observed_at);
  $('detail-limitations').textContent = 'Public chain observation only. It does not report host resources, location, or infrastructure telemetry.'; return true;
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshNetwork(); });
renderDetail().then(detail => { if (!detail) refreshNetwork(); }).catch(() => { $('connection').textContent = 'unavailable'; });

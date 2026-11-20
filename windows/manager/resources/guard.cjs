'use strict';

const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');
const https = require('node:https');
const { HttpsProxyAgent } = require('./node_modules/https-proxy-agent');

const deployment = JSON.parse(fs.readFileSync(path.join(__dirname, 'deployment.json'), 'utf8'));
const EXPECTED = Object.freeze({ ip: deployment.expected_ip, loc: deployment.expected_country, colo: deployment.expected_colo });
const UPSTREAM = Object.freeze({ host: '127.0.0.1', port: 7899 });
const probeAgent = new HttpsProxyAgent(`http://${UPSTREAM.host}:${UPSTREAM.port}`, { keepAlive: false });

function probeGet(url) {
  return new Promise((resolve, reject) => {
    const fail = error => {
      error.message = `${new URL(url).hostname}: ${error.message}`;
      reject(error);
    };
    const request = https.get(url, {
      agent: probeAgent,
      signal: AbortSignal.timeout(8000),
      headers: { 'Cache-Control': 'no-cache' },
    }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('error', fail);
      response.on('end', () => {
        if (response.statusCode !== 200) fail(new Error(`probe_http_${response.statusCode}`));
        else resolve(body);
      });
    });
    request.on('error', fail);
  });
}

async function probeExit() {
  const [trace, identity] = await Promise.all([
    probeGet('https://claude.ai/cdn-cgi/trace'),
    probeGet('https://api.ipify.org?format=json'),
  ]);
  const fields = Object.fromEntries(trace.trim().split(/\r?\n/).map(line => {
    const index = line.indexOf('=');
    return [line.slice(0, index), line.slice(index + 1)];
  }));
  const ipifyIp = JSON.parse(identity).ip;
  if (ipifyIp !== fields.ip) throw new Error('exit_probes_disagree');
  return { ip: fields.ip, loc: fields.loc, colo: fields.colo, ipifyIp };
}

function createGuard({ probe = probeExit, upstream = UPSTREAM, report = () => {} } = {}) {
  const clients = new Set();
  const tunnels = new Set();
  let allowed = false;
  let reason = 'not_verified';
  let observed = null;
  let probeError = null;
  let checkedAt = null;
  let generation = 0;
  let checking = null;
  let stopping = false;
  let monitor;

  function publish() {
    report({ pid: process.pid, allowed, reason, expected: EXPECTED, observed, probeError,
      checkedAt, activeTunnels: tunnels.size, listen: server.address(), upstream });
  }

  function block(why) {
    allowed = false;
    reason = why;
    generation++;
    for (const { client, remote } of tunnels) {
      client.destroy();
      remote.destroy();
    }
    tunnels.clear();
    publish();
  }

  // Identity checks and proxy transport have separate failure scopes.
  function verify() {
    if (checking) return checking;
    const startedGeneration = generation;
    checking = (async () => {
      try {
        observed = await probe();
        probeError = null;
        checkedAt = new Date().toISOString();
        if (stopping || generation !== startedGeneration) return false;
        if (!Object.keys(EXPECTED).every(key => observed?.[key] === EXPECTED[key])) {
          block('exit_mismatch');
          return false;
        }
        allowed = true;
        reason = 'verified';
        publish();
        return true;
      } catch (error) {
        probeError = String(error);
        reason = allowed ? 'verification_degraded' : 'verification_failed';
        publish();
        return false;
      } finally {
        checking = null;
      }
    })();
    return checking;
  }

  const server = net.createServer({ pauseOnConnect: true }, client => {
    clients.add(client);
    client.on('error', () => {});
    client.on('close', () => clients.delete(client));
    if (!allowed || stopping) {
      if (!client.destroyed) client.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
      return;
    }
    if (client.destroyed) return;
    const approvedGeneration = generation;
    const remote = net.createConnection(upstream);
    const tunnel = { client, remote };
    tunnels.add(tunnel);
    const dialTimer = setTimeout(() => remote.destroy(new Error('upstream_timeout')), 5000);
    remote.on('connect', () => {
      clearTimeout(dialTimer);
      if (!allowed || approvedGeneration !== generation || client.destroyed || stopping) {
        remote.destroy();
        client.destroy();
        return;
      }
      client.setNoDelay(true);
      remote.setNoDelay(true);
      client.pipe(remote);
      remote.pipe(client);
      client.resume();
    });
    remote.on('error', error => {
      console.error(`${new Date().toISOString()} upstream connection: ${error.code}`);
      client.destroy();
    });
    remote.on('close', () => {
      clearTimeout(dialTimer);
      tunnels.delete(tunnel);
      client.destroy();
    });
    client.on('close', () => remote.destroy());
  });

  async function start(port = 17899) {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', resolve);
    });
    publish();
    await verify();
    monitor = setInterval(() => { void verify(); }, 10000);
    return server.address();
  }

  async function stop() {
    stopping = true;
    clearInterval(monitor);
    block('stopped');
    for (const client of clients) client.destroy();
    await new Promise(resolve => server.close(resolve));
  }

  return { start, stop, verify };
}

if (require.main === module) {
  let previous = '';
  let lastRecordedAt = 0;
  const history = path.join(__dirname, 'history');
  fs.mkdirSync(history, { recursive: true });
  const gate = createGuard({ report: state => {
    fs.writeFileSync(path.join(__dirname, 'status.json'), JSON.stringify(state, null, 2));
    const now = new Date();
    const current = `${state.allowed} ${state.reason} ${JSON.stringify(state.observed)} ${state.probeError}`;
    if (current !== previous || now.getTime() - lastRecordedAt >= 60000) {
      fs.appendFileSync(path.join(history, `${now.toISOString().slice(0, 10)}.jsonl`),
        JSON.stringify({ recordedAt: now.toISOString(), ...state }) + '\n');
      lastRecordedAt = now.getTime();
    }
    if (current !== previous) {
      console.log(`${now.toISOString()} ${current}`);
      previous = current;
    }
  } });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    gate.stop().then(() => process.exit(0));
  });
  gate.start().catch(error => { console.error(error.code || error.message); process.exit(1); });
}

module.exports = { createGuard, EXPECTED };

import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';

export function isPrivateIPv4(value) {
  if (typeof value !== 'string' || net.isIP(value) !== 4) return false;
  const [a, b] = value.split('.').map(Number);
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

export function validateRemoteOrigin(value) {
  if (typeof value !== 'string') throw new Error('Remote origin must be an HTTPS hostname');
  let parsed;
  try { parsed = new URL(value); } catch { throw new Error('Invalid remote origin'); }
  if (parsed.protocol !== 'https:' || parsed.origin !== value || parsed.port || parsed.username || parsed.password
      || parsed.hostname === 'localhost' || parsed.hostname.endsWith('.localhost')
      || !parsed.hostname.includes('.') || net.isIP(parsed.hostname)
      || !/^[a-z0-9.-]+$/i.test(parsed.hostname)) {
    throw new Error('Use an HTTPS hostname without path, port, query, IP or credentials');
  }
  return parsed.origin;
}

export function readNetworkSettings(root, env = process.env) {
  const local = {
    mode: 'local', origin: 'https://localhost:3443',
    hosts: ['127.0.0.1', '::1'], tlsDirectory: path.join(root, 'runtime/tls'),
  };
  const override = env.REALTIMEORDERS_NETWORK_MODE;
  if (override && !['local', 'configured'].includes(override)) {
    throw new Error('REALTIMEORDERS_NETWORK_MODE must be local or configured');
  }
  if (override === 'local') return local;
  const filename = path.join(root, 'runtime/network.local.json');
  if (!fs.existsSync(filename)) return local;
  const settings = JSON.parse(fs.readFileSync(filename, 'utf8').replace(/^\uFEFF/, ''));
  if (settings.mode === 'local') return local;
  if (settings.mode === 'remote') {
    return {...local, mode: 'remote', origin: validateRemoteOrigin(settings.origin)};
  }
  if (settings.mode !== 'lan' || !isPrivateIPv4(settings.address)
      || settings.origin !== 'https://' + settings.address + ':3443'
      || settings.tlsDirectory !== 'runtime/tls-lan') {
    throw new Error('Invalid LAN configuration; run scripts/configure-lan.ps1 again');
  }
  return {
    mode: 'lan', address: settings.address, origin: settings.origin,
    hosts: [...local.hosts, settings.address],
    tlsDirectory: path.join(root, settings.tlsDirectory),
  };
}

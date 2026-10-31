import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {isPrivateIPv4, readNetworkSettings} from '../network_config.mjs';

function fixture(t, settings) {
  const base = fs.realpathSync(os.tmpdir());
  const root = fs.mkdtempSync(path.join(base, 'realtimeorders-network-'));
  t.after(() => {
    const resolved = fs.realpathSync(root);
    assert.equal(path.dirname(resolved), base);
    assert.ok(path.basename(resolved).startsWith('realtimeorders-network-'));
    fs.rmSync(resolved, {recursive: true});
  });
  if (settings) {
    fs.mkdirSync(path.join(root, 'runtime'));
    fs.writeFileSync(path.join(root, 'runtime/network.local.json'), JSON.stringify(settings));
  }
  return root;
}

const lan = {mode: 'lan', address: '172.20.10.2', origin: 'https://172.20.10.2:3443', tlsDirectory: 'runtime/tls-lan'};

test('default profile binds only IPv4 and IPv6 loopback', t => {
  assert.deepEqual(readNetworkSettings(fixture(t), {}).hosts, ['127.0.0.1', '::1']);
});

test('LAN profile binds the exact configured private address and loopback', t => {
  const result = readNetworkSettings(fixture(t, lan), {});
  assert.deepEqual(result.hosts, ['127.0.0.1', '::1', '172.20.10.2']);
  assert.equal(result.origin, lan.origin);
});

test('isolated validation can override LAN to loopback', t => {
  const result = readNetworkSettings(fixture(t, lan), {REALTIMEORDERS_NETWORK_MODE: 'local'});
  assert.equal(result.mode, 'local');
  assert.deepEqual(result.hosts, ['127.0.0.1', '::1']);
});

test('reject mismatched origins, public IPs and arbitrary TLS directories', t => {
  for (const change of [
    {origin: 'https://evil.invalid:3443'}, {address: '0.0.0.0'},
    {address: '8.8.8.8'}, {tlsDirectory: '../private'}, {mode: 'unexpected'},
  ]) {
    assert.throws(() => readNetworkSettings(fixture(t, {...lan, ...change}), {}));
  }
});

test('address and environment validation reject accidental public exposure', t => {
  for (const address of ['127.0.0.1', '::1', '169.254.0.2', '0.0.0.0', '172.32.0.1', 'example.invalid']) {
    assert.equal(isPrivateIPv4(address), false);
  }
  assert.throws(() => readNetworkSettings(fixture(t), {REALTIMEORDERS_NETWORK_MODE: 'typo'}));
});


test('remote tunnel profile keeps every app listener on loopback', t => {
  const result=readNetworkSettings(fixture(t,{mode:'remote',origin:'https://demo.trycloudflare.com'}),{});
  assert.equal(result.mode,'remote');assert.equal(result.origin,'https://demo.trycloudflare.com');
  assert.deepEqual(result.hosts,['127.0.0.1','::1']);
  assert.ok(result.tlsDirectory.endsWith(path.join('runtime','tls')));
});

test('remote profile rejects origins that would weaken host or TLS checks', t => {
  for(const origin of ['http://demo.example.com','https://localhost','https://127.0.0.1','https://demo.example.com/path',
    'https://user:pass@demo.example.com','https://demo.example.com?x=1','https://demo.example.com:3443','https://demo.example.com/']) {
    assert.throws(()=>readNetworkSettings(fixture(t,{mode:'remote',origin}),{}));
  }
});

import https from 'node:https';
import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {readNetworkSettings} from './network_config.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const network=readNetworkSettings(root);
const canonicalHost=new URL(network.origin).host;
const tls={key:fs.readFileSync(path.join(network.tlsDirectory,'key.pem')),cert:fs.readFileSync(path.join(network.tlsDirectory,'cert.pem'))};

function clientAddress(req) {
  const peer=req.socket.remoteAddress;
  // Only the local tunnel connector may provide Cloudflare's edge client IP.
  const header=req.headers['cf-connecting-ip'];
  if(network.mode==='remote' && ['127.0.0.1','::1','::ffff:127.0.0.1'].includes(peer)
      && typeof header==='string' && net.isIP(header)) return header;
  return peer;
}

function forwardRequest(req,res){
  if(!req.url.startsWith('/')){res.writeHead(400);res.end();return;}
  if(network.mode!=='local' && req.headers.host!==canonicalHost && req.url!=='/api/health'){
    if(!req.url.startsWith('/api/') && ['GET','HEAD'].includes(req.method)){
      res.writeHead(307,{location:network.origin+req.url,'cache-control':'no-store'});
    }else{res.writeHead(421,{'content-type':'text/plain; charset=utf-8'});}
    res.end();return;
  }
  const port=req.url.startsWith('/api/')?8000:3000;
  const upstream=http.request({hostname:'127.0.0.1',port,path:req.url,method:req.method,
    headers:{...req.headers,'x-forwarded-proto':'https','x-forwarded-for':clientAddress(req)}},response=>{
    res.writeHead(response.statusCode,response.headers);
    response.pipe(res);
  });
  upstream.on('socket',socket=>socket.setNoDelay(true));
  upstream.on('error',()=>{
    if(!res.headersSent)res.writeHead(502,{'content-type':'text/plain; charset=utf-8'});
    res.end('Dịch vụ đang khởi động. Vui lòng tải lại.');
  });
  req.on('aborted',()=>upstream.destroy());
  req.pipe(upstream);
}

function forwardUpgrade(req,socket,head){
  if(network.mode!=='local' && req.headers.host!==canonicalHost){
    socket.end('HTTP/1.1 421 Misdirected Request\r\nConnection: close\r\n\r\n');return;
  }
  socket.setNoDelay(true);
  req.headers['x-forwarded-for']=clientAddress(req);
  req.headers['x-forwarded-proto']='https';
  const port=req.url==='/ws'?8000:3000;
  const upstream=net.connect(port,'127.0.0.1',()=>{
    upstream.write(req.method+' '+req.url+' HTTP/'+req.httpVersion+'\r\n'+
      Object.entries(req.headers).map(([key,value])=>key+': '+value).join('\r\n')+'\r\n\r\n');
    if(head.length)upstream.write(head);
    upstream.pipe(socket);
    socket.pipe(upstream);
  });
  upstream.setNoDelay(true);
  upstream.on('error',()=>socket.destroy());
  socket.on('error',()=>upstream.destroy());
  socket.on('close',()=>upstream.destroy());
}

for(const host of network.hosts){
  const server=https.createServer(tls,forwardRequest);
  server.on('secureConnection',socket=>socket.setNoDelay(true));
  server.on('upgrade',forwardUpgrade);
  server.requestTimeout=30000;
  server.on('error',error=>{
    if(host==='::1' && ['EAFNOSUPPORT','EADDRNOTAVAIL'].includes(error.code)){
      console.log('IPv6 loopback unavailable; IPv4 remains enabled.');return;
    }
    console.error('Proxy listen failed: '+host+' ('+error.code+')');process.exit(1);
  });
  server.listen({port:3443,host,...(host==='::1'?{ipv6Only:true}:{})},()=>{
    console.log('RealtimeOrders HTTPS ready: '+host+':3443 ('+network.mode+')');
  });
}

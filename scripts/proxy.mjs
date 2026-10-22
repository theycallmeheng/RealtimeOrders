import https from 'node:https';
import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=https.createServer({key:fs.readFileSync(path.join(root,'runtime/tls/key.pem')),cert:fs.readFileSync(path.join(root,'runtime/tls/cert.pem'))},(req,res)=>{
  const port=req.url.startsWith('/api/')?8000:3000;
  const upstream=http.request({hostname:'127.0.0.1',port,path:req.url,method:req.method,headers:{...req.headers,'x-forwarded-proto':'https','x-forwarded-for':req.socket.remoteAddress}},response=>{
    res.writeHead(response.statusCode,response.headers);response.pipe(res);
  });
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'content-type':'text/plain; charset=utf-8'});res.end('Dịch vụ đang khởi động. Vui lòng tải lại.');});
  req.on('aborted',()=>upstream.destroy());req.pipe(upstream);
});
server.on('upgrade',(req,socket,head)=>{
  req.headers['x-forwarded-for']=req.socket.remoteAddress;
  req.headers['x-forwarded-proto']='https';
  const port=req.url==='/ws'?8000:3000;
  const upstream=net.connect(port,'127.0.0.1',()=>{
    upstream.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`+Object.entries(req.headers).map(([k,v])=>`${k}: ${v}`).join('\r\n')+'\r\n\r\n');
    if(head.length)upstream.write(head);upstream.pipe(socket);socket.pipe(upstream);
  });
  upstream.on('error',()=>socket.destroy());socket.on('error',()=>upstream.destroy());socket.on('close',()=>upstream.destroy());
});
server.requestTimeout=30000;
server.listen(3443,'127.0.0.1',()=>console.log('RealtimeOrders local HTTPS: https://localhost:3443'));

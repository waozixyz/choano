// Real browser input against a disposable headless Chromium profile.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,extname,resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
const root=resolve(process.argv[2]||'build/web');
const types={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.png':'image/png','.wav':'audio/wav','.json':'application/json'};
const missing=[],errors=[];
const server=createServer(async(req,res)=>{const path=new URL(req.url,'http://x').pathname;try{const file=resolve(root,'.'+(path==='/'?'/index.html':path));if(!file.startsWith(root+'/'))throw Error('Path');const data=await readFile(file);res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream'});res.end(data)}catch{missing.push(path);res.writeHead(404);res.end()}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const profile=await mkdtemp(join(tmpdir(),'choano-browser-'));
const env={...process.env,YUE_DESKTOP_RECOVERY:'0'};for(const key of ['DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'])delete env[key];
const browser=spawn(process.env.CHROMIUM||'chromium',['--headless=new','--no-sandbox','--disable-dev-shm-usage','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{env,stdio:'ignore'});
let socket,sequence=0;const pending=new Map();
const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timed out'))},20000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}))});
const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value};
const until=async(expression,timeout=120000)=>{const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await delay(100)}throw Error('Timed out: '+expression+'\n'+errors.slice(-8).join('\n'))};
try{
 let port;for(let i=0;i<200;i++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(50)}if(!port)throw Error('Chromium did not start');
 const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{socket.onopen=r;socket.onerror=j});
 socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error')errors.push(m.params.args.map(a=>a.value||a.description).join(' '));const p=pending.get(m.id);if(!p)return;clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)};
 await command('Runtime.enable');await command('Page.enable');await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
 await until('globalThis.Module?.choanoReady && Number.isFinite(Module.choanoX)');
 if(!await evaluate('Module.FS.stat("/assets/choano/background-inside.png").size>100000'))throw Error('Game images missing from the renderer filesystem');
 await delay(500);
 await command('Input.dispatchKeyEvent',{type:'keyDown',key:'r',code:'KeyR',windowsVirtualKeyCode:82});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'r',code:'KeyR',windowsVirtualKeyCode:82});await delay(100);
 if(process.env.CHOANO_SCREENSHOT){const shot=await command('Page.captureScreenshot',{format:'png'});await writeFile(process.env.CHOANO_SCREENSHOT,Buffer.from(shot.data,'base64'))}
 const before=await evaluate('Module.choanoX');
 await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});await delay(350);await command('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
 const after=await evaluate('Module.choanoX');if(after-before<10)throw Error(`Swimming failed: ${before} -> ${after}`);
 await evaluate('document.querySelector("#profile").click()');await until('Module.profileVisible');
 await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await until('!Module.profileVisible');
 await command('Input.dispatchKeyEvent',{type:'keyDown',key:'r',code:'KeyR',windowsVirtualKeyCode:82});await command('Input.dispatchKeyEvent',{type:'keyUp',key:'r',code:'KeyR',windowsVirtualKeyCode:82});await until('Math.abs(Module.choanoX-245)<1');
 await command('Emulation.setDeviceMetricsOverride',{width:390,height:740,deviceScaleFactor:1,mobile:true});await delay(300);const touch=await evaluate('(()=>{const b=document.querySelector("[data-key=left]").getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2}})()');
 await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:touch.x,y:touch.y}]});await delay(300);await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 await command('Page.reload');await until('Module.choanoReady && Number.isFinite(Module.choanoX)');
 if(missing.length)throw Error('Missing assets: '+missing.join(', '));if(errors.length)throw Error(errors.join('\n'));
 console.log('Choano local browser tests passed: swimming, Profile/Back, restart, narrow viewport and reload.');
}finally{
 const exited=browser.exitCode!==null?Promise.resolve():new Promise(r=>browser.once('exit',r));
 if(socket?.readyState===WebSocket.OPEN)await command('Browser.close').catch(()=>{});
 if(browser.exitCode===null)browser.kill('SIGTERM');
 await exited;socket?.close();
 for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Browser closed'))}pending.clear();
 server.closeAllConnections();await new Promise(r=>server.close(r));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:200})
}

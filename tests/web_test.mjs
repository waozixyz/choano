// Real browser input against a disposable headless Chromium profile.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile,mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {join,extname,resolve} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
const root=resolve(process.argv[2]||'build/web');
const types={'.html':'text/html','.js':'text/javascript','.wasm':'application/wasm','.png':'image/png','.wav':'audio/wav','.json':'application/json'};
const missing=[],errors=[];
const server=createServer(async(req,res)=>{const url=new URL(req.url,'http://x');const path=url.pathname;if(path==='/browser-storage.html'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<!doctype html><title>Browser storage setup</title><link rel="icon" href="/assets/choano/icon.png">');return}try{if(['/game.js','/game.wasm','/assets/manifest.json'].includes(path)&&!url.searchParams.has('v'))throw Error('Unversioned cached asset');const file=resolve(root,'.'+(path==='/'?'/index.html':path));if(!file.startsWith(root+'/'))throw Error('Path');const data=await readFile(file);res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream'});res.end(data)}catch{missing.push(path);res.writeHead(404);res.end()}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
await mkdir('work',{recursive:true});
const profile=await mkdtemp(resolve('work/choano-browser-'));
const env={...process.env,YUE_DESKTOP_RECOVERY:'0'};for(const key of ['DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER'])delete env[key];
const browser=spawn(process.env.CHROMIUM||'chromium',['--headless=new','--mute-audio','--no-sandbox','--disable-dev-shm-usage','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{env,stdio:['ignore','ignore','pipe']});
let browserFailure='',browserDiagnostics='';browser.on('error',error=>{browserFailure=error.message});browser.stderr.on('data',chunk=>{browserDiagnostics=(browserDiagnostics+chunk).slice(-2000)});
let socket,sequence=0;const pending=new Map();
const command=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error(method+' timed out'))},20000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}))});
const evaluate=async expression=>{const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value};
const until=async(expression,timeout=120000)=>{const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await delay(100)}throw Error('Timed out: '+expression+'\n'+errors.slice(-8).join('\n'))};
try{
 let port;for(let i=0;i<600;i++){if(browserFailure||browser.exitCode!==null)throw Error('Browser could not start: '+(browserFailure||browserDiagnostics));try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await delay(50)}if(!port)throw Error('Browser startup timed out: '+browserDiagnostics);
 const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{socket.onopen=r;socket.onerror=j});
 socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error')errors.push(m.params.args.map(a=>a.value||a.description).join(' '));const p=pending.get(m.id);if(!p)return;clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)};
 await command('Runtime.enable');await command('Page.enable');
 await command('Page.addScriptToEvaluateOnNewDocument',{source:`
 (()=>{
 globalThis.choanoAudioStarts=[];globalThis.choanoAudioGains=[];
 const start=AudioBufferSourceNode.prototype.start;
 AudioBufferSourceNode.prototype.start=function(...args){choanoAudioStarts.push({loop:this.loop,duration:this.buffer?.duration});return start.apply(this,args)};
 const createGain=AudioContext.prototype.createGain;
 AudioContext.prototype.createGain=function(...args){const node=createGain.apply(this,args);choanoAudioGains.push(node);return node};
 })();
 `});await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});

 const press=async(key,code,vk)=>{await command('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:vk});await command('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:vk})};
 const click=async(x,y)=>{await command('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});await delay(80);await command('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});await delay(120)};
 const touch=(type,x,y)=>command('Input.dispatchTouchEvent',{type,touchPoints:type==='touchEnd'?[]:[{x,y}]});
 const where=()=>evaluate('[Module.choanoX,Module.choanoY]');
 // One held contact drags far right, past the pad, then points each way from
 // the pad's visible centre, where the press began: each leg must travel
 // where it points, with no sideways drift, then coasts smoothly to rest.
 const frames=async count=>{for(let index=0;index<count;index++)await evaluate('new Promise(resolve=>requestAnimationFrame(resolve))')};
 const coast=async label=>{
  const released=await where();await frames(6);
  const first=await where();await frames(6);
  const second=await where();await frames(6);
  const third=await where();await frames(30);
  const rest=await where();
  await frames(6);const still=await where();
  const step=(a,b)=>Math.hypot(b[0]-a[0],b[1]-a[1]);
  const firstTravel=step(released,first),secondTravel=step(first,second),thirdTravel=step(second,third);
  if(!(firstTravel>2&&secondTravel<firstTravel&&thirdTravel<secondTravel))throw Error(`${label}: release did not decelerate smoothly: ${firstTravel.toFixed(2)}, ${secondTravel.toFixed(2)}, ${thirdTravel.toFixed(2)}`);
  const stillTravel=step(rest,still);
  if(stillTravel>.1)throw Error(`${label}: release coast did not settle completely: ${firstTravel.toFixed(2)}, ${secondTravel.toFixed(2)}, ${thirdTravel.toFixed(2)}, ${step(third,rest).toFixed(2)}, ${stillTravel.toFixed(2)}`);
  const before=await where();await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:before[0],y:before[1]});await delay(200);
  await command('Input.dispatchMouseEvent',{type:'mousePressed',x:before[0],y:before[1],button:'left',clickCount:1});await command('Input.dispatchMouseEvent',{type:'mouseReleased',x:before[0],y:before[1],button:'left',clickCount:1});await delay(200);
  if(Math.hypot(...(await where()).map((value,index)=>value-before[index]))>1)throw Error(label+': pointer movement or a click restarted the player');
 };
 const turns=async(label,ox,oy,spawn=[245,209])=>{
  await press('r','KeyR',82);
  if(spawn)await until(`Math.abs(Module.choanoX-${spawn[0]})<1 && Math.abs(Module.choanoY-${spawn[1]})<1`);
  // Fish centers on the current sea geometry. The first layout after startup
  // or rotation can change that geometry; its earlier position is no reset oracle.
  await frames(3);await delay(100);
  await touch('touchStart',ox,oy);await delay(80);for(const x of [ox+60,ox+120,ox+180]){await touch('touchMove',x,oy);await delay(60)}await delay(250);
  const d=Math.SQRT1_2,legs=[['below the pad',0,1],['above the pad',0,-1],['left',-1,0],['right',1,0],['down-right',d,d],['up-left',-d,-d],['down-left',-d,d],['up-right',d,-d]];
  for(const [name,x,y] of legs){
   await touch('touchMove',ox+x*90,oy+y*90);await delay(40);const from=await where();await delay(300);const to=await where();
   const along=(to[0]-from[0])*x+(to[1]-from[1])*y,across=Math.abs((to[0]-from[0])*y-(to[1]-from[1])*x);
   if(!(along>8&&across<along*.12))throw Error(`${label}: pointing ${name} after a long drag swam ${along.toFixed(1)} along and ${across.toFixed(1)} sideways`);
  }
  await touch('touchEnd');await coast(label);
 };
 const shot=async path=>{if(path){const result=await command('Page.captureScreenshot',{format:'png'});await writeFile(path,Buffer.from(result.data,'base64'))}};
 const dimensions=()=>evaluate('({w:Module.canvas.clientWidth,h:Module.canvas.clientHeight})');
 // Match shell.zi's compact top action geometry.
 const actionWidth=text=>Math.max(72,24+[...text].reduce((sum,c)=>sum+(' iIljtfr.,:'.includes(c)||c==="'"?5:'mwWM'.includes(c)?16:10),0));
 const actionCenter=(width,label,title=false)=>{
  let right=width-8;
  if(label==='Settings')return width-34;
  right-=60;
  const labels=[...(title?['Downloads']:[]),'PROFILE'];
  const total=labels.reduce((sum,text)=>sum+actionWidth(text),0);
  const scale=Math.min(1,(width-136-(title?8:0))/total);
  for(const text of labels){
   const size=actionWidth(text)*scale;
   if(text===(label==='Profile'?'PROFILE':label))return right-size/2;
   right-=size+8;
  }
  throw Error('Unknown action '+label);
 };
 const wardrobe=async()=>{
  await click(34,26);
  await until('Module.choanoWardrobeOpen');
  if(await evaluate('Module.choanoPage')!==0)throw Error('Shop must stay on title');
  await press('Escape','Escape',27);await until('!Module.choanoWardrobeOpen');
 };
 const shopHidden=async()=>{
  await click(120,26);await delay(150);
  if(await evaluate('Module.choanoWardrobeOpen || Module.choanoPage!==1'))throw Error('Gameplay shop must be absent');
 };
 // Clicks where the title's compact Downloads pill sits, left of Settings and the wardrobe. The
 // new tab it opens is caught and cancelled, so nothing leaves this profile.
 const download=async()=>{
  await evaluate(`globalThis.caught||(globalThis.caught=[],addEventListener('click',e=>{const a=e.target.closest&&e.target.closest('a');if(a){caught.push({href:a.href,target:a.target,rel:a.rel});e.preventDefault()}},true)),true`);
  await click(actionCenter((await dimensions()).w,'Downloads',true),26);await delay(150);return evaluate('caught.splice(0)')};
 const downloadsOpen=async label=>{
  const opened=await download();
  if(opened.length!==1||opened[0].href!=='https://github.com/waozixyz/choano/releases/latest'||opened[0].target!=='_blank'||!opened[0].rel.includes('noopener'))throw Error(label+': Downloads did not open the latest release in a new tab: '+JSON.stringify(opened));
  if(!await evaluate('Module.choanoPage===0 && !Module.profileVisible && document.querySelectorAll("a").length===0'))throw Error(label+': Downloads left the title screen or a link behind');
 };
 const downloadsHidden=async label=>{
  // The title Downloads position becomes Profile on paused screens. Probe
  // the unused center of the bar without activating another real action.
  await click((await dimensions()).w/2,26);
  if((await evaluate('caught.splice(0)')).length)throw Error('Downloads shows '+label);
 };
 await until('globalThis.Module?.choanoReady && Module.choanoPage===0');await delay(400);
 if(!await evaluate('Module.FS.stat("/assets/choano/organisms-hd.png").size>1000000'))throw Error('High-resolution organisms not loaded');
 if(!await evaluate('Module.FS.stat("/assets/choano/shop.png").size>10000'))throw Error('Illustrated Shop is not bundled');
 if(!await evaluate('document.querySelectorAll("header,footer,button,#loading").length===0 && Module.canvas.clientWidth===innerWidth && Module.canvas.clientHeight===innerHeight'))throw Error('HTML app chrome remains');
 await shot(process.env.CHOANO_SCREENSHOT);
 // Exercise the real image control, including its paint and browser cursor.
 const shopPixels=async()=> (await command('Page.captureScreenshot',{format:'png',clip:{x:0,y:0,width:68,height:64,scale:1}})).data;
 const normalShop=await shopPixels();
 await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:34,y:26});await delay(150);
 if(await evaluate('getComputedStyle(Module.canvas).cursor')!=='pointer')throw Error('Shop hover did not show a pointer cursor');
 const hoverShop=await shopPixels();
 if(hoverShop===normalShop)throw Error('Shop hover did not change its picture');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.shop-hover.png');
 await command('Input.dispatchMouseEvent',{type:'mousePressed',x:34,y:26,button:'left',clickCount:1});await delay(150);
 if(await shopPixels()===hoverShop)throw Error('Shop press did not change its picture');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.shop-press.png');
 await command('Input.dispatchMouseEvent',{type:'mouseReleased',x:34,y:26,button:'left',clickCount:1});
 await until('Module.choanoWardrobeOpen');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.shop.png');
 await press('Escape','Escape',27);await until('!Module.choanoWardrobeOpen');
 await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:200,y:200});await delay(100);
 await downloadsOpen('landscape title');await wardrobe();
 const lockedSize=await dimensions();
 await click(lockedSize.w/2+80,lockedSize.h-98);
 await until('Module.choanoFishLocked && Module.choanoFishLockMessage');
 await click(actionCenter(lockedSize.w,'Settings',true),26);await until('Module.choanoPage===3');
 await press('Escape','Escape',27);await until('Module.choanoPage===0');
 await press('ArrowRight','ArrowRight',39);await delay(150);
 let size=await dimensions();await click(size.w/2,size.h-44);await until('Module.choanoPage===1 && Math.abs(Module.choanoX-245)<1');
 if(await evaluate('Module.choanoMode')!==0)throw Error('Fish mode was playable before it was earned');
 await shopHidden();
 await downloadsHidden('during play');if(await evaluate('Module.choanoPage')!==1)throw Error('A click in the top bar left the game');
 await until('choanoAudioStarts.some(source=>!source.loop && source.duration>0)');
 // Mute during an actual cue: completed chimes have no live gain node.
 const audioStarts=await evaluate('choanoAudioStarts.length');
 await press('r','KeyR',82);await until(`choanoAudioStarts.length>${audioStarts}`);
 await press('m','KeyM',77);await until('Module.choanoMuted');
 await until('choanoAudioGains.some(node=>node.gain.value===0)');
 await press('m','KeyM',77);await until('!Module.choanoMuted');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.game.png');
 const before=await evaluate('Module.choanoX');await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});await delay(350);await command('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
 if(await evaluate('Module.choanoX')-before<10)throw Error('Keyboard swimming failed');
 await delay(700);const clicked=await evaluate('[Module.choanoX,Module.choanoY]');await click(300,200);await delay(300);
 if(await evaluate(`Math.hypot(Module.choanoX-${clicked[0]},Module.choanoY-${clicked[1]})`)>1)throw Error('A click started swimming');
 await command('Emulation.setTouchEmulationEnabled',{enabled:true});
 const swipeBefore=await evaluate('Module.choanoX');await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:300,y:200}]});await delay(100);await command('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:360,y:200}]});await delay(300);
 const held=await evaluate('Module.choanoX');if(held-swipeBefore<8)throw Error('Touch steering did not swim right');await delay(250);if(await evaluate('Module.choanoX')-held<8)throw Error('A held touch stopped swimming');
 await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await coast('right swipe');
 const tapped=await evaluate('[Module.choanoX,Module.choanoY]');await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:300,y:200}]});await delay(80);await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await delay(400);
 if(await evaluate(`Math.hypot(Module.choanoX-${tapped[0]},Module.choanoY-${tapped[1]})`)>1)throw Error('A tap started swimming');
 await press('r','KeyR',82);await until('Math.abs(Module.choanoX-245)<1 && Math.abs(Module.choanoY-209)<1');await delay(100);
 const diagonal=await evaluate('[Module.choanoX,Module.choanoY]');await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:300,y:200}]});await delay(100);await command('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:330,y:240}]});await delay(400);
 const [dx,dy]=await evaluate('[Module.choanoX,Module.choanoY]').then(([x,y])=>[x-diagonal[0],y-diagonal[1]]);if(!(dy>8&&dx>4&&Math.abs(dy/dx-4/3)<.2))throw Error(`A held diagonal did not steer freely: ${dx},${dy}`);
 await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await coast('diagonal swipe');
 await turns('Amoeba landscape',300,200);if(await evaluate('Module.choanoDishFrame')!==false)throw Error('The landscape dish took the portrait rim');
 await press('Escape','Escape',27);await until('Module.choanoPage===2');const paused=await evaluate('Module.choanoX');await delay(350);if(await evaluate('Module.choanoX')!==paused)throw Error('Pause advanced the game');
 await downloadsHidden('while paused');
 await click(actionCenter(size.w,'Settings'),26);await until('Module.choanoPage===3');
 const settingsChoice=async(right,row)=>{
  const {w,h}=await dimensions(),pw=Math.min(480,w-32),ph=Math.min(344,h-24),compact=ph<328;
  await click(w/2+(right?1:-1)*(pw-40)/4,(h-ph)/2+(row?(compact?156:200):(compact?78:108))+(compact?22:24));
 };
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.settings.png');
 await settingsChoice(true,0);if(await evaluate('Module.choanoPage')!==3)throw Error('Control choice left Settings');
 await settingsChoice(true,1);await until('Module.choanoMuted');await settingsChoice(false,1);await until('!Module.choanoMuted');
 await press('Escape','Escape',27);await until('Module.choanoPage===2');await press('Escape','Escape',27);await until('Module.choanoPage===1');
 await press('Escape','Escape',27);await until('Module.choanoPage===2');await click(actionCenter(size.w,'Profile'),26);await until('Module.profileVisible');await press('Escape','Escape',27);await until('!Module.profileVisible');await delay(150);await press('Escape','Escape',27);await until('Module.choanoPage===1');await delay(150);
 await press('r','KeyR',82);await until('Math.abs(Module.choanoX-245)<1');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.game.png');
 await command('Emulation.setDeviceMetricsOverride',{width:390,height:740,deviceScaleFactor:1,mobile:true});await delay(350);
 const touchBefore=await evaluate('Module.choanoX');await command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:165,y:630}]});await delay(350);await command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
 if(await evaluate('Module.choanoX')-touchBefore<8)throw Error('In-app direction pad did not swim right');
 await press('m','KeyM',77);await until('Module.choanoMuted');await delay(1500);
 await command('Page.reload');await until('globalThis.Module?.choanoReady && Module.choanoPage===0');await delay(300);await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.portrait.png');
 await downloadsOpen('portrait title');await wardrobe();
 if(!await evaluate('Module.choanoMuted'))throw Error('Sound preference was not retained');
 await press('Enter','Enter',13);await until('Module.choanoPage===1');
 // Swipe steering again, in portrait, then Fish mode as if earned.
 // Stop the app before replacing its IDBFS record so its in-memory settings
 // cannot overwrite the seed. Preserve the real saved entry’s filesystem metadata.
 const prefer=async text=>{
  await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/browser-storage.html`});
  await until('document.title==="Browser storage setup"');
  await evaluate(`new Promise((resolve,reject)=>{
   const request=indexedDB.open('/kryon-apps');request.onerror=()=>reject(request.error);
   request.onsuccess=()=>{const db=request.result,tx=db.transaction('FILE_DATA','readwrite'),store=tx.objectStore('FILE_DATA');
    const entry=store.get('/kryon-apps/choano/preferences.v1');
    entry.onsuccess=()=>{if(!entry.result){tx.abort();return}store.put({...entry.result,contents:new TextEncoder().encode(${JSON.stringify(text)}),timestamp:new Date()},'/kryon-apps/choano/preferences.v1')};
    tx.oncomplete=()=>{db.close();resolve(true)};tx.onabort=tx.onerror=()=>{db.close();reject(Error('Could not seed existing preferences'))};
   };
  })`);
  await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
  await until('globalThis.Module?.choanoReady && Module.choanoPage===0');await delay(300);
  await press('Enter','Enter',13);await until('Module.choanoPage===1');await delay(200);
 };
 // A tall phone textures the whole area and rims the arena; the sea keeps its shape.
 await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await prefer('1s110');if(await evaluate('Module.choanoMode')!==0)throw Error('Amoeba mode did not start');
 if(await evaluate('Module.choanoDishFrame')!==true)throw Error('The portrait dish has no rimmed arena');
 await shot(process.env.CHOANO_SCREENSHOT&&process.env.CHOANO_SCREENSHOT+'.portrait-game.png');await turns('Amoeba portrait',195,400);
 await prefer('1s111');
 if(await evaluate('Module.choanoMode')!==1)throw Error('Fish mode did not start once earned');if(await evaluate('Module.choanoDishFrame')!==false)throw Error('Fish mode kept the dish rim');await turns('Fish portrait',195,400,null);
 await command('Emulation.clearDeviceMetricsOverride');await delay(350);await press('r','KeyR',82);await delay(200);await turns('Fish landscape',300,200,null);
 // Inspect the real durable record after leaving the running page. Both fields
 // share one IDBFS entry, and reopening must not restore an active run.
 await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/browser-storage.html`});
 await until('document.title==="Browser storage setup"');
 const earned=await evaluate(`new Promise((resolve,reject)=>{
  const request=indexedDB.open('/kryon-apps');request.onerror=()=>reject(request.error);
  request.onsuccess=()=>{const db=request.result,tx=db.transaction('FILE_DATA','readonly');
   const row=tx.objectStore('FILE_DATA').get('/kryon-apps/choano/choano.earned.guest.v1');
   row.onsuccess=()=>resolve(row.result?JSON.parse(new TextDecoder().decode(row.result.contents)):null);
   tx.oncomplete=()=>db.close();tx.onerror=()=>reject(tx.error);
  };
 })`);
 if(!earned || typeof earned.pending!=='boolean' || earned.earned.game!=='choano' || earned.earned.unlocked<1 ||
    Object.keys(earned.earned).sort().join(',')!=='completed,game,unlocked,updated_at')throw Error('Earned record and pending marker were not saved atomically');
 await command('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/`});
 await until('globalThis.Module?.choanoReady && Module.choanoPage===0');
 if(missing.length)throw Error('Missing assets: '+missing.join(', '));if(errors.length)throw Error(errors.join('\n'));
 console.log('Choano local browser tests passed: app title/chrome, title-only Downloads to the latest release, locked Fish mode, choice, keyboard/click no start/held free touch steering/clean turns after long drags in Amoeba and Fish, landscape and portrait/round landscape and rimmed portrait dish/release glide/tap no start/pad, title-only shop/pause, nested navigation, Profile, restart, persisted controls/sound, portrait and reload.');
}finally{
 const exited=!browser.pid||browser.exitCode!==null?Promise.resolve():new Promise(r=>browser.once('exit',r));
 if(socket?.readyState===WebSocket.OPEN)await command('Browser.close').catch(()=>{});
 if(browser.exitCode===null)browser.kill('SIGTERM');
 await exited;socket?.close();
 for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Browser closed'))}pending.clear();
 server.closeAllConnections();await new Promise(r=>server.close(r));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:200})
}

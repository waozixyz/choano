#!/usr/bin/env python3
"""Compile the production adapter against real IDBFS (no profile/VM rebuild)."""
import os
from pathlib import Path
import subprocess
import shutil
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env = dict(os.environ)
locked = ['--locked']
package = lambda name: Path(subprocess.check_output(['ziran', 'pkg', 'path', name, *locked], text=True).strip())
out = ROOT / 'build/progress-browser-test'
out.mkdir(parents=True, exist_ok=True)
subprocess.run(['ziran', 'build', '--project', *locked, '--target=c', '--define', 'PLATFORM_WEB',
                '--define', 'CHOANO_PROGRESS_STORAGE_TEST', '--entry', 'progress_browser:main',
                '-o', str(out / 'generated'), 'tests/progress_browser.zi'], check=True, env=env)
ziran = package('ziran')
emcc = os.environ.get('EMCC') or shutil.which('emcc') or str(Path.home() / 'emsdk/upstream/emscripten/emcc')
env['EM_CACHE'] = str(ROOT / 'build/profile-web/emscripten-cache')
subprocess.run([emcc, '-O1', '-I' + str(ziran / 'include'),
                '-iquote', str(out / 'generated'), *map(str, (out / 'generated').rglob('*.c')),
                str(ROOT / 'build/profile-web/runtime/libziran.a'),
                '--js-library', str(ziran / 'web/ziran_web.js'), '-lidbfs.js', '-sASYNCIFY',
                '-sALLOW_MEMORY_GROWTH=1', '-sEXPORTED_RUNTIME_METHODS=FS', '-sEXIT_RUNTIME=0', '-sSTACK_SIZE=16777216',
                '-sASYNCIFY_STACK_SIZE=1048576', '-o', str(out / 'test.js')], check=True, env=env)
(out / 'index.html').write_text('''<!doctype html><title>Progress storage</title><script>
var Module={preRun:[function(){
 const sync=FS.syncfs;let fail=false;
 globalThis.progressFlushFailure=value=>{fail=value};
 FS.syncfs=(populate,callback)=>fail&&!populate?setTimeout(()=>callback(Error('injected flush failure')),0):sync(populate,callback);
}]};</script><script src="test.js"></script>''')
subprocess.run(['node', 'tests/progress_browser_test.mjs'], check=True, env=env)

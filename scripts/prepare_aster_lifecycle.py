"""Patch A184's actual lifecycle methods, retaining desktop input and callbacks."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
PREFIX='Lcom/popcap/SexyAppFramework/'
ACT=PREFIX+'SexyAppFrameworkActivity;'
APP=PREFIX+'AndroidGameApp;'
VIEW=PREFIX+'AndroidSurfaceView;'
INPUT=PREFIX+'AndroidUIEventManager;'
FRAMES=PREFIX+'AsterBackgroundFrames;'
MUSIC='Lcom/popcap/pvz2cthd/PvpMusic;'
UPDATER='Lcom/popcap/pvz2cthd/ReleaseUpdater;'

def method(text,name):
    m=re.search(r'^\.method [^\n]* '+re.escape(name)+r'\([^\n]*\n.*?^\.end method',text,re.M|re.S)
    if not m:raise ValueError('Missing method '+name)
    return m[0]

def replace(text,name,body):
    old=method(text,name)
    return text.replace(old,body.strip(),1)

def patch_smali(folder):
    root=folder/'com/popcap/SexyAppFramework'
    p=root/'SexyAppFrameworkActivity.smali';s=p.read_text(encoding='utf8')
    if 'mAsterRunning' in s:raise ValueError('Lifecycle patch already applied')
    for name,expected in (('onPause','onActivityPause'),('onResume','onActivityResume'),('onStop','onActivityStop')):
        if expected not in method(s,name):raise ValueError('Unknown original '+name)
    pos=s.index('\n.method');s=s[:pos]+'\n.field private mAsterRunning:Z\n'+s[pos:]
    s=replace(s,'onResume',f'''
.method public onResume()V
    .locals 2
    invoke-super {{p0}}, Landroid/app/Activity;->onResume()V
    invoke-static {{p0}}, {UPDATER}->resume(Landroid/app/Activity;)V
    iget-boolean v0, p0, {ACT}->mAsterRunning:Z
    if-nez v0, :done
    iget-object v0, p0, {ACT}->mGameApp:{APP}
    if-eqz v0, :done
    iget-object v1, p0, {ACT}->mGLView:{VIEW}
    if-eqz v1, :done
    const/4 v0, 0x1
    invoke-static {{v0}}, {MUSIC}->setForeground(Z)V
    invoke-virtual {{v1}}, {VIEW}->onResume()V
    iget-object v0, p0, {ACT}->mGameApp:{APP}
    invoke-virtual {{v0}}, {APP}->onActivityResume()V
    iget-object v1, p0, {ACT}->mGLView:{VIEW}
    invoke-virtual {{v1}}, {VIEW}->requestFocus()Z
    const/4 v0, 0x1
    iput-boolean v0, p0, {ACT}->mAsterRunning:Z
    :done
    return-void
.end method''')
    s=replace(s,'onPause',f'''
.method public onPause()V
    .locals 0
    invoke-static {{p0}}, {UPDATER}->pause(Landroid/app/Activity;)V
    invoke-super {{p0}}, Landroid/app/Activity;->onPause()V
    return-void
.end method''')
    s=replace(s,'onStop',f'''
.method public onStop()V
    .locals 2
    invoke-super {{p0}}, Landroid/app/Activity;->onStop()V
    iget-object v0, p0, {ACT}->mGameApp:{APP}
    if-eqz v0, :done
    iget-boolean v1, p0, {ACT}->mAsterRunning:Z
    if-eqz v1, :stop
    const/4 v1, 0x0
    invoke-static {{v1}}, {MUSIC}->setForeground(Z)V
    invoke-virtual {{v0}}, {APP}->onActivityPause()V
    iget-object v1, p0, {ACT}->mGLView:{VIEW}
    invoke-virtual {{v1}}, {VIEW}->onPause()V
    const/4 v1, 0x0
    iput-boolean v1, p0, {ACT}->mAsterRunning:Z
    :stop
    iget-object v0, p0, {ACT}->mGameApp:{APP}
    invoke-virtual {{v0}}, {APP}->onActivityStop()V
    :done
    return-void
.end method''')
    s=replace(s,'onWindowFocusChanged',f'''
.method public onWindowFocusChanged(Z)V
    .locals 2
    invoke-super {{p0, p1}}, Landroid/app/Activity;->onWindowFocusChanged(Z)V
    iget-object v0, p0, {ACT}->mGameApp:{APP}
    if-eqz v0, :done
    iget-object v1, p0, {ACT}->mUIEventManager:{INPUT}
    if-eqz v1, :done
    if-eqz p1, :lost
    invoke-virtual {{v1}}, {INPUT}->HandleGotFocus()V
    invoke-virtual {{v0, p1}}, {APP}->onWindowFocusChanged(Z)V
    goto :done
    :lost
    invoke-virtual {{v1}}, {INPUT}->HandleLostFocus()V
    :done
    return-void
.end method''')
    p.write_text(s,encoding='utf8')

    p=root/'AndroidGameApp.smali';s=p.read_text(encoding='utf8');body=method(s,'onActivityPause')
    # Keep native resign/background, wake lock and PNS bookkeeping verbatim.
    start=body.index('    .line 209\n');end=body.index('    .line 225\n',start)
    if '->wait()V' not in body[start:end]:raise ValueError('Unknown pause handshake')
    body=body[:start]+f'''    iget-object v1, p0, {APP}->mGLView:{VIEW}
    invoke-static {{v1}}, {FRAMES}->awaitFrame({VIEW})V
    invoke-direct {{p0}}, {APP}->TryLoseFocus()V
'''+body[end:]
    s=replace(s,'onActivityPause',body);p.write_text(s,encoding='utf8')

    p=root/'AndroidSurfaceView.smali';s=p.read_text(encoding='utf8')
    for field,kind in (('mbDrawingFrames','Z'),('mbFocusState','Z'),('mbNotifyOnDrawEventObject','Ljava/lang/Object;')):
        before=f'.field public {field}:{kind}'
        if s.count(before)!=1:raise ValueError('Unknown surface field '+field)
        s=s.replace(before,f'.field public volatile {field}:{kind}')
    if '.method public onWindowFocusChanged(' in s:raise ValueError('Unexpected surface focus override')
    s+=f'''
.method public onWindowFocusChanged(Z)V
    .locals 1
    invoke-super {{p0, p1}}, Landroid/opengl/GLSurfaceView;->onWindowFocusChanged(Z)V
    if-nez p1, :done
    const/4 v0, 0x0
    iput-boolean v0, p0, {VIEW}->mDesktopRightDown:Z
    iput-boolean v0, p0, {VIEW}->mDesktopMiddleDown:Z
    :done
    return-void
.end method
'''
    p.write_text(s,encoding='utf8')
    p=root/'AndroidSurfaceView$AndroidRenderer.smali';s=p.read_text(encoding='utf8');body=method(s,'onDrawFrame')
    start=body.index('    .line 435\n');end=body.index('    .line 447\n',start)
    if '->notifyAll()V' not in body[start:end]:raise ValueError('Unknown renderer handshake')
    # Keep PresetEditor.frame(), splash/FPS handling and every native call.
    body=body[:start]+f'''    invoke-static {{p1}}, {FRAMES}->acknowledgeFrame({VIEW})Z
    move-result v2
    const/4 v1, 0x0
    if-nez v2, :draw
    iget-boolean v2, p1, {VIEW}->mbFocusState:Z
    if-nez v2, :draw
    return-void
    :draw
'''+body[end:]
    s=replace(s,'onDrawFrame',body);p.write_text(s,encoding='utf8')

def prepare(apk,output,sdk,jdk):
    output.mkdir(parents=True,exist_ok=True)
    tool=ROOT.parent/'tools/apktool.jar';cp=str(tool)+os.pathsep+str(output)
    def run(*args):subprocess.run([str(x) for x in args],check=True)
    with ZipFile(apk) as z:original=z.read('classes.dex')
    (output/'original.dex').write_bytes(original)
    run(jdk/'bin/javac.exe','-cp',tool,'-d',output,ROOT/'scripts/RepairDex.java')
    smali=output/'smali'
    if smali.exists():raise ValueError('Use a fresh output directory')
    run(jdk/'bin/java.exe','-Xmx512m','-cp',cp,'RepairDex','decode',output/'original.dex',smali)
    shutil.copytree(smali,output/'original-smali')
    patch_smali(smali)
    # Compile only the new helper against an API stub with the actual public
    # surface fields. The stub is never packaged; all game classes stay smali.
    stub=output/'api/com/popcap/SexyAppFramework/AndroidSurfaceView.java';stub.parent.mkdir(parents=True)
    stub.write_text('package com.popcap.SexyAppFramework; public class AndroidSurfaceView extends android.opengl.GLSurfaceView { public volatile boolean mbDrawingFrames,mbFocusState; public volatile Object mbNotifyOnDrawEventObject; public AndroidSurfaceView(android.content.Context c){super(c);} }')
    platform=sdk/'platforms/android-34/android.jar';classes=output/'classes';classes.mkdir()
    run(jdk/'bin/javac.exe','--release','8','-encoding','UTF-8','-cp',platform,'-d',classes,stub,ROOT/'src/desktop-lifecycle/com/popcap/SexyAppFramework/AsterBackgroundFrames.java')
    helper=output/'helper.jar'
    with ZipFile(helper,'w') as z:z.write(classes/'com/popcap/SexyAppFramework/AsterBackgroundFrames.class','com/popcap/SexyAppFramework/AsterBackgroundFrames.class')
    dex=output/'helper-dex';dex.mkdir()
    run(jdk/'bin/java.exe','-cp',sdk/'build-tools/34.0.0/lib/d8.jar','com.android.tools.r8.D8','--min-api','21','--lib',platform,'--output',dex,helper)
    helper_smali=output/'helper-smali'
    run(jdk/'bin/java.exe','-cp',cp,'RepairDex','decode',dex/'classes.dex',helper_smali)
    for file in helper_smali.rglob('*.smali'):
        dest=smali/file.relative_to(helper_smali)
        if dest.exists():raise ValueError('New helper conflicts with game')
        shutil.copyfile(file,dest)
    run(jdk/'bin/java.exe','-Xmx512m','-cp',cp,'RepairDex','encode',smali,output/'classes.dex')
    report=dict(source_dex_sha256=hashlib.sha256(original).hexdigest(),dex_sha256=hashlib.sha256((output/'classes.dex').read_bytes()).hexdigest(),iris_reference='I40',visible_focus_loss_keeps_running=True,hidden_window_suspends=True,background_wait_ms=250,runtime_accepted=False)
    (output/'lifecycle-patch.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','output','sdk','jdk'):p.add_argument(name,type=Path)
    prepare(**vars(p.parse_args()))

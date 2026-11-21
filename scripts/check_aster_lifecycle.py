"""Check actual patched DEX scope and execute lifecycle/handshake source on JVM."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,sys,zlib,struct
from prepare_aster_lifecycle import method as smali_method

ROOT=Path(__file__).resolve().parents[1]

def java_method(source,name):
    start=source.index('    public void '+name+'(');brace=source.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]

def check(folder,jdk):
    sys.path.insert(0,str(ROOT/'src/recovered/tools'))
    from build_dex_reference_jar import Dex
    original=(folder/'original.dex').read_bytes();patched=(folder/'classes.dex').read_bytes()
    before=folder/'original-smali';after=folder/'roundtrip-smali'
    # Decode the actual assembled DEX so reference relocation, retained methods
    # and the renderer tail are checked after the final assembly as well.
    subprocess.run([jdk/'bin/java.exe','-Xmx512m','-cp',str(ROOT.parent/'tools/apktool.jar')+';'+str(folder),'RepairDex','decode',folder/'classes.dex',after],check=True)
    changed=[]
    for file in before.rglob('*.smali'):
        rel=file.relative_to(before)
        if file.read_bytes()!=(after/rel).read_bytes():changed.append(rel.as_posix())
    prefix='com/popcap/SexyAppFramework/'
    expected={prefix+n+'.smali' for n in ('SexyAppFrameworkActivity','AndroidGameApp','AndroidSurfaceView','AndroidSurfaceView$AndroidRenderer')}
    assert set(changed)==expected,changed
    for name,allowed in (('SexyAppFrameworkActivity',{'onResume','onPause','onStop','onWindowFocusChanged'}),('AndroidGameApp',{'onActivityPause'}),('AndroidSurfaceView',set()),('AndroidSurfaceView$AndroidRenderer',{'onDrawFrame'})):
        a=(before/(prefix+name+'.smali')).read_text();b=(after/(prefix+name+'.smali')).read_text()
        for entry in re.finditer(r'^\.method[^\n]* ([^ (]+)\([^\n]*\n.*?^\.end method',a,re.M|re.S):
            if entry[1] not in allowed:assert entry[0]==smali_method(b,entry[1]),(name,entry[1])
    a=after/prefix
    activity=(a/'SexyAppFrameworkActivity.smali').read_text();app=(a/'AndroidGameApp.smali').read_text();surface=(a/'AndroidSurfaceView.smali').read_text();renderer=(a/'AndroidSurfaceView$AndroidRenderer.smali').read_text()
    assert 'onActivityPause' not in smali_method(activity,'onPause') and 'setForeground' not in smali_method(activity,'onPause')
    stop=smali_method(activity,'onStop');assert stop.index('onActivityPause')<stop.index('->onPause()')
    assert '->wait()V' not in smali_method(app,'onActivityPause')
    for field in ('mbDrawingFrames:Z','mbFocusState:Z','mbNotifyOnDrawEventObject:Ljava/lang/Object;'):assert '.field public volatile '+field in surface
    assert 'PresetEditor;->frame()V' in smali_method(renderer,'onDrawFrame')
    bdefs={d['name'] for d in Dex(original).classes()};defs={d['name'] for d in Dex(patched).classes()}
    assert defs-bdefs=={'Lcom/popcap/SexyAppFramework/AsterBackgroundFrames;'} and bdefs<=defs
    assert hashlib.sha1(patched[32:]).digest()==patched[12:32]
    assert zlib.adler32(patched[12:])&0xffffffff==struct.unpack_from('<I',patched,8)[0]
    strings=Dex(patched).strings;assert strings==sorted(strings)

    source=ROOT/'src/recovered/game_bridge/com/popcap/SexyAppFramework'
    activity=(source/'SexyAppFrameworkActivity.java').read_text()
    methods='\n'.join(java_method(activity,n) for n in ('onResume','onPause','onStop','onWindowFocusChanged'))
    methods=methods.replace('com.popcap.pvz2cthd.ReleaseUpdater','ReleaseUpdater').replace('com.popcap.pvz2cthd.PvpMusic','PvpMusic')
    helper=(ROOT/'src/desktop-lifecycle/com/popcap/SexyAppFramework/AsterBackgroundFrames.java').read_text()
    helper=helper[helper.index('public final class '):].replace('public final class AsterBackgroundFrames','static final class AsterBackgroundFrames').replace('android.os.SystemClock.uptimeMillis()','(System.nanoTime()/1000000)')
    focus=java_method((source/'AndroidSurfaceView.java').read_text(),'onWindowFocusChanged')
    harness=r'''
public class AsterLifecycleCheck {
 static void expect(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static class Log {static void i(String a,String b){}}
 static class ReleaseUpdater {static int pauses,resumes;static void pause(Object o){pauses++;}static void resume(Object o){resumes++;}}
 static class PvpMusic {static boolean foreground;static void setForeground(boolean b){foreground=b;}}
 static String order="";
 static class Base {public void onResume(){}public void onPause(){}public void onStop(){}public void onWindowFocusChanged(boolean f){}}
 static class App {int resumes,pauses,stops,focus;boolean manualPause;
  void onActivityResume(){resumes++;order+="appResume,";}
  void onActivityPause(){pauses++;order+="appPause,";}void onActivityStop(){stops++;}
  void onWindowFocusChanged(boolean f){expect(f,"native focus loss must not be sent");focus++;}
 }
 static class Input {int got,lost;boolean held,focused;
  void HandleLostFocus(){lost++;held=false;focused=false;}void HandleGotFocus(){got++;focused=true;}}
 static class AndroidSurfaceView extends Base {
  volatile boolean mbDrawingFrames,mbFocusState;volatile Object mbNotifyOnDrawEventObject;
  boolean mDesktopRightDown,mDesktopMiddleDown,acknowledge;int resumes,pauses;
  public void onResume(){resumes++;order+="glResume,";}public void onPause(){pauses++;order+="glPause,";}
  void requestFocus(){}void requestRender(){if(acknowledge)new Thread(()->AsterBackgroundFrames.acknowledgeFrame(this)).start();}
  FOCUS
 }
 static class Activity extends Base {
  boolean mAsterRunning;static boolean DEBUG=false;
  App mGameApp=new App();AndroidSurfaceView mGLView=new AndroidSurfaceView();Input mUIEventManager=new Input();
  METHODS
 }
 HELPER
 public static void main(String[] args)throws Exception {
  Activity a=new Activity();a.onResume();a.onWindowFocusChanged(true);
  expect(order.startsWith("glResume,appResume,"),"resume GL before native");
  a.mUIEventManager.held=true;a.mGLView.mDesktopRightDown=a.mGLView.mDesktopMiddleDown=true;
  a.mGLView.onWindowFocusChanged(false);a.onWindowFocusChanged(false);a.onPause();
  expect(a.mGameApp.pauses==0&&a.mGLView.pauses==0&&PvpMusic.foreground,"visible window keeps simulation/render/music");
  expect(!a.mUIEventManager.held&&!a.mUIEventManager.focused&&!a.mGLView.mDesktopRightDown&&!a.mGLView.mDesktopMiddleDown,"release held input only");
  a.onResume();a.onWindowFocusChanged(true);expect(a.mGameApp.resumes==1&&a.mUIEventManager.focused,"activation restores input without duplicate native resume");
  for(boolean paused:new boolean[]{false,true}){
   a.mGameApp.manualPause=paused;a.onPause();a.onWindowFocusChanged(false);a.onStop();a.onStop();
   expect(a.mGameApp.manualPause==paused&&!a.mAsterRunning&&!PvpMusic.foreground,"stop preserves manual pause and suspends music");
   expect(order.endsWith("appPause,glPause,"),"native background handshake before GL pause");
   a.onResume();a.onWindowFocusChanged(true);expect(a.mGameApp.manualPause==paused&&a.mAsterRunning&&PvpMusic.foreground,"restore manual pause unchanged");
  }
  expect(a.mGameApp.pauses==2&&a.mGLView.pauses==2&&a.mGameApp.resumes==3,"one suspend per stop cycle");
  Activity empty=new Activity();empty.mGameApp=null;empty.mGLView=null;empty.mUIEventManager=null;
  empty.onWindowFocusChanged(false);empty.onResume();empty.onPause();empty.onStop();
  AndroidSurfaceView v=new AndroidSurfaceView();long t=System.nanoTime();AsterBackgroundFrames.awaitFrame(v);
  expect(System.nanoTime()-t<100000000,"no wait before any frame");
  v.mbDrawingFrames=true;t=System.nanoTime();AsterBackgroundFrames.awaitFrame(v);
  expect(System.nanoTime()-t<1000000000L&&!v.mbDrawingFrames&&v.mbNotifyOnDrawEventObject==null,"destroyed surface timeout clears handshake");
  v.acknowledge=true;v.mbDrawingFrames=true;AsterBackgroundFrames.awaitFrame(v);expect(v.mbNotifyOnDrawEventObject==null,"renderer acknowledges");
  v.acknowledge=false;v.mbDrawingFrames=true;Thread.currentThread().interrupt();AsterBackgroundFrames.awaitFrame(v);
  expect(Thread.interrupted()&&v.mbNotifyOnDrawEventObject==null,"preserve interrupt and clear handshake");
  expect(!AsterBackgroundFrames.acknowledgeFrame(v),"late renderer after timeout is safe");
  for(int i=0;i<100;i++){v.acknowledge=true;v.mbDrawingFrames=true;AsterBackgroundFrames.awaitFrame(v);expect(v.mbNotifyOnDrawEventObject==null,"repeated handshake");}
  System.out.println("Lifecycle source JVM checks passed: visible running/music, held input, pause preservation, stop ordering, null teardown, bounded/acknowledged/interrupted handshake");
 }
}
'''.replace('METHODS',methods).replace('HELPER',helper).replace('FOCUS',focus)
    out=folder/'jvm';out.mkdir(exist_ok=True);path=out/'AsterLifecycleCheck.java';path.write_text(harness,encoding='utf8')
    subprocess.run([jdk/'bin/javac.exe','-encoding','UTF-8','-d',out,path],check=True)
    subprocess.run([jdk/'bin/java.exe','-cp',out,'AsterLifecycleCheck'],check=True)
    report=dict(dex_classes_before=len(bdefs),dex_classes_after=len(defs),changed_existing_classes=changed,unrelated_existing_methods_preserved=True,dex_checksum_and_string_order_valid=True,jvm_lifecycle_and_handshake_passed=True,native_engine_unchanged=True,runtime_accepted=False)
    (folder/'lifecycle-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('jdk',type=Path);check(**vars(p.parse_args()))

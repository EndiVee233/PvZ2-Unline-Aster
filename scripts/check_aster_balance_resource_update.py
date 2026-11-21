"""Execute the retained RGBA updater source against old/new resource generations."""
from pathlib import Path
import argparse,json,subprocess

ROOT=Path(__file__).resolve().parents[1]

def check(folder,jdk):
    out=folder/'update-jvm';out.mkdir(parents=True,exist_ok=True)
    files={
      'android/content/Context.java':'''package android.content; import java.io.*; public class Context {public final File root,assets;public Context(File r,File a){root=r;assets=a;}public File getExternalFilesDir(String ignored){return root;}public Context getApplicationContext(){return this;}public android.content.res.AssetManager getAssets(){return new android.content.res.AssetManager(assets);}}''',
      'android/content/res/AssetManager.java':'''package android.content.res;import java.io.*;public class AssetManager{private final File root;public AssetManager(File r){root=r;}public InputStream open(String n)throws IOException{return new FileInputStream(new File(root,n));}}''',
      'android/os/Process.java':'''package android.os;public class Process{public static final int THREAD_PRIORITY_BACKGROUND=10;public static void setThreadPriority(int ignored){}}''',
      'android/os/Build.java':'''package android.os;public class Build{public static String BRAND="Windows",MANUFACTURER="Microsoft Corporation",MODEL="Subsystem for Android(TM)",PRODUCT="windows_x86_64",DEVICE="windows_x86_64";}''',
      'android/system/Os.java':'''package android.system;import java.nio.file.*;public class Os{public static void rename(String a,String b)throws Exception{Files.move(Path.of(a),Path.of(b),StandardCopyOption.REPLACE_EXISTING);}}''',
      'android/util/Log.java':'''package android.util;public class Log{public static int i(String a,String b){return 0;}public static int w(String a,String b,Throwable t){throw new AssertionError(b,t);}}''',
      'UpdateCheck.java':r'''
import java.io.*;import java.nio.file.*;import java.security.*;import java.util.*;
import android.content.Context;import com.popcap.pvz2cthd.AsterRgbaPilot;
public class UpdateCheck{
 static File output,assets,source,reference,old;static int cases;
 static byte[] hash(File f)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(f)){byte[] b=new byte[262144];int n;while((n=in.read(b))!=-1)d.update(b,0,n);}return d.digest();}
 static void expect(boolean b){if(!b)throw new AssertionError("case "+cases);}
 static void copy(File a,File b)throws Exception{Files.copy(a.toPath(),b.toPath(),StandardCopyOption.REPLACE_EXISTING);}
 static File root(String name)throws Exception{File r=new File(output,name);r.mkdirs();Files.writeString(new File(r,"save-sentinel").toPath(),"untouched");for(String f:new String[]{"started","active"}){var field=AsterRgbaPilot.class.getDeclaredField(f);field.setAccessible(true);field.setBoolean(null,false);}return r;}
 static void proof(File root,byte[] sourceHash,File target)throws Exception{try(OutputStream out=new FileOutputStream(new File(root,".aster-dynamic-rgba-v1.sha256"))){out.write(sourceHash);out.write(hash(target));}}
 static void sentinel(File r)throws Exception{expect(Files.readString(new File(r,"save-sentinel").toPath()).equals("untouched"));cases++;}
 public static void main(String[] args)throws Exception{
  output=new File(args[0]);File patch=new File(args[1]);old=new File(args[2]);assets=new File(output,"assets");new File(assets,"reconstruction").mkdirs();
  source=new File(patch,"dynamic-balance.rsb.smf");reference=new File(patch,"dynamic-rgba.reference");
  copy(source,new File(assets,"reconstruction/dynamic-original-speed.rsb.smf"));copy(new File(patch,"aster-dynamic-rgba.plan"),new File(assets,"reconstruction/aster-dynamic-rgba.plan"));
  byte[] sourceHash=hash(source),oldSource=HexFormat.of().parseHex(args[3]);
  File r=root("old-rgba"),current=new File(r,"dynamic.rsb.smf");copy(old,current);proof(r,oldSource,current);Files.writeString(new File(r,".aster-dynamic-rgba-v1.next").toPath(),"stale");
  expect(AsterRgbaPilot.useReady(new Context(r,assets)));expect(Arrays.equals(hash(current),sourceHash));expect(!new File(r,".aster-dynamic-rgba-v1.sha256").exists());expect(!new File(r,".aster-dynamic-rgba-v1.next").exists());sentinel(r);
  r=root("new-source");current=new File(r,"dynamic.rsb.smf");copy(source,current);
  expect(AsterRgbaPilot.useReady(new Context(r,assets)));expect(Arrays.equals(hash(current),sourceHash));sentinel(r);
  r=root("ready-successor");current=new File(r,"dynamic.rsb.smf");copy(source,current);copy(reference,new File(r,".aster-dynamic-rgba-v1.next"));proof(r,sourceHash,reference);
  expect(AsterRgbaPilot.useReady(new Context(r,assets)));expect(Arrays.equals(hash(current),hash(reference)));expect(!new File(r,".aster-dynamic-rgba-v1.next").exists());sentinel(r);
  r=root("already-new-rgba");current=new File(r,"dynamic.rsb.smf");copy(reference,current);proof(r,sourceHash,reference);long modified=current.lastModified();
  expect(AsterRgbaPilot.useReady(new Context(r,assets)));expect(current.lastModified()==modified&&Arrays.equals(hash(current),hash(reference)));sentinel(r);
  r=root("corrupt-successor");current=new File(r,"dynamic.rsb.smf");copy(source,current);proof(r,sourceHash,reference);Files.writeString(new File(r,".aster-dynamic-rgba-v1.next").toPath(),"truncated");
  expect(AsterRgbaPilot.useReady(new Context(r,assets)));expect(Arrays.equals(hash(current),sourceHash));expect(!new File(r,".aster-dynamic-rgba-v1.next").exists());sentinel(r);
  android.os.Build.BRAND="OnePlus";expect(!AsterRgbaPilot.usesWsaTextureDecoder());
  r=root("native-upgrade");current=new File(r,"dynamic.rsb.smf");Context nativeContext=new Context(r,assets);
  copy(reference,current);proof(r,sourceHash,reference);
  String prefix=".aster-dynamic-rgba-v1.";
  for(String suffix:new String[]{"next","partial","proof","restore"})Files.writeString(new File(r,prefix+suffix).toPath(),"stale");
  expect(AsterRgbaPilot.useReady(nativeContext));expect(Arrays.equals(hash(current),sourceHash));
  for(String suffix:new String[]{"next","partial","proof","restore","sha256"})expect(!new File(r,prefix+suffix).exists());sentinel(r);
  long nativeModified=current.lastModified();copy(reference,new File(r,prefix+"next"));proof(r,sourceHash,reference);
  expect(AsterRgbaPilot.useReady(nativeContext));expect(current.lastModified()==nativeModified);
  expect(!new File(r,prefix+"next").exists()&&!new File(r,prefix+"sha256").exists());
  AsterRgbaPilot.start(nativeContext);var started=AsterRgbaPilot.class.getDeclaredField("started");
  started.setAccessible(true);expect(!started.getBoolean(null));sentinel(r);
  File packaged=new File(assets,"reconstruction/dynamic-original-speed.rsb.smf");
  copy(reference,current);Files.writeString(packaged.toPath(),"incomplete");boolean failed=false;
  try{AsterRgbaPilot.useReady(nativeContext);}catch(IOException e){failed=true;}finally{copy(source,packaged);}
  expect(failed&&Arrays.equals(hash(current),hash(reference)));expect(!new File(r,prefix+"restore").exists());sentinel(r);
  System.out.println("Resource generation JVM scenarios passed: "+cases);
 }
}'''}
    for name,text in files.items():
        path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf8')
    classes=out/'classes';classes.mkdir(exist_ok=True)
    helper=ROOT/'src/bootstrap-extra/com/popcap/pvz2cthd/AsterRgbaPilot.java'
    subprocess.run([jdk/'bin/javac.exe','-encoding','UTF-8','-d',classes,*[out/n for n in files],helper],check=True)
    evidence=json.loads((folder/'balance-patch.json').read_text())
    subprocess.run([jdk/'bin/java.exe','-cp',classes,'UpdateCheck',out,folder,folder.parent/'device-dynamic-before.smf',evidence['source_resource_sha256']],check=True)
    result=dict(resource_generation_jvm_scenarios_passed=8,old_device_rgba_invalidated_and_replaced=True,new_source_and_rgba_successors_accepted=True,non_wsa_restores_compressed_and_skips_worker=True,unrelated_save_sentinel_preserved=True,android_rendering_and_on_device_bake_tested=False)
    (folder/'resource-update-checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('jdk',type=Path);check(**vars(p.parse_args()))

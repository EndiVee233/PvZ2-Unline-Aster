package com.popcap.pvz2cthd;

import android.content.Context;
import android.util.Log;
import java.io.*;
import java.lang.reflect.*;
import java.math.BigDecimal;
import java.util.*;
import org.json.*;

/** Retires the pre-v193 automatic import before the native player registry opens. */
public final class PresetProfileImporter {
    static final int LIMIT = 8 * 1024 * 1024;
    private PresetProfileImporter() {}

    public static synchronized void apply(Context context) {
        File folder = new File(context.getFilesDir(), "userdataNo_Backup");
        File done = new File(folder, ".test-profile-migrated-A193");
        if (done.exists() || !folder.isDirectory()) return;
        File scratch = new File(context.getCacheDir(), "preset-import-v86");
        try {
            if (!scratch.isDirectory() && !scratch.mkdirs()) throw new IOException("scratch");
            // A recovered native backup must obey the same rule as the primary.
            boolean complete = true;
            for (String name : new String[]{"pp.dat", "pp.dat.bak", "pp.dat_.bak"}) {
                try { retireLegacy(new File(folder, name), scratch); }
                catch (Exception error) {
                    complete = false;
                    Log.e("PresetImport", "migration deferred for " + name + ": " + error.getClass().getSimpleName());
                }
            }
            if (complete) write(done, new byte[]{1});
        } catch (Exception error) {
            Log.e("PresetImport", "migration deferred: " + error.getClass().getSimpleName());
        } finally { clean(scratch); }
    }

    static boolean retireLegacy(File save, File scratch) throws Exception {
        if (!save.isFile()) return false;
        byte[] before = read(save);
        JSONObject expected = decode(save, new File(scratch, "before.json"));
        JSONArray rows = expected.getJSONArray("objects");
        boolean changed = false;
        for (int i = rows.length() - 1; i >= 0; --i) {
            JSONObject obj = rows.optJSONObject(i);
            if (obj == null || !"PlayerInfo".equals(obj.optString("objclass"))) continue;
            // v86 allocated 1.0.7e860001..400 and kept the shipped PlayerInfo.i.
            // v86's marker alone is insufficient: its name fallback could adopt
            // a real player. The UID and original identity survive renaming.
            String uid = obj.optString("uid").toLowerCase(Locale.ROOT);
            if (!uid.matches("1\\.0\\.7e86[0-9a-f]{4}")) continue;
            int suffix = Integer.parseInt(uid.substring(8), 16);
            JSONObject data = obj.optJSONObject("objdata");
            if (suffix >= 1 && suffix <= 0x400 && data != null && data.optLong("i") == 1722523140L) {
                rows.remove(i);
                changed = true;
            }
        }
        if (!changed) return false;
        File json = new File(scratch, "merged.json"), encoded = new File(scratch, "merged.dat");
        write(json, expected.toString().getBytes("UTF-8"));
        codec("encodeAndEncrypt", json, encoded);
        if (!same(expected, decode(encoded, new File(scratch, "checked.json"))))
            throw new IOException("roundtrip mismatch");
        if (!Arrays.equals(before, read(save))) throw new IOException("save changed");
        File temp = new File(save.getPath() + ".migration.tmp");
        try {
            write(temp, read(encoded));
            if (!temp.renameTo(save)) throw new IOException("save replace");
        } finally { temp.delete(); }
        return true;
    }

    static JSONObject decode(File source, File json) throws Exception {
        codec("decodeAuto", source, json);
        return new JSONObject(new String(read(json), "UTF-8"));
    }

    // Reuse the APK's own RTON/crypto implementation. Its API is suspending;
    // runBlocking waits for completion instead of passing a null continuation.
    static void codec(final String operation, final File input, final File output) throws Exception {
        if (output.exists() && !output.delete()) throw new IOException("stale codec output");
        final Class<?> continuation = Class.forName("kotlin.coroutines.Continuation");
        Class<?> function = Class.forName("kotlin.jvm.functions.Function2");
        Class<?> coroutineContext = Class.forName("kotlin.coroutines.CoroutineContext");
        final Object rton = Class.forName("io.github.dreammooncai.pvz2tool.pop.rton.RTON").getConstructor().newInstance();
        final Method convert = rton.getClass().getMethod(operation, File.class, File.class, continuation);
        Object block = Proxy.newProxyInstance(function.getClassLoader(), new Class<?>[]{function}, new InvocationHandler() {
            public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
                if ("invoke".equals(method.getName())) {
                    try { return convert.invoke(rton, input, output, args[1]); }
                    catch (InvocationTargetException e) { throw e.getCause(); }
                }
                if ("toString".equals(method.getName())) return "PresetCodec";
                if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                if ("equals".equals(method.getName())) return proxy == args[0];
                throw new UnsupportedOperationException(method.getName());
            }
        });
        Method run = Class.forName("kotlinx.coroutines.BuildersKt").getMethod("runBlocking$default", coroutineContext, function, int.class, Object.class);
        try { run.invoke(null, null, block, 1, null); }
        catch (InvocationTargetException e) { throw new IOException("codec " + operation, e.getCause()); }
        if (!output.isFile() || output.length()==0 || output.length()>LIMIT) throw new IOException("codec output");
    }

    static boolean same(Object a,Object b) throws JSONException {
        if (a==JSONObject.NULL || b==JSONObject.NULL) return a==b;
        if (a instanceof JSONObject && b instanceof JSONObject) {
            JSONObject x=(JSONObject)a,y=(JSONObject)b;
            if(x.length()!=y.length())return false;
            Iterator<String> keys=x.keys();while(keys.hasNext()){String k=keys.next();if(!y.has(k)||!same(x.get(k),y.get(k)))return false;}
            return true;
        }
        if(a instanceof JSONArray && b instanceof JSONArray){JSONArray x=(JSONArray)a,y=(JSONArray)b;if(x.length()!=y.length())return false;for(int i=0;i<x.length();++i)if(!same(x.get(i),y.get(i)))return false;return true;}
        if(a instanceof Number && b instanceof Number)return new BigDecimal(a.toString()).compareTo(new BigDecimal(b.toString()))==0;
        return a!=null && a.equals(b);
    }
    static byte[] read(File file) throws IOException {InputStream in=new FileInputStream(file);try{return read(in);}finally{in.close();}}
    static byte[] read(InputStream in) throws IOException {ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))!=-1){if(out.size()+n>LIMIT)throw new IOException("size");out.write(buffer,0,n);}return out.toByteArray();}
    static void write(File file,byte[] data) throws IOException {FileOutputStream out=new FileOutputStream(file);try{out.write(data);out.getFD().sync();}finally{out.close();}}
    static void clean(File folder) {File[] files=folder.listFiles();if(files!=null)for(File f:files)if(f.isFile())f.delete();folder.delete();}
}

package com.popcap.pvz2cthd;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.*;

/** Portable backups of Aster's game files, using the Android document picker. */
public final class AsterSaveBackup {
    private static final String TAG = "AsterSaveBackup";
    private static final int SAVE = 20805, OPEN = 20806;
    private static final String PENDING = ".aster-pending-restore";
    private static final String META = "aster-save.json";
    private static final String PROFILE = "files/userdataNo_Backup/pp.dat";
    private static final String PUBLIC_IDS = "shared_prefs/adventure-share.xml";
    private static final String[] FOLDERS = {"files/userdata", "files/userdataNo_Backup"};
    private static final Set<String> DEVICE_FILES = new HashSet<>(Arrays.asList(
            "phoneid.dat", "networkcache.dat", "tlogcache.dat", "pvz2_log.txt", "resumableDownload"));
    private static final int MAX_FILE = 16 * 1024 * 1024, MAX_TOTAL = 64 * 1024 * 1024, MAX_ENTRIES = 4096;
    private static final ExecutorService WORK = Executors.newSingleThreadExecutor();
    private static boolean busy;
    private static AlertDialog dialog;

    private AsterSaveBackup() {}

    static void show(Activity activity) {
        if (busy || dialog != null || !activity.hasWindowFocus()) return;
        dialog = new AlertDialog.Builder(activity).setTitle("外置存档")
                .setItems(new String[]{"导出存档备份", "从备份恢复"}, (shown, item) -> openPicker(activity, item == 0))
                .setNegativeButton("关闭", null).create();
        dialog.setOnDismissListener(shown -> dialog = null);
        dialog.show();
    }

    private static void openPicker(Activity activity, boolean save) {
        Intent intent = new Intent(save ? Intent.ACTION_CREATE_DOCUMENT : Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType(save ? "application/zip" : "*/*");
        if (save) {
            String date = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date());
            intent.putExtra(Intent.EXTRA_TITLE, "Aster-save-" + date + ".zip");
        }
        try {
            activity.startActivityForResult(intent, save ? SAVE : OPEN);
        } catch (RuntimeException error) {
            toast(activity, "无法打开系统文件选择器");
        }
    }

    static boolean onResult(Activity activity, int request, int result, Intent intent) {
        if (request != SAVE && request != OPEN) return false;
        if (busy || result != Activity.RESULT_OK || intent == null || intent.getData() == null) return true;
        Uri uri = intent.getData();
        busy = true;
        WORK.execute(() -> {
            File temp = null;
            try {
                File root = data(activity);
                temp = File.createTempFile("aster-save-", ".zip", activity.getCacheDir());
                if (request == SAVE) {
                    try {
                        create(root, temp);
                    } catch (Changed first) {
                        create(root, temp);
                    }
                    try (InputStream input = new FileInputStream(temp);
                         OutputStream output = activity.getContentResolver().openOutputStream(uri, "wt")) {
                        if (output == null) throw new IOException("Document is not writable");
                        copy(input, output, MAX_TOTAL + MAX_FILE);
                    }
                    finish(activity, "存档备份已保存");
                } else {
                    if (pending(activity).exists()) throw new IOException("A restore is already pending");
                    try (InputStream input = activity.getContentResolver().openInputStream(uri);
                         FileOutputStream output = new FileOutputStream(temp)) {
                        if (input == null) throw new IOException("Document is not readable");
                        copy(input, output, MAX_TOTAL + MAX_FILE);
                    }
                    File stage = createStage(activity);
                    try {
                        extract(temp, new File(stage, "incoming"));
                    } catch (Exception error) {
                        removeTree(stage);
                        throw error;
                    }
                    activity.runOnUiThread(() -> confirmRestore(activity, stage));
                }
            } catch (Exception error) {
                Log.w(TAG, "Backup operation failed", error);
                finish(activity, request == SAVE ? "备份未完成，请重试" : "无法恢复，请检查备份文件");
            } finally {
                if (temp != null) temp.delete();
            }
        });
        return true;
    }

    private static void confirmRestore(Activity activity, File stage) {
        if (activity.isFinishing() || activity.isDestroyed()) {
            WORK.execute(() -> removeTree(stage));
            busy = false;
            return;
        }
        new AlertDialog.Builder(activity).setTitle("恢复存档")
                .setMessage("游戏退出后，下次启动会载入这份备份。当前存档会在恢复前另存一份。")
                .setNegativeButton("取消", (shown, choice) -> cancelRestore(stage))
                .setOnCancelListener(shown -> cancelRestore(stage))
                .setPositiveButton("恢复并退出", (shown, choice) -> {
                    try {
                        rename(stage, pending(activity));
                        activity.finishAffinity();
                        android.os.Process.killProcess(android.os.Process.myPid());
                    } catch (IOException error) {
                        cancelRestore(stage);
                        toast(activity, "无法安排恢复，请重试");
                    }
                }).show();
    }

    private static void cancelRestore(File stage) {
        busy = false;
        WORK.execute(() -> removeTree(stage));
    }

    private static void finish(Activity activity, String message) {
        activity.runOnUiThread(() -> {
            busy = false;
            if (!activity.isFinishing() && !activity.isDestroyed()) toast(activity, message);
        });
    }

    private static void toast(Activity activity, String message) {
        Toast.makeText(activity, message, Toast.LENGTH_LONG).show();
    }

    private static File data(Context context) throws IOException {
        return new File(context.getApplicationInfo().dataDir).getCanonicalFile();
    }

    private static File pending(Context context) {
        return new File(context.getFilesDir(), PENDING);
    }

    private static File createStage(Context context) throws IOException {
        File stage = File.createTempFile(".aster-stage-", "", context.getFilesDir());
        if (!stage.delete() || !stage.mkdir()) throw new IOException("Could not stage restore");
        return stage;
    }

    private static boolean saveName(String path) {
        if (PUBLIC_IDS.equals(path)) return true;
        String root = path.startsWith(FOLDERS[0] + "/") ? FOLDERS[0] : FOLDERS[1];
        if (!path.startsWith(root + "/") || path.length() > 300 || path.indexOf('\\') >= 0 || path.indexOf(':') >= 0) return false;
        String[] parts = path.substring(root.length() + 1).split("/", -1);
        if (parts.length > 10 || DEVICE_FILES.contains(parts[0])) return false;
        for (String part : parts) {
            if (part.isEmpty() || part.equals(".") || part.equals("..") || part.endsWith(".tmp")
                    || part.startsWith("adventure-test-")) return false;
            for (int i = 0; i < part.length(); ++i) if (Character.isISOControl(part.charAt(i))) return false;
        }
        return true;
    }

    private static Map<String, File> files(File data) throws IOException {
        Map<String, File> found = new TreeMap<>();
        for (String folder : FOLDERS) collect(data, folder, found);
        File identity = new File(data, PUBLIC_IDS);
        if (identity.isFile() && identity.equals(identity.getCanonicalFile())) found.put(PUBLIC_IDS, identity);
        if (!found.containsKey(PROFILE) || found.get(PROFILE).length() == 0) throw new IOException("No existing save");
        return found;
    }

    private static void collect(File data, String path, Map<String, File> found) throws IOException {
        File file = new File(data, path);
        if (!file.getCanonicalFile().equals(file) || !file.exists()) return;
        if (file.isDirectory()) {
            String[] children = file.list();
            if (children == null) throw new IOException("Could not list save folder");
            for (String child : children) {
                String entry = path + "/" + child;
                if (saveName(entry)) collect(data, entry, found);
            }
        } else if (file.isFile() && saveName(path)) {
            if (found.size() >= MAX_ENTRIES) throw new IOException("Too many save files");
            found.put(path, file);
        }
    }

    private static final class Changed extends IOException {
        Changed() { super("Save changed during backup"); }
    }

    static void create(File data, File destination) throws Exception {
        Map<String, File> files = files(data);
        JSONObject hashes = new JSONObject();
        int total = 0;
        try (ZipOutputStream zip = new ZipOutputStream(new BufferedOutputStream(new FileOutputStream(destination)))) {
            for (Map.Entry<String, File> entry : files.entrySet()) {
                byte[] bytes = read(new FileInputStream(entry.getValue()), Math.min(MAX_FILE, MAX_TOTAL - total));
                total += bytes.length;
                zip.putNextEntry(new ZipEntry(entry.getKey()));
                zip.write(bytes);
                zip.closeEntry();
                hashes.put(entry.getKey(), sha(bytes));
            }
            Map<String, File> after = files(data);
            if (!files.keySet().equals(after.keySet())) throw new Changed();
            for (Map.Entry<String, File> entry : after.entrySet()) {
                if (!hashes.getString(entry.getKey()).equals(sha(read(new FileInputStream(entry.getValue()), MAX_FILE)))) {
                    throw new Changed();
                }
            }
            JSONObject meta = new JSONObject().put("format", "pvz2-aster-save").put("version", 1).put("files", hashes);
            zip.putNextEntry(new ZipEntry(META));
            zip.write(meta.toString().getBytes(StandardCharsets.UTF_8));
            zip.closeEntry();
        }
    }

    static void extract(File archive, File incoming) throws Exception {
        try (ZipFile zip = new ZipFile(archive)) {
            ZipEntry manifest = zip.getEntry(META);
            if (manifest == null || manifest.isDirectory()) throw new IOException("Backup manifest missing");
            byte[] contents = read(zip.getInputStream(manifest), 1024 * 1024);
            PvpPresetDocument.checkDepth(contents);
            JSONObject meta = new JSONObject(new String(contents, StandardCharsets.UTF_8));
            if (!"pvz2-aster-save".equals(meta.getString("format")) || meta.getInt("version") != 1) {
                throw new IOException("Unsupported backup");
            }
            JSONObject hashes = meta.getJSONObject("files");
            if (!hashes.has(PROFILE) || hashes.length() > MAX_ENTRIES || zip.size() != hashes.length() + 1) {
                throw new IOException("Backup has missing or extra files");
            }
            for (String folder : FOLDERS) mkdir(new File(incoming, folder));
            Set<String> seen = new HashSet<>();
            int total = 0;
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String name = entry.getName();
                if (!seen.add(name)) throw new IOException("Duplicate file in backup");
                if (name.equals(META)) continue;
                if (entry.isDirectory() || !saveName(name)) throw new IOException("Invalid backup path");
                byte[] bytes = read(zip.getInputStream(entry), Math.min(MAX_FILE, MAX_TOTAL - total));
                total += bytes.length;
                if ((PROFILE.equals(name) && bytes.length == 0) || !sha(bytes).equals(hashes.getString(name))) {
                    throw new IOException("Backup checksum mismatch");
                }
                File target = new File(incoming, name);
                mkdir(target.getParentFile());
                try (FileOutputStream output = new FileOutputStream(target)) {
                    output.write(bytes);
                    output.getFD().sync();
                }
            }
        }
    }

    /** Called in bootstrap before the player registry is loaded. Renames resume safely after interruption. */
    public static void applyPending(Context context) throws IOException {
        File transaction = pending(context);
        if (!transaction.isDirectory()) return;
        File root = data(context);
        File previous = new File(transaction, "previous");
        File incoming = new File(transaction, "incoming");
        for (String path : FOLDERS) {
            promote(path, root, incoming, previous);
            File old = new File(previous, path);
            File active = new File(root, path);
            for (String name : DEVICE_FILES) {
                File held = new File(old, name);
                File local = new File(active, name);
                if (held.exists() && !local.exists()) rename(held, local);
            }
        }
        if (new File(incoming, PUBLIC_IDS).isFile()) promote(PUBLIC_IDS, root, incoming, previous);
        if (!new File(root, PROFILE).isFile()) throw new IOException("Restored save missing");
        rename(transaction, new File(context.getFilesDir(), ".aster-before-restore-" + System.currentTimeMillis()));
        Log.i(TAG, "Verified external backup installed");
    }

    private static void promote(String path, File root, File incoming, File previous) throws IOException {
        File next = new File(incoming, path);
        File active = new File(root, path);
        File old = new File(previous, path);
        if (next.exists()) {
            if (active.exists() && !old.exists()) {
                mkdir(old.getParentFile());
                rename(active, old);
            }
            mkdir(active.getParentFile());
            rename(next, active);
        }
        if (!active.exists()) throw new IOException("Staged save unavailable: " + path);
    }

    private static void mkdir(File directory) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Could not create save folder");
    }

    private static void rename(File from, File to) throws IOException {
        try {
            Os.rename(from.getPath(), to.getPath());
        } catch (ErrnoException error) {
            throw new IOException("Could not install staged save", error);
        }
    }

    private static void removeTree(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) removeTree(child);
        file.delete();
    }

    private static byte[] read(InputStream source, int max) throws IOException {
        try (InputStream input = source; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            copy(input, out, max);
            return out.toByteArray();
        }
    }

    private static void copy(InputStream input, OutputStream output, int remaining) throws IOException {
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (count > remaining) throw new IOException("Backup exceeds size limit");
            output.write(buffer, 0, count);
            remaining -= count;
        }
    }

    private static String sha(byte[] bytes) {
        try {
            StringBuilder result = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes)) {
                result.append(Character.forDigit((value & 255) >>> 4, 16)).append(Character.forDigit(value & 15, 16));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException unavailable) {
            throw new AssertionError(unavailable);
        }
    }
}

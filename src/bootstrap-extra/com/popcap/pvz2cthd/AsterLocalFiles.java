package com.popcap.pvz2cthd;

import android.content.Context;
import android.util.Log;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.Locale;

public final class AsterLocalFiles {
    private static final String TAG = "AsterLocalFiles";

    private AsterLocalFiles() {}

    public static String assetInfo(Context context, String name, long[] info) {
        File file = asset(context, name);
        if (file == null) return null;
        info[0] = 0;
        info[1] = file.length();
        Log.i(TAG, "Using local asset " + file.getPath());
        return file.getPath();
    }

    public static long assetSize(Context context, String name) {
        File file = asset(context, name);
        return file == null ? -1 : file.length();
    }

    private static File asset(Context context, String requested) {
        if (requested == null || !requested.startsWith("ASSET:")) return null;
        String name = requested.substring(6).replace('\\', '/');
        if (name.isEmpty() || name.startsWith("/") || name.indexOf(':') >= 0) return null;
        for (String part : name.split("/", -1))
            if (part.isEmpty() || part.equals(".") || part.equals("..")) return null;
        String extension = name.toLowerCase(Locale.ROOT);
        if (!extension.endsWith(".rton") && !extension.endsWith(".json") &&
                !extension.endsWith(".rtbo") && !extension.endsWith(".rsb") &&
                !extension.endsWith(".rsb.tag") && !extension.endsWith(".smf")) return null;

        File internal = context.getFilesDir();
        File external = context.getExternalFilesDir(null);
        File file = lookup(internal, name);
        if (file != null || external == null) return file;
        file = contained(new File(external, "dev"), name);
        if (file != null) return file;
        file = contained(external.getParentFile(), name);
        if (file != null || extension.endsWith(".rsb") || extension.endsWith(".rsb.smf")) return file;
        return contained(external, name);
    }

    static File dynamicOverride(Context context) {
        File internal = context.getFilesDir();
        File external = context.getExternalFilesDir(null);
        File result = lookup(internal, "dynamic.rsb.smf");
        if (result != null || external == null) return result;
        result = contained(new File(external, "dev"), "dynamic.rsb.smf");
        return result != null ? result : contained(external.getParentFile(), "dynamic.rsb.smf");
    }

    private static File lookup(File root, String name) {
        if (root == null) return null;
        File file = contained(new File(root, "dev"), name);
        return file != null ? file : contained(root, name);
    }

    private static File contained(File folder, String name) {
        if (folder == null) return null;
        try {
            File root = folder.getCanonicalFile();
            File file = new File(root, name).getCanonicalFile();
            if (!file.getPath().startsWith(root.getPath() + File.separator)) return null;
            if (file.isFile() && file.canRead() && file.length() > 0) return file;
            if (!name.endsWith(".smf")) return contained(folder, name + ".smf");
        } catch (IOException | SecurityException ignored) {
            // Continue with the installed resources.
        }
        return null;
    }

    static boolean isBundle(File file) {
        if (file == null || !file.isFile() || file.length() < 4096 ||
                file.length() > Integer.MAX_VALUE) return false;
        try (RandomAccessFile in = new RandomAccessFile(file, "r")) {
            if (in.readInt() != 0x31627372) return false; // 1bsr
            in.seek(12);
            int headerLength = Integer.reverseBytes(in.readInt());
            return headerLength >= 112 && headerLength < in.length() &&
                    (headerLength & 4095) == 0;
        } catch (IOException | SecurityException ignored) {
            return false;
        }
    }
}

package com.popcap.pvz2cthd;

import android.content.Context;
import android.util.Log;
import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.zip.InflaterInputStream;

public final class AsterZombossArt {
    private static final String TAG = "AsterZombossArt";
    private static final int MAGIC = 0x415a4231; // AZB1
    private static final int MAX_ARCHIVE_SIZE = 256 * 1024 * 1024;

    private AsterZombossArt() {}

    public static void apply(Context context) {
        File root = context.getExternalFilesDir(null);
        if (root == null) return;
        File bundle = new File(root, "zombie1.rsb.smf");
        if (!bundle.isFile()) return;
        File staged = new File(root, "zombie1-aster-zomboss.tmp");
        try (DataInputStream patch = new DataInputStream(new BufferedInputStream(new InflaterInputStream(
                context.getAssets().open("reconstruction/aster-zomboss-art.patch"))))) {
            if (patch.readInt() != MAGIC) throw new IOException("Invalid Zomboss patch header");
            int originalLength = patch.readInt();
            int targetLength = patch.readInt();
            int edits = patch.readInt();
            if (originalLength <= 0 || originalLength > MAX_ARCHIVE_SIZE || targetLength <= 0 ||
                    targetLength > MAX_ARCHIVE_SIZE || edits <= 0 || edits > 16) {
                throw new IOException("Invalid Zomboss patch dimensions");
            }
            byte[] originalHash = new byte[32];
            byte[] targetHash = new byte[32];
            patch.readFully(originalHash);
            patch.readFully(targetHash);
            if (bundle.length() != originalLength && bundle.length() != targetLength) {
                Log.w(TAG, "Unrecognized zombie1 archive size");
                return;
            }
            byte[] buffer = new byte[64 * 1024];
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (FileInputStream input = new FileInputStream(bundle)) {
                for (int count; (count = input.read(buffer)) != -1;) digest.update(buffer, 0, count);
            }
            byte[] installed = digest.digest();
            if (Arrays.equals(installed, targetHash)) return;
            if (!Arrays.equals(installed, originalHash)) {
                Log.w(TAG, "Unrecognized zombie1 archive checksum");
                return;
            }

            try (RandomAccessFile source = new RandomAccessFile(bundle, "r");
                 FileOutputStream file = new FileOutputStream(staged);
                 DigestOutputStream output = new DigestOutputStream(file, digest)) {
                int cursor = 0;
                long written = 0;
                for (int i = 0; i < edits; i++) {
                    int offset = patch.readInt();
                    int oldLength = patch.readInt();
                    int newLength = patch.readInt();
                    if (offset < cursor || offset > originalLength || oldLength < 0 ||
                            oldLength > originalLength - offset || newLength < 0) {
                        throw new IOException("Invalid Zomboss patch span");
                    }
                    int unchanged = offset - cursor;
                    written += (long) unchanged + newLength;
                    if (written > targetLength) throw new IOException("Zomboss patch is too large");
                    for (int left = unchanged; left > 0;) {
                        int count = Math.min(left, buffer.length);
                        source.readFully(buffer, 0, count);
                        output.write(buffer, 0, count);
                        left -= count;
                    }
                    cursor = offset + oldLength;
                    source.seek(cursor);
                    for (int left = newLength; left > 0;) {
                        int count = Math.min(left, buffer.length);
                        patch.readFully(buffer, 0, count);
                        output.write(buffer, 0, count);
                        left -= count;
                    }
                }
                if (written + originalLength - cursor != targetLength || patch.read() != -1) {
                    throw new IOException("Zomboss patch length differs");
                }
                for (int left = originalLength - cursor; left > 0;) {
                    int count = Math.min(left, buffer.length);
                    source.readFully(buffer, 0, count);
                    output.write(buffer, 0, count);
                    left -= count;
                }
                if (!Arrays.equals(digest.digest(), targetHash)) {
                    throw new IOException("Zomboss patch checksum differs");
                }
                file.getFD().sync();
            }
            if (!staged.renameTo(bundle)) throw new IOException("Could not install Zomboss artwork");
            Log.i(TAG, "Installed the Egyptian Zomboss teleport artwork");
        } catch (IOException | NoSuchAlgorithmException failure) {
            Log.w(TAG, "Could not update Zomboss artwork", failure);
        } finally {
            if (staged.exists()) staged.delete();
        }
    }
}

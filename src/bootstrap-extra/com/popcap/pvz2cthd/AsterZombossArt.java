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
    private static final int MAGIC = 0x415a4232; // AZB2
    private static final int MAX_ARCHIVE_SIZE = 256 * 1024 * 1024;

    private AsterZombossArt() {}

    private static DataInputStream openPatch(Context context) throws IOException {
        return new DataInputStream(new BufferedInputStream(new InflaterInputStream(
                context.getAssets().open("reconstruction/aster-zomboss-art.patch"))));
    }

    private static final class PatchHeader {
        static final int TARGET = -2;
        static final int UNKNOWN = -1;
        final int targetLength;
        final int edits;
        final byte[] targetHash = new byte[32];
        final int[] inputLengths;
        final byte[][] inputHashes;

        PatchHeader(DataInputStream patch) throws IOException {
            if (patch.readInt() != MAGIC) throw new IOException("Invalid Zomboss patch header");
            targetLength = patch.readInt();
            edits = patch.readInt();
            int inputs = patch.readInt();
            if (targetLength <= 0 || targetLength > MAX_ARCHIVE_SIZE || edits <= 0 ||
                    edits > 16 || inputs <= 0 || inputs > 4) {
                throw new IOException("Invalid Zomboss patch dimensions");
            }
            patch.readFully(targetHash);
            inputLengths = new int[inputs];
            inputHashes = new byte[inputs][32];
            for (int i = 0; i < inputs; i++) {
                inputLengths[i] = patch.readInt();
                patch.readFully(inputHashes[i]);
            }
        }

        int match(File archive, MessageDigest digest, byte[] buffer) throws IOException {
            long size = archive.length();
            boolean knownSize = size == targetLength;
            for (int length : inputLengths) knownSize |= size == length;
            if (!knownSize) return UNKNOWN;

            try (FileInputStream input = new FileInputStream(archive)) {
                for (int count; (count = input.read(buffer)) != -1;) digest.update(buffer, 0, count);
            }
            byte[] hash = digest.digest();
            if (size == targetLength && Arrays.equals(hash, targetHash)) return TARGET;
            for (int i = 0; i < inputLengths.length; i++) {
                if (size == inputLengths[i] && Arrays.equals(hash, inputHashes[i])) return i;
            }
            return UNKNOWN;
        }
    }

    public static boolean matchesPatchedArchive(Context context, File root, String name) {
        if (!"zombie1.rsb.smf".equals(name)) return false;
        try (DataInputStream patch = openPatch(context)) {
            PatchHeader header = new PatchHeader(patch);
            return header.match(new File(root, name), MessageDigest.getInstance("SHA-256"),
                    new byte[64 * 1024]) != PatchHeader.UNKNOWN;
        } catch (IOException | NoSuchAlgorithmException failure) {
            Log.w(TAG, "Could not validate the Zomboss archive", failure);
            return false;
        }
    }

    public static void apply(Context context) {
        File root = context.getExternalFilesDir(null);
        if (root == null) return;
        File bundle = new File(root, "zombie1.rsb.smf");
        if (!bundle.isFile()) return;
        File staged = new File(root, "zombie1-aster-zomboss.tmp");
        try (DataInputStream patch = openPatch(context)) {
            PatchHeader header = new PatchHeader(patch);
            byte[] buffer = new byte[64 * 1024];
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            int selectedInput = header.match(bundle, digest, buffer);
            if (selectedInput == PatchHeader.TARGET) return;
            if (selectedInput == PatchHeader.UNKNOWN) {
                Log.w(TAG, "Unrecognized zombie1 archive");
                return;
            }
            int originalLength = header.inputLengths[selectedInput];

            try (RandomAccessFile source = new RandomAccessFile(bundle, "r");
                 FileOutputStream file = new FileOutputStream(staged);
                 DigestOutputStream output = new DigestOutputStream(file, digest)) {
                int cursor = 0;
                long written = 0;
                for (int i = 0; i < header.edits; i++) {
                    int offset = 0;
                    int oldLength = 0;
                    for (int input = 0; input < header.inputLengths.length; input++) {
                        int inputOffset = patch.readInt();
                        int inputLength = patch.readInt();
                        if (input == selectedInput) {
                            offset = inputOffset;
                            oldLength = inputLength;
                        }
                    }
                    int newLength = patch.readInt();
                    if (offset < cursor || offset > originalLength || oldLength < 0 ||
                            oldLength > originalLength - offset || newLength < 0) {
                        throw new IOException("Invalid Zomboss patch span");
                    }
                    int unchanged = offset - cursor;
                    written += (long) unchanged + newLength;
                    if (written > header.targetLength) throw new IOException("Zomboss patch is too large");
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
                if (written + originalLength - cursor != header.targetLength || patch.read() != -1) {
                    throw new IOException("Zomboss patch length differs");
                }
                for (int left = originalLength - cursor; left > 0;) {
                    int count = Math.min(left, buffer.length);
                    source.readFully(buffer, 0, count);
                    output.write(buffer, 0, count);
                    left -= count;
                }
                if (!Arrays.equals(digest.digest(), header.targetHash)) {
                    throw new IOException("Zomboss patch checksum differs");
                }
                file.getFD().sync();
            }
            if (!staged.renameTo(bundle)) throw new IOException("Could not install Zomboss artwork");
            Log.i(TAG, "Installed the Egyptian Zomboss teleport and phase-change artwork");
        } catch (IOException | NoSuchAlgorithmException failure) {
            Log.w(TAG, "Could not update Zomboss artwork", failure);
        } finally {
            if (staged.exists()) staged.delete();
        }
    }
}

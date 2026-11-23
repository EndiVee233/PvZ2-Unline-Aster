package com.popcap.pvz2cthd;

import android.content.Context;
import android.util.Log;
import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.EOFException;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.zip.CRC32;

public final class AsterLuckyTreasureArt {
    private AsterLuckyTreasureArt() {}

    public static void apply(Context context) {
        File root = context.getExternalFilesDir(null);
        if (root == null) return;
        apply(context, root, "uicommon");
        apply(context, root, "uiactive");
    }

    private static void apply(Context context, File root, String name) {
        File bundle = new File(root, name + ".rsb.smf");
        File staged = new File(root, name + "-aster-lucky-art.tmp");
        try (DataInputStream patch = new DataInputStream(new BufferedInputStream(
                context.getAssets().open("reconstruction/aster-lucky-art-" + name + ".patch")));
             RandomAccessFile source = new RandomAccessFile(bundle, "r")) {
            int length = patch.readInt();
            int offset = patch.readInt();
            int size = patch.readInt();
            int originalCrc = patch.readInt();
            int replacementCrc = patch.readInt();
            if (source.length() != length || size <= 0 || size > 16 * 1024 * 1024 ||
                    offset < 4096 || offset > length - size) return;

            byte[] payload = new byte[size];
            source.seek(offset);
            source.readFully(payload);
            int installedCrc = crc(payload);
            if (installedCrc == replacementCrc || installedCrc != originalCrc) return;
            patch.readFully(payload);
            if (crc(payload) != replacementCrc || patch.read() != -1) {
                throw new IOException("Invalid artwork patch");
            }
            try (RandomAccessFile destination = new RandomAccessFile(staged, "rw")) {
                destination.setLength(0);
                source.seek(0);
                copy(source, destination, offset);
                destination.write(payload);
                source.seek(offset + size);
                copy(source, destination, length - offset - size);
                destination.getFD().sync();
            }
            if (!staged.renameTo(bundle)) throw new IOException("Could not replace artwork bundle");
            Log.i("AsterLuckyArt", "Removed the Lucky Treasure artwork from " + name);
        } catch (IOException failure) {
            Log.w("AsterLuckyArt", "Artwork update failed", failure);
        } finally {
            if (staged.exists()) staged.delete();
        }
    }

    private static int crc(byte[] bytes) {
        CRC32 checksum = new CRC32();
        checksum.update(bytes);
        return (int) checksum.getValue();
    }

    private static void copy(RandomAccessFile source, RandomAccessFile target, int remaining)
            throws IOException {
        byte[] buffer = new byte[64 * 1024];
        while (remaining > 0) {
            int read = source.read(buffer, 0, Math.min(remaining, buffer.length));
            if (read < 0) throw new EOFException();
            target.write(buffer, 0, read);
            remaining -= read;
        }
    }
}

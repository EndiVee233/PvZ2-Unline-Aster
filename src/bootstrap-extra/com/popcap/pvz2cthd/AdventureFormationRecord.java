package com.popcap.pvz2cthd;

import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Reader for the native adventure records.h v1 layout. */
final class AdventureFormationRecord {
    private static final int SIZE = 4888;
    private static final int PLANT_SIZE = 36;
    final int owner, day, stars, elapsedMs;
    final List<Plant> plants;

    static final class Plant {
        final String type;
        final int column, row, level;
        final boolean avatar;

        Plant(String type, int column, int row, int level, boolean avatar) {
            this.type = type;
            this.column = column;
            this.row = row;
            this.level = level;
            this.avatar = avatar;
        }
    }

    private AdventureFormationRecord(int owner, int day, int stars, int elapsedMs, List<Plant> plants) {
        this.owner = owner;
        this.day = day;
        this.stars = stars;
        this.elapsedMs = elapsedMs;
        this.plants = Collections.unmodifiableList(plants);
    }

    static AdventureFormationRecord read(InputStream input) throws IOException {
        byte[] bytes = new byte[SIZE];
        DataInputStream stream = new DataInputStream(input);
        stream.readFully(bytes);
        if (stream.read() != -1) throw new IOException("Unexpected adventure record length");
        ByteBuffer data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        int digest = 0x811c9dc5;
        for (int i = 0; i < SIZE - Integer.BYTES; i++) {
            digest = (digest ^ (bytes[i] & 0xff)) * 0x01000193;
        }
        if (data.getInt(SIZE - Integer.BYTES) != digest || data.getInt() != 1) {
            throw new IOException("Invalid adventure record format");
        }
        int owner = data.getInt();
        int day = data.getInt();
        int stars = data.getInt();
        int elapsedMs = data.getInt();
        int count = data.getInt();
        if (owner == -1 || day < 1 || day > 2 || stars < 0 || stars > 3 ||
                elapsedMs < 1 || elapsedMs > 3_600_000 || count < 0 || count > 135) {
            throw new IOException("Invalid adventure record metadata");
        }

        int[][] stacks = new int[5][9];
        List<Plant> plants = new ArrayList<>(count);
        for (int index = 0; index < count; index++) {
            int offset = data.position();
            int length = 0;
            while (length < 32 && bytes[offset + length] != 0) {
                byte ch = bytes[offset + length];
                if (!(ch >= 'a' && ch <= 'z') && !(ch >= '0' && ch <= '9') && ch != '_') {
                    throw new IOException("Invalid plant alias");
                }
                length++;
            }
            if (length == 0 || length == 32) throw new IOException("Invalid plant alias length");
            String type = new String(bytes, offset, length, StandardCharsets.US_ASCII);
            int column = bytes[offset + 32] & 0xff;
            int row = bytes[offset + 33] & 0xff;
            int level = bytes[offset + 34] & 0xff;
            int avatar = bytes[offset + 35] & 0xff;
            if (column >= 9 || row >= 5 || level < 1 || level > 4 || avatar > 1 ||
                    ++stacks[row][column] > 3) {
                throw new IOException("Invalid plant position or attributes");
            }
            plants.add(new Plant(type, column, row, level, avatar == 1));
            data.position(offset + PLANT_SIZE);
        }
        return new AdventureFormationRecord(owner, day, stars, elapsedMs, plants);
    }
}

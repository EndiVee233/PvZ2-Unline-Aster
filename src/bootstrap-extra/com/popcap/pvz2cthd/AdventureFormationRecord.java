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

/** Reader for the native adventure records.h layout. */
final class AdventureFormationRecord {
    static final int VERSION = 3;
    static final int LOADOUT_OFFSET = 4884;
    static final int MAX_SLOTS = 16;
    static final int CARD_SIZE = 36;
    static final int CUKE_OFFSET = LOADOUT_OFFSET + Integer.BYTES + MAX_SLOTS * CARD_SIZE;
    static final int SIZE = CUKE_OFFSET + 2 * Integer.BYTES;
    private static final int LEGACY_SIZE = LOADOUT_OFFSET + Integer.BYTES;
    private static final int PLANT_SIZE = 36;
    final int owner, day, stars, elapsedMs, tacticalCukeUses;
    final List<Plant> plants;
    final List<Card> cards;

    static final class Card {
        final String type;
        final int level;

        Card(String type, int level) {
            this.type = type;
            this.level = level;
        }
    }

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

    private AdventureFormationRecord(int owner, int day, int stars, int elapsedMs, List<Plant> plants,
                                     List<Card> cards, int tacticalCukeUses) {
        this.owner = owner;
        this.day = day;
        this.stars = stars;
        this.elapsedMs = elapsedMs;
        this.plants = Collections.unmodifiableList(plants);
        this.cards = Collections.unmodifiableList(cards);
        this.tacticalCukeUses = tacticalCukeUses;
    }

    static AdventureFormationRecord read(InputStream input) throws IOException {
        DataInputStream stream = new DataInputStream(input);
        int version = Integer.reverseBytes(stream.readInt());
        int size = version == 1 ? LEGACY_SIZE : version == 2 ? CUKE_OFFSET + Integer.BYTES : SIZE;
        if (version < 1 || version > VERSION) throw new IOException("Invalid adventure record version");
        byte[] bytes = new byte[size];
        ByteBuffer data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        data.putInt(version);
        stream.readFully(bytes, Integer.BYTES, size - Integer.BYTES);
        if (stream.read() != -1) throw new IOException("Unexpected adventure record length");
        int digest = 0x811c9dc5;
        for (int i = 0; i < size - Integer.BYTES; i++) {
            digest = (digest ^ (bytes[i] & 0xff)) * 0x01000193;
        }
        if (data.getInt(size - Integer.BYTES) != digest) {
            throw new IOException("Invalid adventure record format");
        }
        int owner = data.getInt();
        int day = data.getInt();
        int stars = data.getInt();
        int elapsedMs = data.getInt();
        int count = data.getInt();
        if (owner == -1 || !validLevel(day) || stars < 0 || stars > 3 ||
                elapsedMs < 1 || elapsedMs > 3_600_000 || count < 0 || count > 135) {
            throw new IOException("Invalid adventure record metadata");
        }

        int[][] stacks = new int[5][9];
        List<Plant> plants = new ArrayList<>(count);
        for (int index = 0; index < count; index++) {
            int offset = data.position();
            int length = aliasLength(bytes, offset);
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
        List<Card> cards = new ArrayList<>();
        if (version >= 2) {
            int slots = data.getInt(LOADOUT_OFFSET);
            if (slots < 0 || slots > MAX_SLOTS) throw new IOException("Invalid seed bank size");
            for (int slot = 0; slot < MAX_SLOTS; slot++) {
                int offset = LOADOUT_OFFSET + Integer.BYTES + slot * CARD_SIZE;
                int level = data.getInt(offset + 32);
                if (bytes[offset] == 0 && level == 0) {
                    if (slot < slots) cards.add(null);
                    continue;
                }
                if (slot >= slots || level < 1 || level > 4) throw new IOException("Invalid seed card");
                cards.add(new Card(new String(bytes, offset, aliasLength(bytes, offset), StandardCharsets.US_ASCII), level));
            }
        }
        int uses = version == VERSION ? data.getInt(CUKE_OFFSET) : -1;
        if (uses < -1 || uses > 3600) throw new IOException("Invalid tactical cucumber count");
        return new AdventureFormationRecord(owner, day, stars, elapsedMs, plants, cards, uses);
    }

    static int aliasLength(byte[] bytes, int offset) throws IOException {
        for (int length = 0; length < 32; length++) {
            byte ch = bytes[offset + length];
            if (ch == 0 && length > 0) return length;
            if (!(ch >= 'a' && ch <= 'z') && !(ch >= '0' && ch <= '9') && ch != '_') {
                throw new IOException("Invalid plant alias");
            }
        }
        throw new IOException("Invalid plant alias length");
    }

    static boolean validLevel(int key) {
        return key == 1 || key == 2 || (key >>> 30) == 1;
    }
}

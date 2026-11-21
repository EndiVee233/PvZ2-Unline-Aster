package com.popcap.pvz2cthd;

import android.app.Activity;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Supplies offline friend data to the native level menu. */
public final class AdventureSocial {
    private static final String EVENT = "aster-social-level";
    private static final String REPLY = "aster-social-reply";
    private static final int SELECT = 1, CLOSED = 3, UNAVAILABLE = 4;
    private static final int WATCH = 2, BACK = 3, SCORES = 4;
    private static final int FRIEND = 0x100;
    private static long nextFramePoll;
    private static File event;
    private static Message activeMenu;
    private static List<FriendRun> menuRuns;
    private static Message activeView;

    private AdventureSocial() {}

    private static final class Message {
        final int token, owner, day, kind;

        Message(byte[] raw) {
            ByteBuffer fields = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
            token = fields.getInt();
            owner = fields.getInt();
            day = fields.getInt();
            kind = fields.getInt();
        }

        boolean matches(Message other) {
            return other != null && other.token == token && other.owner == owner && other.day == day;
        }
    }

    private static final class FriendRun {
        final String name;
        final byte[] record;
        final int elapsedMs, stars;

        FriendRun(String name, byte[] record, AdventureFormationRecord data) {
            this.name = name;
            this.record = record;
            this.elapsedMs = data.elapsedMs;
            this.stars = data.stars;
        }
    }

    public static void frame() {
        long now = SystemClock.uptimeMillis();
        if (now < nextFramePoll) return;
        nextFramePoll = now + 120;
        if (event != null && !event.isFile()) return;
        try {
            Activity activity = (Activity) Class.forName("com.popcap.SexyAppFramework.SexyAppFrameworkActivity")
                    .getMethod("instance").invoke(null);
            if (activity == null) return;
            if (event == null) {
                event = new File(activity.getCacheDir(), EVENT);
                event.delete();
                return;
            }
            try (FileInputStream file = new FileInputStream(event)) {
                if (!event.delete()) return;
                byte[] raw = PvpPresetDocument.read(file);
                if (raw.length != 16) return;
                Message message = new Message(raw);
                if (message.owner == -1 || message.day < 1 || message.day > 2) return;
                activity.runOnUiThread(() -> receive(activity, message));
            }
        } catch (ReflectiveOperationException | IOException | RuntimeException error) {
            android.util.Log.w("AsterSocial", "Could not receive level event", error);
        }
    }

    private static void receive(Activity activity, Message message) {
        if (activity.isFinishing() || activity.isDestroyed()) return;
        if (message.kind == SELECT) {
            activeMenu = message;
            menuRuns = friends(activity, message.day);
            sendScores(activity, message, menuRuns);
        } else if (message.kind >= FRIEND && message.matches(activeMenu)) {
            int index = message.kind - FRIEND;
            if (index >= menuRuns.size() || !activity.hasWindowFocus()) {
                reply(activity, message, BACK, null);
                return;
            }
            FriendRun choice = menuRuns.get(index);
            if (reply(activity, message, WATCH, choice.record)) activeView = message;
        } else if (message.matches(activeView)) {
            if (message.kind == CLOSED || message.kind == UNAVAILABLE) {
                activeView = null;
                if (message.kind == UNAVAILABLE) {
                    Toast.makeText(activity, "当前关卡无法展示这份阵型", Toast.LENGTH_SHORT).show();
                }
            }
        }
    }

    private static void sendScores(Activity activity, Message message, List<FriendRun> runs) {
        ByteBuffer rows = ByteBuffer.allocate(4 + runs.size() * 168).order(ByteOrder.LITTLE_ENDIAN);
        rows.putInt(runs.size());
        for (FriendRun run : runs) {
            rows.putInt(run.stars).putInt(run.elapsedMs);
            int end = rows.position() + 160;
            run.name.codePoints().forEach(rows::putInt);
            rows.position(end);
        }
        reply(activity, message, SCORES, rows.array());
    }

    private static boolean reply(Activity activity, Message message, int action, byte[] record) {
        ByteBuffer data = ByteBuffer.allocate(16 + (record == null ? 0 : record.length))
                .order(ByteOrder.LITTLE_ENDIAN);
        data.putInt(message.token).putInt(message.owner).putInt(message.day).putInt(action);
        if (record != null) data.put(record);
        File temp = new File(activity.getCacheDir(), REPLY + ".tmp");
        File target = new File(activity.getCacheDir(), REPLY);
        try {
            try (FileOutputStream output = new FileOutputStream(temp)) {
                output.write(data.array());
            }
            Os.rename(temp.getPath(), target.getPath());
            return true;
        } catch (IOException | ErrnoException error) {
            temp.delete();
            Toast.makeText(activity, "关卡操作暂不可用", Toast.LENGTH_SHORT).show();
            android.util.Log.w("AsterSocial", "Could not send level command", error);
            return false;
        }
    }

    private static List<FriendRun> friends(Activity activity, int day) {
        File external = activity.getExternalFilesDir(null);
        File local = external == null ? null : new File(external, "adventure-friends.json");
        if (local != null && local.isFile()) {
            try (FileInputStream stream = new FileInputStream(local)) {
                return readFriends(stream, day);
            } catch (IOException | JSONException error) {
                android.util.Log.w("AsterSocial", "Invalid offline friends file", error);
            }
        }
        try (InputStream stream = activity.getAssets().open("adventure/friends.json")) {
            return readFriends(stream, day);
        } catch (IOException | JSONException error) {
            android.util.Log.w("AsterSocial", "Could not read bundled offline friends", error);
            return new ArrayList<>();
        }
    }

    static List<FriendRun> readFriends(InputStream stream, int day) throws IOException, JSONException {
        JSONObject file = new JSONObject(new String(PvpPresetDocument.read(stream), StandardCharsets.UTF_8));
        integer(file, "version", 1, 1);
        JSONArray players = file.getJSONArray("friends");
        if (players.length() > 40) throw new IOException("Too many offline friends");
        List<FriendRun> results = new ArrayList<>();
        for (int index = 0; index < players.length(); index++) {
            JSONObject player = players.getJSONObject(index);
            String name = PvpPresetDocument.validName(player.getString("name"));
            int id = integer(player, "id", 1, Integer.MAX_VALUE);
            JSONArray records = player.getJSONArray("runs");
            if (name.isEmpty() || records.length() > 64) throw new IOException("Invalid offline friend");
            boolean[] seen = new boolean[8];
            for (int run = 0; run < records.length(); run++) {
                JSONObject entry = records.getJSONObject(run);
                int level = integer(entry, "day", 1, 2);
                int stars = integer(entry, "stars", 0, 3);
                int slot = (level - 1) * 4 + stars;
                if (seen[slot]) throw new IOException("Duplicate entry for offline friend");
                seen[slot] = true;
                if (level != day) continue;
                byte[] packed = encodeRun(entry, id, level, stars);
                AdventureFormationRecord record = AdventureFormationRecord.read(new ByteArrayInputStream(packed));
                results.add(new FriendRun(name, packed, record));
            }
        }
        results.sort(Comparator.comparingInt(item -> item.elapsedMs));
        return results;
    }

    private static int integer(JSONObject object, String key, int min, int max)
            throws IOException, JSONException {
        Object value = object.get(key);
        if (!(value instanceof Number)) throw new IOException("Invalid numeric field " + key);
        double number = ((Number) value).doubleValue();
        if (!(number == (int) number && number >= min && number <= max)) {
            throw new IOException("Invalid numeric field " + key);
        }
        return (int) number;
    }

    private static byte[] encodeRun(JSONObject entry, int owner, int day, int stars)
            throws IOException, JSONException {
        int time = integer(entry, "elapsedMs", 1, 3_600_000);
        JSONArray plants = entry.getJSONArray("plants");
        if (plants.length() > 135) throw new IOException("Formation is too large");
        ByteBuffer out = ByteBuffer.allocate(4888).order(ByteOrder.LITTLE_ENDIAN);
        out.putInt(1).putInt(owner).putInt(day).putInt(stars).putInt(time).putInt(plants.length());
        for (int index = 0; index < plants.length(); index++) {
            JSONObject plant = plants.getJSONObject(index);
            String type = plant.getString("type");
            if (!type.matches("[a-z0-9_]{1,31}")) throw new IOException("Invalid plant alias");
            int end = out.position() + 32;
            out.put(type.getBytes(StandardCharsets.US_ASCII)).position(end);
            out.put((byte) (integer(plant, "column", 1, 9) - 1));
            out.put((byte) (integer(plant, "row", 1, 5) - 1));
            out.put((byte) integer(plant, "level", 1, 4));
            out.put((byte) 0);
        }
        int digest = 0x811c9dc5;
        for (int i = 0; i < out.capacity() - 4; i++) {
            digest = (digest ^ (out.get(i) & 255)) * 0x01000193;
        }
        out.putInt(out.capacity() - 4, digest);
        return out.array();
    }
}

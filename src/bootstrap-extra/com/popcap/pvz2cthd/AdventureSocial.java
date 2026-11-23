package com.popcap.pvz2cthd;

import android.app.Activity;
import android.content.Intent;
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
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Connects the native social menus to the local and community player files. */
public final class AdventureSocial {
    private static final String EVENT = "aster-social-level";
    private static final String REPLY = "aster-social-reply";
    private static final int SELECT = 1, CLOSED = 3, UNAVAILABLE = 4;
    private static final int WATCH = 2, BACK = 3, SCORES = 4;
    private static final int SUN_FRIENDS = 5;
    private static final int BORROW_FRIENDS = 6;
    private static final int REFRESH_FRIENDS = 7;
    private static final int SAVE_BACKUP = 8;
    private static final int FRIEND_LIST = 9, FRIEND_CATALOG = 10, FRIEND_ADD = 11, FRIEND_REMOVE = 12;
    private static final int FRIEND = 0x100;
    private static final int UNKNOWN_AVATAR = -1;
    private static long nextFramePoll;
    private static File event, exportEvent;
    private static Message activeMenu;
    private static List<FriendRun> menuRuns;
    private static Message activeView;
    private static JSONObject levels;

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
        final int id, elapsedMs, stars, avatar;

        FriendRun(String name, int avatar, byte[] record, AdventureFormationRecord data) {
            this.name = name;
            this.record = record;
            this.id = data.owner;
            this.elapsedMs = data.elapsedMs;
            this.stars = data.stars;
            this.avatar = avatar;
        }
    }

    public static void frame() {
        long now = SystemClock.uptimeMillis();
        if (now < nextFramePoll) return;
        nextFramePoll = now + 120;
        if (event != null && !event.isFile() && !exportEvent.isFile()) return;
        try {
            Activity activity = (Activity) Class.forName("com.popcap.SexyAppFramework.SexyAppFrameworkActivity")
                    .getMethod("instance").invoke(null);
            if (activity == null) return;
            if (event == null) {
                event = new File(activity.getCacheDir(), EVENT);
                exportEvent = new File(activity.getCacheDir(), AdventureFriendFiles.EXPORT_EVENT);
                event.delete();
                exportEvent.delete();
                AdventureFriendFiles.prepare(activity);
                return;
            }
            if (exportEvent.isFile()) {
                try (FileInputStream file = new FileInputStream(exportEvent)) {
                    if (exportEvent.delete()) {
                        byte[] raw = AdventureFriendFiles.read(file, AdventureFriendFiles.EXPORT_SIZE);
                        activity.runOnUiThread(() -> {
                            JSONObject catalog = catalog(activity);
                            if (catalog != null) AdventureFriendFiles.export(activity, raw, catalog);
                        });
                    }
                }
            }
            if (!event.isFile()) return;
            try (FileInputStream file = new FileInputStream(event)) {
                if (!event.delete()) return;
                byte[] raw = PvpPresetDocument.read(file);
                if (raw.length != 16) return;
                Message message = new Message(raw);
                boolean rosterMessage = message.kind >= FRIEND_LIST && message.kind <= FRIEND_REMOVE;
                if (message.owner == -1 || (!rosterMessage && !AdventureFormationRecord.validLevel(message.day)))
                    return;
                activity.runOnUiThread(() -> receive(activity, message));
            }
        } catch (ReflectiveOperationException | IOException | RuntimeException error) {
            android.util.Log.w("AsterSocial", "Could not receive level event", error);
        }
    }

    public static boolean onActivityResult(Activity activity, int request, int result, Intent intent) {
        return AdventureFriendFiles.onResult(activity, request, result, intent)
                || AsterSaveBackup.onResult(activity, request, result, intent);
    }

    private static void receive(Activity activity, Message message) {
        if (activity.isFinishing() || activity.isDestroyed()) return;
        if (message.kind == SAVE_BACKUP) {
            AsterSaveBackup.show(activity);
        } else if (message.kind == REFRESH_FRIENDS) {
            JSONObject catalog = catalog(activity);
            if (catalog != null) AdventureFriendFiles.refresh(activity, catalog);
        } else if (message.kind >= FRIEND_LIST && message.kind <= FRIEND_REMOVE) {
            JSONArray candidates = readFriendCatalog(activity, message.owner, players -> players);
            try {
                byte[] page = AdventureFriendRoster.respond(activity, message.owner, message.kind,
                        message.day, candidates == null ? new JSONArray() : candidates);
                reply(activity, message, FRIEND_LIST, page);
            } catch (IOException | JSONException error) {
                android.util.Log.w("AsterSocial", "Could not read friend roster", error);
                reply(activity, message, FRIEND_LIST,
                        ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN).putInt(3).array());
            }
        } else if (message.kind == SELECT) {
            activeMenu = message;
            menuRuns = friends(activity, message);
            sendScores(activity, message, menuRuns);
        } else if (message.kind == BORROW_FRIENDS) {
            byte[] friends = readAllFriends(activity, message.owner, AdventureSocial::encodeBorrowFriends);
            reply(activity, message, BORROW_FRIENDS, friends == null ? new byte[4] : friends);
        } else if (message.kind == SUN_FRIENDS) {
            byte[] friends = readAllFriends(activity, message.owner, AdventureSocial::encodeSunFriends);
            reply(activity, message, SUN_FRIENDS, friends == null ? new byte[4] : friends);
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
        ByteBuffer rows = ByteBuffer.allocate(4 + runs.size() * 176).order(ByteOrder.LITTLE_ENDIAN);
        rows.putInt(runs.size());
        for (FriendRun run : runs) {
            rows.putInt(run.id).putInt(run.stars).putInt(run.elapsedMs).putInt(run.avatar);
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

    private static JSONObject catalog(Activity activity) {
        if (levels == null) {
            try (InputStream stream = activity.getAssets().open("adventure/levels.json")) {
                levels = new JSONObject(new String(PvpPresetDocument.read(stream), StandardCharsets.UTF_8));
            } catch (IOException | JSONException error) {
                android.util.Log.w("AsterSocial", "Could not read adventure level catalog", error);
                return null;
            }
        }
        return levels;
    }

    private static List<FriendRun> friends(Activity activity, Message message) {
        JSONObject catalog = catalog(activity);
        if (catalog == null) return new ArrayList<>();
        List<FriendRun> result = readAllFriends(activity, message.owner, players -> readFriends(players, catalog, message.day));
        return result == null ? new ArrayList<>() : result;
    }

    private interface Reader<T> {
        T read(JSONArray players) throws IOException, JSONException;
    }

    private static <T> T readAllFriends(Activity activity, int owner, Reader<T> reader) {
        return readFriendCatalog(activity, owner,
                players -> reader.read(AdventureFriendRoster.selected(activity, owner, players)));
    }

    private static <T> T readFriendCatalog(Activity activity, int owner, Reader<T> reader) {
        JSONObject catalog = catalog(activity);
        if (catalog != null) AdventureFriendFiles.refresh(activity, catalog);
        File external = activity.getExternalFilesDir(null);
        File local = external == null ? null : new File(external, "adventure-friends.json");
        if (local != null && local.isFile()) {
            try (FileInputStream stream = new FileInputStream(local)) {
                return reader.read(AdventureFriendFiles.merge(activity, owner, players(stream)));
            } catch (IOException | JSONException error) {
                android.util.Log.w("AsterSocial", "Invalid offline friends file", error);
            }
        }
        try (InputStream stream = activity.getAssets().open("adventure/friends.json")) {
            return reader.read(AdventureFriendFiles.merge(activity, owner, players(stream)));
        } catch (IOException | JSONException error) {
            android.util.Log.w("AsterSocial", "Could not read bundled offline friends", error);
            return null;
        }
    }

    private static JSONArray players(InputStream stream) throws IOException, JSONException {
        JSONObject file = new JSONObject(new String(PvpPresetDocument.read(stream), StandardCharsets.UTF_8));
        integer(file, "version", 1, 1);
        JSONArray players = file.getJSONArray("friends");
        if (players.length() > AdventureFriendFiles.MAX_FRIENDS) throw new IOException("Too many offline friends");
        return players;
    }

    private static byte[] encodeSunFriends(JSONArray players) throws IOException, JSONException {
        ByteBuffer result = ByteBuffer.allocate(4 + 168 * players.length()).order(ByteOrder.LITTLE_ENDIAN);
        result.putInt(players.length());
        Set<Integer> ids = new HashSet<>();
        for (int index = 0; index < players.length(); index++) {
            JSONObject player = players.getJSONObject(index);
            int id = integer(player, "id", 1, Integer.MAX_VALUE);
            String name = PvpPresetDocument.validName(player.getString("name"));
            if (name.isEmpty() || !ids.add(id)) throw new IOException("Invalid offline friend");
            result.putInt(id).putInt(avatar(player));
            int end = result.position() + 160;
            name.codePoints().limit(39).forEach(result::putInt);
            result.position(end);
        }
        return result.array();
    }

    private static byte[] encodeBorrowFriends(JSONArray players) throws IOException, JSONException {
        int size = 2 * Integer.BYTES + 160 + AdventureFormationRecord.CARD_SIZE;
        ByteBuffer out = ByteBuffer.allocate(4 + size * 3 * players.length()).order(ByteOrder.LITTLE_ENDIAN);
        out.position(4);
        int count = 0;
        Set<Integer> ids = new HashSet<>();
        for (int index = 0; index < players.length(); index++) {
            JSONObject player = players.getJSONObject(index);
            JSONArray cards = player.optJSONArray("borrowPlants");
            if (cards == null && player.has("borrowPlant")) cards = new JSONArray().put(player.getJSONObject("borrowPlant"));
            if (cards == null) continue;
            String name = PvpPresetDocument.validName(player.getString("name"));
            int id = integer(player, "id", 1, Integer.MAX_VALUE);
            int portrait = avatar(player);
            if (name.isEmpty() || !ids.add(id) || cards.length() > 3) {
                throw new IOException("Invalid borrowed plant");
            }
            for (int i = 0; i < cards.length(); ++i) {
                JSONObject card = cards.getJSONObject(i);
                out.putInt(id).putInt(portrait);
                int alias = out.position() + 160;
                name.codePoints().limit(39).forEach(out::putInt);
                out.position(alias).put(plantType(card).getBytes(StandardCharsets.US_ASCII)).position(alias + 32);
                out.putInt(integer(card, "level", 1, 4));
                count++;
            }
        }
        out.putInt(0, count);
        return java.util.Arrays.copyOf(out.array(), out.position());
    }

    static List<FriendRun> readFriends(JSONArray players, JSONObject levels, int day)
            throws IOException, JSONException {
        List<FriendRun> results = new ArrayList<>();
        Set<Integer> ids = new HashSet<>();
        for (int index = 0; index < players.length(); index++) {
            JSONObject player = players.getJSONObject(index);
            String name = PvpPresetDocument.validName(player.getString("name"));
            int id = integer(player, "id", 1, Integer.MAX_VALUE);
            JSONArray records = player.getJSONArray("runs");
            boolean community = player.has("playerId");
            int maxRuns = community ? AdventureFriendFiles.MAX_RUNS : 64;
            if (name.isEmpty() || !ids.add(id) || records.length() > maxRuns) {
                throw new IOException("Invalid offline friend");
            }
            Set<Long> seen = new HashSet<>();
            for (int run = 0; run < records.length(); run++) {
                JSONObject entry = records.getJSONObject(run);
                String alias = entry.has("level") ? entry.getString("level")
                        : "egypt" + integer(entry, "day", 1, 2);
                JSONArray info = levels.optJSONArray(alias);
                if (info == null) continue;
                int level = info.getInt(0);
                int tiers = info.getInt(1);
                int stars = integer(entry, "stars", tiers == 1 ? 1 : 0, tiers);
                if (!seen.add(((long) level << 2) | stars)) {
                    throw new IOException("Duplicate entry for offline friend");
                }
                if (level != day) continue;
                byte[] packed = encodeRun(entry, id, level, stars, info.getBoolean(2));
                AdventureFormationRecord record = AdventureFormationRecord.read(new ByteArrayInputStream(packed));
                results.add(new FriendRun(name, avatar(player), packed, record));
            }
        }
        results.sort(Comparator.comparingInt(item -> item.elapsedMs));
        return results;
    }

    private static int avatar(JSONObject player) throws IOException, JSONException {
        return player.has("avatar") ? integer(player, "avatar", 0, 5) : UNKNOWN_AVATAR;
    }

    static String plantType(JSONObject card) throws IOException, JSONException {
        Object alias = card.get("type");
        if (!(alias instanceof String) || !((String) alias).matches("[a-z0-9_]{1,31}")) {
            throw new IOException("Invalid plant alias");
        }
        return (String) alias;
    }

    static int integer(JSONObject object, String key, int min, int max)
            throws IOException, JSONException {
        Object value = object.get(key);
        if (!(value instanceof Number)) throw new IOException("Invalid numeric field " + key);
        double number = ((Number) value).doubleValue();
        if (!(number == (int) number && number >= min && number <= max)) {
            throw new IOException("Invalid numeric field " + key);
        }
        return (int) number;
    }

    static byte[] encodeRun(JSONObject entry, int owner, int day, int stars, boolean formation)
            throws IOException, JSONException {
        int time = integer(entry, "elapsedMs", 1, 3_600_000);
        JSONArray plants = formation ? entry.getJSONArray("plants") : new JSONArray();
        if (plants.length() > 135) throw new IOException("Formation is too large");
        ByteBuffer out = ByteBuffer.allocate(AdventureFormationRecord.SIZE).order(ByteOrder.LITTLE_ENDIAN);
        out.putInt(AdventureFormationRecord.VERSION).putInt(owner).putInt(day).putInt(stars)
                .putInt(time).putInt(plants.length());
        for (int index = 0; index < plants.length(); index++) {
            JSONObject plant = plants.getJSONObject(index);
            int end = out.position() + 32;
            out.put(plantType(plant).getBytes(StandardCharsets.US_ASCII)).position(end);
            out.put((byte) (integer(plant, "column", 1, 9) - 1));
            out.put((byte) (integer(plant, "row", 1, 5) - 1));
            out.put((byte) integer(plant, "level", 1, 4));
            out.put((byte) (plant.optBoolean("avatar", false) ? 1 : 0));
        }
        if (formation && entry.has("cards")) {
            JSONArray cards = entry.getJSONArray("cards");
            if (cards.length() > AdventureFormationRecord.MAX_SLOTS) throw new IOException("Too many seed slots");
            out.position(AdventureFormationRecord.LOADOUT_OFFSET);
            out.putInt(cards.length());
            for (int slot = 0; slot < cards.length(); slot++) {
                int offset = out.position();
                if (!cards.isNull(slot)) {
                    JSONObject card = cards.getJSONObject(slot);
                    out.put(plantType(card).getBytes(StandardCharsets.US_ASCII)).position(offset + 32);
                    out.putInt(integer(card, "level", 1, 4));
                }
                out.position(offset + AdventureFormationRecord.CARD_SIZE);
            }
        }
        int uses = entry.has("tacticalCukeUses") ? integer(entry, "tacticalCukeUses", 0, 3600) : -1;
        out.putInt(AdventureFormationRecord.CUKE_OFFSET, uses);
        int digest = 0x811c9dc5;
        for (int i = 0; i < out.capacity() - 4; i++) {
            digest = (digest ^ (out.get(i) & 255)) * 0x01000193;
        }
        out.putInt(out.capacity() - 4, digest);
        return out.array();
    }
}

package com.popcap.pvz2cthd;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.SystemClock;
import android.util.AtomicFile;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.HttpsURLConnection;

final class AdventureFriendFiles {
    static final String EXPORT_EVENT = "aster-social-export";
    private static final int LEGACY_EXPORT_SIZE = 280;
    static final int EXPORT_SIZE = LEGACY_EXPORT_SIZE + Integer.BYTES;
    static final int MAX_FRIENDS = 40;
    private static final int SAVE_DOCUMENT = 20804;
    private static final int MAX_EXPORT_BYTES = 12 * 1024 * 1024;
    private static final int MAX_CATALOG_BYTES = 24 * 1024 * 1024;
    static final int MAX_RUNS = 1280;
    private static final long REFRESH_INTERVAL = 10 * 60 * 1000L;
    private static final long RETRY_INTERVAL = 30 * 1000L;
    private static final String FORMAT = "pvz2-aster-player";
    private static final String REPOSITORY = "EndiVee233/PvZ2-Unline-Aster";
    private static final String DIRECTORY = "adventure-friends";
    private static final String CONTENTS = "https://api.github.com/repos/" + REPOSITORY
            + "/contents/" + DIRECTORY + "?ref=main";
    private static final String RAW = "https://raw.githubusercontent.com/" + REPOSITORY
            + "/main/" + DIRECTORY + "/";
    private static final String UUID_PATTERN = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
    private static final Pattern LEGACY_PLAYER_FILE =
            Pattern.compile("player-(" + UUID_PATTERN + ")(?: ?\\([1-9][0-9]{0,5}\\))?\\.json");
    private static final Pattern WINDOWS_DEVICE_NAME =
            Pattern.compile("(?i)(?:CON|PRN|AUX|NUL|CONIN\\$|CONOUT\\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\\..*)?");
    private static final ExecutorService EXPORTS = Executors.newSingleThreadExecutor();
    private static final ExecutorService SYNC = Executors.newSingleThreadExecutor();
    private static volatile JSONArray community = new JSONArray();
    private static volatile boolean catalogAvailable;
    private static boolean loaded, exporting;
    private static volatile long nextRefresh;
    private static Export pendingExport;

    private AdventureFriendFiles() {}

    private static final class Export {
        final String id;
        final String filename;
        final byte[] data;

        Export(String id, String name, byte[] data) {
            this.id = id;
            this.filename = playerFilename(name);
            this.data = data;
        }
    }

    static String playerFilename(String name) {
        String stem = name.replaceAll("[<>:\"/\\\\|?*]", "_").replaceAll("[ .]+$", "");
        if (stem.isEmpty()) stem = "玩家";
        if (WINDOWS_DEVICE_NAME.matcher(stem).matches()) stem = "_" + stem;
        return stem + ".json";
    }

    static byte[] read(InputStream in, int max) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int size;
        while ((size = in.read(buffer)) != -1) {
            if (size > max - out.size()) throw new IOException("Friend file too large");
            out.write(buffer, 0, size);
        }
        return out.toByteArray();
    }

    private static Object json(byte[] data) throws JSONException, IOException {
        PvpPresetDocument.checkDepth(data);
        JSONTokener input = new JSONTokener(new String(data, StandardCharsets.UTF_8));
        Object value = input.nextValue();
        if (input.nextClean() != 0) throw new IOException("Unexpected JSON content");
        return value;
    }

    private static String identity(Activity activity, int owner) {
        return activity.getSharedPreferences("adventure-share", 0).getString(Integer.toHexString(owner), "");
    }

    private static String exportIdentity(Activity activity, int owner) throws IOException {
        String id = identity(activity, owner);
        if (id.matches(UUID_PATTERN)) return id;
        id = UUID.randomUUID().toString();
        if (!activity.getSharedPreferences("adventure-share", 0).edit().putString(Integer.toHexString(owner), id).commit()) {
            throw new IOException("Could not save public player ID");
        }
        return id;
    }

    static void export(Activity activity, byte[] raw, JSONObject levels) {
        if (exporting || pendingExport != null) return;
        exporting = true;
        EXPORTS.execute(() -> {
            try {
                ByteBuffer header = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
                if (!validExportSize(raw.length) || header.getInt() != 1) throw new IOException("Invalid export request");
                int owner = header.getInt();
                if (owner == -1) throw new IOException("Player not selected");
                String id = exportIdentity(activity, owner);
                Export export = createExport(raw, id, levels, new File(activity.getFilesDir(), "userdata"));
                SharedPreferences files = destinations(activity);
                String destination = files.getString(id, "");
                // Saved destinations from UUID-named exports have no recorded title.
                if (!destination.isEmpty() && export.filename.equals(files.getString(id + ".filename", ""))) {
                    try {
                        writeExport(activity, Uri.parse(destination), export);
                        activity.runOnUiThread(() -> finishExport(activity, "已更新导出的玩家数据"));
                        return;
                    } catch (IOException | SecurityException unavailable) {
                        files.edit().remove(id).remove(id + ".filename").apply();
                    }
                }
                activity.runOnUiThread(() -> openDocument(activity, export));
            } catch (IOException | JSONException | RuntimeException error) {
                Log.w("AsterSocial", "Player export failed", error);
                activity.runOnUiThread(() -> finishExport(activity, "导出玩家数据失败，请重试"));
            }
        });
    }

    private static boolean validExportSize(int size) {
        return size == EXPORT_SIZE || size == LEGACY_EXPORT_SIZE;
    }

    private static Export createExport(byte[] raw, String id, JSONObject levels, File records)
            throws IOException, JSONException {
        ByteBuffer header = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
        if (!validExportSize(raw.length) || header.getInt() != 1 || !id.matches(UUID_PATTERN)) {
            throw new IOException("Invalid profile export");
        }
        int owner = header.getInt();
        int avatar = header.getInt();
        if (owner == -1 || avatar < 0 || avatar >= AdventureSocial.AVATAR_COUNT) throw new IOException("Invalid profile");
        StringBuilder nickname = new StringBuilder();
        for (int i = 0; i < 40; ++i) {
            int code = header.getInt();
            if (code == 0) break;
            if (Character.isValidCodePoint(code) && !Character.isISOControl(code) && !(code >= 0xd800 && code <= 0xdfff)) {
                nickname.appendCodePoint(code);
            }
        }
        String name = PvpPresetDocument.validName(nickname.toString());
        if (name.isEmpty()) name = "玩家";
        JSONArray loans = new JSONArray();
        for (int slot = 0; slot < 3; ++slot) {
            int offset = 172 + slot * AdventureFormationRecord.CARD_SIZE;
            if (raw[offset] == 0) continue;
            int level = header.getInt(offset + 32);
            String type = new String(raw, offset, AdventureFormationRecord.aliasLength(raw, offset), StandardCharsets.US_ASCII);
            if (level < 1 || level > 4) throw new IOException("Invalid loan card");
            loans.put(new JSONObject().put("type", type).put("level", level));
        }

        Map<Integer, String> aliases = new HashMap<>();
        for (java.util.Iterator<String> it = levels.keys(); it.hasNext();) {
            String alias = it.next();
            aliases.put(levels.getJSONArray(alias).getInt(0), alias);
        }
        String prefix = String.format(java.util.Locale.ROOT, "adventure-%08x-", owner);
        File[] files = records.listFiles((folder, file) -> file.startsWith(prefix) && file.endsWith(".run"));
        if (files == null) throw new IOException("Could not list player records");
        Arrays.sort(files, Comparator.comparing(File::getName));
        JSONArray runs = new JSONArray();
        for (File file : files) {
            AdventureFormationRecord record;
            try (FileInputStream stream = new FileInputStream(file)) {
                record = AdventureFormationRecord.read(stream);
            } catch (IOException invalid) {
                continue;
            }
            String alias = aliases.get(record.day);
            if (record.owner != owner || alias == null || !file.getName().equals(recordName(prefix, record))) continue;
            JSONArray info = levels.getJSONArray(alias);
            int stars = info.getInt(1);
            if (record.stars > stars || (stars == 1 && record.stars != 1)) continue;
            runs.put(encodeRecord(record, alias, info.getBoolean(2)));
        }
        int totalStars = raw.length == EXPORT_SIZE ? Math.max(0, header.getInt(LEGACY_EXPORT_SIZE)) : 0;
        JSONObject result = new JSONObject().put("format", FORMAT).put("version", 1)
                .put("playerId", id).put("name", name).put("avatar", avatar % AdventureSocial.LEGACY_AVATAR_COUNT)
                .put("totalStars", totalStars).put("borrowPlants", loans).put("runs", runs);
        // Clients with the original six portraits can still read the player file.
        if (avatar >= AdventureSocial.LEGACY_AVATAR_COUNT) result.put("avatarIndex", avatar);
        byte[] encoded = (result.toString() + "\n").getBytes(StandardCharsets.UTF_8);
        if (encoded.length > MAX_EXPORT_BYTES) throw new IOException("Export exceeds file limit");
        return new Export(id, name, encoded);
    }

    private static String recordName(String prefix, AdventureFormationRecord record) {
        String day = Integer.toHexString(record.day);
        return prefix + day + "-" + record.stars + ".run";
    }

    private static JSONObject encodeRecord(AdventureFormationRecord run, String alias, boolean formation)
            throws JSONException {
        JSONObject entry = new JSONObject().put("level", alias).put("stars", run.stars).put("elapsedMs", run.elapsedMs);
        JSONArray plants = new JSONArray();
        if (formation) {
            for (AdventureFormationRecord.Plant plant : run.plants) {
                JSONObject item = new JSONObject().put("type", plant.type).put("column", plant.column + 1)
                        .put("row", plant.row + 1).put("level", plant.level);
                if (plant.avatar) item.put("avatar", true);
                plants.put(item);
            }
            if (!run.cards.isEmpty()) {
                JSONArray cards = new JSONArray();
                for (AdventureFormationRecord.Card card : run.cards) {
                    cards.put(card == null ? JSONObject.NULL : new JSONObject().put("type", card.type).put("level", card.level));
                }
                entry.put("cards", cards);
            }
        }
        if (run.tacticalCukeUses >= 0) entry.put("tacticalCukeUses", run.tacticalCukeUses);
        return entry.put("plants", plants);
    }

    private static SharedPreferences destinations(Activity activity) {
        return activity.getSharedPreferences("adventure-export-destinations", 0);
    }

    private static void writeExport(Activity activity, Uri uri, Export export) throws IOException {
        try (OutputStream out = activity.getContentResolver().openOutputStream(uri, "wt")) {
            if (out == null) throw new IOException("Could not open export destination");
            out.write(export.data);
        }
    }

    private static void openDocument(Activity activity, Export export) {
        exporting = false;
        if (activity.isFinishing() || activity.isDestroyed()) return;
        pendingExport = export;
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("application/json").putExtra(Intent.EXTRA_TITLE, export.filename);
        try {
            activity.startActivityForResult(intent, SAVE_DOCUMENT);
        } catch (RuntimeException error) {
            pendingExport = null;
            finishExport(activity, "系统文件选择器不可用");
        }
    }

    static boolean onResult(Activity activity, int request, int result, Intent intent) {
        if (request != SAVE_DOCUMENT) return false;
        Export export = pendingExport;
        pendingExport = null;
        if (result != Activity.RESULT_OK || intent == null || intent.getData() == null) return true;
        if (export == null) {
            finishExport(activity, "请重新导出玩家数据");
            return true;
        }
        exporting = true;
        EXPORTS.execute(() -> {
            String message;
            Uri destination = intent.getData();
            try {
                writeExport(activity, destination, export);
                try {
                    activity.getContentResolver().takePersistableUriPermission(destination, Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                    destinations(activity).edit().putString(export.id, destination.toString())
                            .putString(export.id + ".filename", export.filename).apply();
                } catch (SecurityException ignored) {
                    // Some providers grant access only for this save operation.
                }
                message = "已导出玩家数据，可提交到 GitHub 好友库";
            } catch (IOException | RuntimeException error) {
                Log.w("AsterSocial", "Could not save exported player data", error);
                message = "无法保存玩家数据，请重试";
            }
            String text = message;
            activity.runOnUiThread(() -> finishExport(activity, text));
        });
        return true;
    }

    private static void finishExport(Activity activity, String text) {
        exporting = false;
        if (!activity.isFinishing() && !activity.isDestroyed()) Toast.makeText(activity, text, Toast.LENGTH_LONG).show();
    }

    static JSONArray candidates(Activity activity, int owner) throws JSONException {
        JSONArray result = new JSONArray();
        Set<Integer> ids = new HashSet<>();
        String ownId = identity(activity, owner);
        JSONArray snapshot = community;
        for (int i = 0; i < snapshot.length() && result.length() < MAX_FRIENDS; i++) {
            JSONObject player = snapshot.getJSONObject(i);
            if (!ownId.equals(player.getString("playerId")) && ids.add(player.getInt("id"))) result.put(player);
        }
        return result;
    }

    static boolean catalogAvailable() {
        return catalogAvailable;
    }

    static void refresh(Activity activity, JSONObject levels) {
        refresh(activity, levels, null);
    }

    static void refresh(Activity activity, JSONObject levels, Runnable onReady) {
        long now = SystemClock.elapsedRealtime();
        if (now >= nextRefresh) {
            nextRefresh = now + REFRESH_INTERVAL;
            AtomicFile cache = cache(activity);
            SYNC.execute(() -> {
                loadCache(cache);
                try {
                    JSONArray updated = download(levels, community);
                    byte[] data = updated.toString().getBytes(StandardCharsets.UTF_8);
                    if (data.length > MAX_CATALOG_BYTES)
                        throw new IOException("Community catalog exceeds its byte limit");
                    FileOutputStream out = cache.startWrite();
                    try {
                        out.write(data);
                        cache.finishWrite(out);
                    } catch (IOException error) {
                        cache.failWrite(out);
                        throw error;
                    }
                    community = updated;
                    catalogAvailable = true;
                    Log.i("AsterSocial", "Synced " + updated.length() + " GitHub player profiles");
                } catch (IOException | JSONException | RuntimeException error) {
                    if (!catalogAvailable) nextRefresh = SystemClock.elapsedRealtime() + RETRY_INTERVAL;
                    Log.w("AsterSocial", "Kept the previous GitHub friend list: " + error);
                }
            });
        }
        if (onReady != null) SYNC.execute(() -> activity.runOnUiThread(onReady));
    }

    static void prepare(Activity activity) {
        AtomicFile cache = cache(activity);
        SYNC.execute(() -> loadCache(cache));
    }

    private static AtomicFile cache(Activity activity) {
        return new AtomicFile(new File(activity.getCacheDir(), "adventure-community.json"));
    }

    private static void loadCache(AtomicFile cache) {
        if (loaded) return;
        loaded = true;
        try (FileInputStream in = cache.openRead()) {
            community = (JSONArray) json(read(in, MAX_CATALOG_BYTES));
            catalogAvailable = community.length() > 0;
        } catch (IOException | JSONException | ClassCastException ignored) {
            // An empty catalog is valid before the first download.
        }
    }

    private static JSONArray download(JSONObject levels, JSONArray cached) throws IOException, JSONException {
        Object response = json(fetch(CONTENTS, 2 * 1024 * 1024));
        if (!(response instanceof JSONArray)) throw new IOException("Expected a GitHub directory");
        JSONArray listing = (JSONArray) response;
        Map<String, JSONObject> old = new HashMap<>();
        for (int i = 0; i < cached.length(); ++i) {
            JSONObject player = cached.getJSONObject(i);
            old.put(player.optString("blob"), player);
        }
        ArrayList<JSONObject> files = new ArrayList<>();
        for (int i = 0; i < listing.length(); ++i) files.add(listing.getJSONObject(i));
        // Prefer a player-named file if the previous UUID-named copy is still present.
        files.sort(Comparator.comparing(row -> LEGACY_PLAYER_FILE.matcher(row.optString("name")).matches()));
        JSONArray updated = new JSONArray();
        Set<String> included = new HashSet<>();
        int size = 2;
        for (JSONObject row : files) {
            if (updated.length() >= MAX_FRIENDS) break;
            String name = row.optString("name");
            String sha = row.optString("sha");
            int bytes = row.optInt("size", -1);
            if (!"file".equals(row.optString("type")) || !name.endsWith(".json") || name.length() <= 5
                    || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0
                    || !sha.matches("[0-9a-f]{40}") || bytes < 1 || bytes > MAX_EXPORT_BYTES) continue;
            Matcher filename = LEGACY_PLAYER_FILE.matcher(name);
            String legacyId = filename.matches() ? filename.group(1) : null;
            if (legacyId != null && included.contains(legacyId)) continue;
            if (size + bytes + 128 > MAX_CATALOG_BYTES) continue;
            JSONObject player = old.get(sha);
            if (player == null || !player.has("totalStars")) {
                byte[] data = fetch(RAW + Uri.encode(name), MAX_EXPORT_BYTES);
                if (data.length != bytes || !sha.equals(blobSha(data))) throw new IOException("GitHub file changed during sync");
                try {
                    player = parsePlayer(data, legacyId, levels).put("blob", sha);
                } catch (IOException | JSONException invalid) {
                    Log.i("AsterSocial", "Skipped invalid community profile " + name);
                    continue;
                }
            }
            String id = player.getString("playerId");
            if ((legacyId != null && !legacyId.equals(id)) || !included.add(id)) continue;
            size += bytes + 128;
            updated.put(player);
        }
        return updated;
    }

    static int totalStars(JSONObject player) {
        if (!player.has("totalStars")) return 0;
        try {
            return AdventureSocial.integer(player, "totalStars", 0, Integer.MAX_VALUE);
        } catch (IOException | JSONException invalid) {
            return 0;
        }
    }

    static JSONObject parsePlayer(byte[] raw, String legacyId, JSONObject levels) throws IOException, JSONException {
        Object value = json(raw);
        if (!(value instanceof JSONObject)) throw new IOException("Expected one player per file");
        JSONObject player = (JSONObject) value;
        Object playerId = player.get("playerId");
        if (!(playerId instanceof String) || !((String) playerId).matches(UUID_PATTERN)
                || (legacyId != null && !legacyId.equals(playerId)) || !FORMAT.equals(player.get("format"))) {
            throw new IOException("Player ID or file format mismatch");
        }
        String id = (String) playerId;
        AdventureSocial.integer(player, "version", 1, 1);
        if (!(player.get("name") instanceof String)) throw new IOException("Invalid nickname");
        String name = PvpPresetDocument.validName(player.getString("name"));
        if (name.isEmpty()) throw new IOException("Empty nickname");
        int avatar = AdventureSocial.integer(player, "avatar", 0, AdventureSocial.LEGACY_AVATAR_COUNT - 1);
        JSONArray rawLoans = player.getJSONArray("borrowPlants");
        if (rawLoans.length() > 3) throw new IOException("Too many loan plants");
        JSONArray loans = new JSONArray();
        Set<String> loanTypes = new HashSet<>();
        for (int i = 0; i < rawLoans.length(); ++i) {
            JSONObject loan = rawLoans.getJSONObject(i);
            String type = AdventureSocial.plantType(loan);
            if (!loanTypes.add(type)) throw new IOException("Duplicate loan plant");
            loans.put(new JSONObject().put("type", type).put("level", AdventureSocial.integer(loan, "level", 1, 4)));
        }
        // The game protocol needs an integer ID. Derive a stable value from the public UUID.
        int friend = ByteBuffer.wrap(digest("SHA-256").digest(id.getBytes(StandardCharsets.US_ASCII))).getInt()
                & 0x3fffffff | 0x40000000;
        JSONArray rawRuns = player.getJSONArray("runs");
        if (rawRuns.length() > MAX_RUNS) throw new IOException("Too many player records");
        JSONArray runs = new JSONArray();
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < rawRuns.length(); ++i) {
            JSONObject run = rawRuns.getJSONObject(i);
            String alias = run.getString("level");
            JSONArray info = levels.optJSONArray(alias);
            if (info == null) continue;
            int key = info.getInt(0);
            int tiers = info.getInt(1);
            int stars = AdventureSocial.integer(run, "stars", tiers == 1 ? 1 : 0, tiers);
            if (!seen.add(((long) key << 2) | stars)) throw new IOException("Duplicate community record");
            boolean formation = info.getBoolean(2);
            byte[] record = AdventureSocial.encodeRun(run, friend, key, stars, formation);
            AdventureFormationRecord validated = AdventureFormationRecord.read(new java.io.ByteArrayInputStream(record));
            runs.put(encodeRecord(validated, alias, formation));
        }
        JSONObject result = new JSONObject().put("id", friend).put("playerId", id).put("name", name).put("avatar", avatar)
                .put("totalStars", totalStars(player)).put("borrowPlants", loans).put("runs", runs);
        if (player.has("avatarIndex")) {
            int index = AdventureSocial.integer(player, "avatarIndex",
                    AdventureSocial.LEGACY_AVATAR_COUNT, AdventureSocial.AVATAR_COUNT - 1);
            result.put("avatarIndex", index);
        }
        return result;
    }

    private static byte[] fetch(String address, int limit) throws IOException {
        HttpsURLConnection connection = (HttpsURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(4500);
        connection.setReadTimeout(6000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("User-Agent", "PvZ2-Unline-Aster");
        try {
            if (connection.getResponseCode() != 200) throw new IOException("GitHub HTTP " + connection.getResponseCode());
            try (InputStream in = connection.getInputStream()) {
                return read(in, limit);
            }
        } finally {
            connection.disconnect();
        }
    }

    private static String blobSha(byte[] bytes) {
        MessageDigest hash = digest("SHA-1");
        hash.update(("blob " + bytes.length + "\0").getBytes(StandardCharsets.US_ASCII));
        StringBuilder hex = new StringBuilder(40);
        for (byte b : hash.digest(bytes)) {
            hex.append(Character.forDigit((b & 0xff) >>> 4, 16)).append(Character.forDigit(b & 15, 16));
        }
        return hex.toString();
    }

    private static MessageDigest digest(String algorithm) {
        try {
            return MessageDigest.getInstance(algorithm);
        } catch (NoSuchAlgorithmException unavailable) {
            throw new AssertionError(unavailable);
        }
    }
}

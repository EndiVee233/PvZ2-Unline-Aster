package com.popcap.pvz2cthd;

import android.app.Activity;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class AdventureFriendRoster {
    private static final int LIMIT = 6;
    private static final int LIST = 9, CATALOG = 10, ADD = 11, REMOVE = 12;
    private static final int OK = 0, FULL = 1, UNAVAILABLE = 2, SAVE_ERROR = 3;
    private static final int ROW_SIZE = 168;
    private static final int NAME_CODE_POINTS = 39;

    private AdventureFriendRoster() {}

    private static SharedPreferences storage(Activity activity) {
        return activity.getSharedPreferences("adventure-friend-roster", 0);
    }

    private static String profileKey(int owner) {
        return Integer.toUnsignedString(owner);
    }

    private static Map<Integer, JSONObject> players(JSONArray source) {
        Map<Integer, JSONObject> entries = new LinkedHashMap<>();
        for (int i = 0; i < source.length(); i++) {
            JSONObject player = source.optJSONObject(i);
            // GitHub UUID-derived IDs occupy this range. Drop legacy demo rows.
            if (player == null || player.optInt("id") < 0x40000000) continue;
            try {
                String name = PvpPresetDocument.validName(player.optString("name"));
                if (!name.isEmpty()) entries.putIfAbsent(player.optInt("id"), player);
            } catch (IOException ignored) {
                // A malformed display name cannot enter the roster.
            }
        }
        return entries;
    }

    private static Map<Integer, JSONObject> roster(Activity activity, int owner) throws JSONException {
        JSONArray saved = new JSONArray(storage(activity).getString(profileKey(owner), "[]"));
        if (saved.length() > LIMIT) throw new JSONException("Invalid roster size");
        return players(saved);
    }

    static JSONArray selected(Activity activity, int owner, JSONArray candidates) throws JSONException {
        Map<Integer, JSONObject> available = players(candidates);
        JSONArray selected = new JSONArray();
        for (Integer id : roster(activity, owner).keySet()) {
            JSONObject player = available.get(id);
            if (player != null) selected.put(player);
        }
        return selected;
    }

    static byte[] respond(Activity activity, int owner, int operation, int value, JSONArray candidates)
            throws IOException, JSONException {
        Map<Integer, JSONObject> available = players(candidates);
        Map<Integer, JSONObject> friends = roster(activity, owner);
        int status = OK;
        if (operation == ADD || operation == REMOVE) {
            Map<Integer, JSONObject> changed = new LinkedHashMap<>(friends);
            if (operation == ADD && !friends.containsKey(value)) {
                JSONObject candidate = available.get(value);
                if (candidate == null) status = UNAVAILABLE;
                else if (friends.size() >= LIMIT) status = FULL;
                else changed.put(value, summary(candidate));
            } else if (operation == REMOVE) {
                changed.remove(value);
            }
            if (!changed.equals(friends)) {
                JSONArray saved = new JSONArray();
                for (JSONObject player : changed.values()) saved.put(player);
                if (storage(activity).edit().putString(profileKey(owner), saved.toString()).commit())
                    friends = changed;
                else status = SAVE_ERROR;
            }
        }

        boolean addTab = operation == CATALOG || operation == ADD;
        List<JSONObject> rows = new ArrayList<>();
        if (addTab) {
            for (Map.Entry<Integer, JSONObject> candidate : available.entrySet()) {
                if (!friends.containsKey(candidate.getKey())) rows.add(candidate.getValue());
            }
        } else {
            for (Map.Entry<Integer, JSONObject> friend : friends.entrySet())
                rows.add(available.getOrDefault(friend.getKey(), friend.getValue()));
        }
        int maxPage = Math.max(0, (rows.size() - 1) / LIMIT);
        int page = operation == LIST || operation == CATALOG ? Math.min(Math.max(0, value), maxPage) : 0;
        int first = page * LIMIT;
        int count = Math.min(LIMIT, rows.size() - first);
        ByteBuffer data = ByteBuffer.allocate(20 + ROW_SIZE * count).order(ByteOrder.LITTLE_ENDIAN);
        data.putInt(status).putInt(friends.size()).putInt(rows.size()).putInt(page).putInt(count);
        for (int i = first; i < first + count; i++) {
            JSONObject player = summary(rows.get(i));
            data.putInt(player.getInt("id")).putInt(player.optInt("avatarIndex", player.getInt("avatar")));
            int end = data.position() + NAME_CODE_POINTS * Integer.BYTES;
            player.getString("name").codePoints().limit(NAME_CODE_POINTS - 1).forEach(data::putInt);
            data.position(end).putInt(player.getInt("totalStars"));
        }
        return data.array();
    }

    private static JSONObject summary(JSONObject player) throws IOException, JSONException {
        int avatar = player.optInt("avatar", -1);
        JSONObject result = new JSONObject().put("id", player.getInt("id"))
                .put("name", PvpPresetDocument.validName(player.getString("name")))
                .put("avatar", avatar >= 0 && avatar < AdventureSocial.LEGACY_AVATAR_COUNT ? avatar : -1)
                .put("totalStars", AdventureFriendFiles.totalStars(player));
        int index = player.optInt("avatarIndex", -1);
        if (index >= AdventureSocial.LEGACY_AVATAR_COUNT && index < AdventureSocial.AVATAR_COUNT)
            result.put("avatarIndex", index);
        return result;
    }
}

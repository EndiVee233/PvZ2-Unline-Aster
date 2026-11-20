package com.popcap.pvz2cthd;

import java.io.File;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Device-side migration test. Only the shipped fixture and generated data are used. */
public final class PresetImporterTest {
    private static void require(boolean value, String description) {
        if (!value) throw new AssertionError(description);
    }

    private static JSONObject player(JSONObject fixture, String uid, String name, long id) throws Exception {
        JSONObject row = new JSONObject(fixture.toString());
        row.put("uid", uid);
        row.getJSONObject("objdata").put("n", name).put("i", id);
        return row;
    }

    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        require(root.getCanonicalPath().equals("/data/local/tmp/aster-a193-profile-unit"), "fixture root");
        File save = new File(root, "pp.dat");
        File plain = new File(root, "fixture.json");
        File decoded = new File(root, "decoded.json");
        JSONObject doc = PresetProfileImporter.decode(new File(root, "public-preset.dat"), decoded);
        JSONObject fixture = doc.getJSONArray("objects").getJSONObject(0);
        long oldId = 1722523140L;
        JSONArray retained = new JSONArray();
        retained.put(player(fixture, "1.0.0000002a", "全一 TEST", oldId));
        retained.put(player(fixture, "1.0.7e860001", "全一 TEST", 54321));
        retained.put(player(fixture, "1.0.7e860401", "OUTSIDE RANGE", oldId));
        retained.put(player(fixture, "1.193.41535452", "NEW MANAGED", 1234567890));
        retained.put(player(fixture, "1.0.7e860123", "OTHER CLASS", oldId).put("objclass", "Other"));
        retained.getJSONObject(0).getJSONObject("objdata").put("largeGuard", 9007199254740993L);
        JSONArray input = new JSONArray(retained.toString());
        input.put(player(fixture, "1.0.7e860002", "RENAMED", oldId));
        input.put(player(fixture, "1.0.7E860400", "SECOND OLD ROW", oldId));
        doc.put("objects", input);
        PresetProfileImporter.write(plain, doc.toString().getBytes("UTF-8"));
        PresetProfileImporter.codec("encodeAndEncrypt", plain, save);
        require(PresetProfileImporter.retireLegacy(save, root), "retired historical imports");
        doc.put("objects", retained);
        require(PresetProfileImporter.same(doc, PresetProfileImporter.decode(save, decoded)), "all other records preserved");
        byte[] once = PresetProfileImporter.read(save);
        require(!PresetProfileImporter.retireLegacy(save, root), "repeat boot");
        require(Arrays.equals(once, PresetProfileImporter.read(save)), "repeat leaves bytes intact");
        File absent = new File(root, "absent.dat");
        require(!PresetProfileImporter.retireLegacy(absent, root) && !absent.exists(), "fresh install");
        File corrupt = new File(root, "corrupt.dat");
        byte[] damaged = {5, 4, 3};
        PresetProfileImporter.write(corrupt, damaged);
        boolean rejected = false;
        try { PresetProfileImporter.retireLegacy(corrupt, root); }
        catch (Exception expected) { rejected = true; }
        require(rejected && Arrays.equals(damaged, PresetProfileImporter.read(corrupt)), "damaged save preserved");
        System.out.println("PROFILE_MIGRATION_OK removed=2 preserved=5 repeat=ok absent=ok corrupt=ok");
    }
}

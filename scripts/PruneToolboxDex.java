import com.android.tools.smali.baksmali.Adaptors.ClassDefinition;
import com.android.tools.smali.baksmali.BaksmaliOptions;
import com.android.tools.smali.baksmali.formatter.BaksmaliWriter;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Recover just the shared classes reachable from the game and save migration. */
public final class PruneToolboxDex {
    private static final Pattern DESCRIPTOR = Pattern.compile("L[\\p{L}\\p{N}_$/-]+;");
    private static final Pattern CLASS_NAME = Pattern.compile(
            "[\\p{L}\\p{N}_$-]+(?:[./][\\p{L}\\p{N}_$-]+)+");
    private static final Pattern DISPLAY = Pattern.compile(
            "(?ms)^\\.method public static final getDefaultDisplay"
            + "\\(Landroid/view/WindowManager;\\)Landroid/view/Display;\\R.*?^\\.end method");
    private static final Set<String> TOOLBOX_DEX = Set.of(
            "classes3.dex", "classes4.dex", "classes5.dex", "classes6.dex", "classes7.dex");
    private final Map<String, ClassDef> candidates = new HashMap<>();
    private final Set<String> selected = new HashSet<>();
    private final ArrayDeque<String> pending = new ArrayDeque<>();
    private final Map<String, String> referencedBy = new HashMap<>();
    private final BaksmaliOptions options = new BaksmaliOptions();

    private void select(String type, String caller) {
        if (candidates.containsKey(type) && selected.add(type)) {
            pending.addLast(type);
            referencedBy.put(type, caller);
        }
    }

    private void references(String text, String caller) {
        Matcher direct = DESCRIPTOR.matcher(text);
        while (direct.find()) {
            select(direct.group(), caller);
        }
        // Keep exact dotted/binary names used for reflective loading and JNI.
        Matcher reflective = CLASS_NAME.matcher(text);
        while (reflective.find()) {
            select("L" + reflective.group().replace('.', '/') + ";", caller);
        }
    }

    private static String removeToolboxDisplay(String source) {
        Matcher method = DISPLAY.matcher(source);
        if (!method.find() || !method.group().contains("Lio/github/dreammooncai/pvz2tool/ui/main/SettingsDialogState;")) {
            throw new IllegalStateException("Unexpected toolbox display bridge");
        }
        // Get the system display directly after dropping the launcher's sizing settings.
        return method.replaceFirst(Matcher.quoteReplacement(
                ".method public static final getDefaultDisplay(Landroid/view/WindowManager;)Landroid/view/Display;\n"
                + "    .registers 1\n"
                + "    invoke-interface {p0}, Landroid/view/WindowManager;->getDefaultDisplay()Landroid/view/Display;\n"
                + "    move-result-object p0\n"
                + "    return-object p0\n"
                + ".end method"))
                .replaceAll("(?m)^\\.field private static windowDisplay:LCustomDisplay;\\R", "")
                .replaceAll("(?ms)^\\.annotation runtime Lkotlin/Metadata;\\R.*?^\\.end annotation\\R", "");
    }

    private void recover(Path input, Path output) throws Exception {
        var live = new ArrayDeque<DexBackedDexFile>();
        try (var files = Files.list(input)) {
            for (Path file : (Iterable<Path>) files.filter(p -> p.toString().endsWith(".dex"))::iterator) {
                var dex = new DexBackedDexFile(null, Files.readAllBytes(file), 0);
                if (!TOOLBOX_DEX.contains(file.getFileName().toString())) {
                    live.add(dex);
                    continue;
                }
                for (Object row : dex.classSection) {
                    ClassDef def = (ClassDef) row;
                    if (candidates.putIfAbsent(def.getType(), def) != null) {
                        throw new IllegalStateException("Duplicate class: " + def.getType());
                    }
                }
            }
        }
        for (var dex : live) {
            for (int i = 0; i < dex.stringSection.size(); ++i) {
                references(dex.stringSection.get(i), "game DEX string");
            }
        }
        references(Files.readString(input.resolve("external-class-references.txt")), "manifest or JNI");
        // Fast ServiceLoader assembles this class name conditionally on Android.
        select("Lkotlinx/coroutines/android/AndroidDispatcherFactory;", "coroutines dispatcher");

        while (!pending.isEmpty()) {
            String type = pending.removeFirst();
            StringWriter text = new StringWriter();
            try (var writer = new BaksmaliWriter(text, type)) {
                new ClassDefinition(options, candidates.get(type)).writeTo(writer);
            }
            String source = text.toString();
            if (type.equals("LDreamRootPath;")) {
                source = removeToolboxDisplay(source);
            }
            references(source, type);
            Path file = output.resolve(type.substring(1, type.length() - 1) + ".smali");
            Files.createDirectories(file.getParent());
            Files.writeString(file, source, StandardCharsets.UTF_8);
        }
        if (!selected.contains("Lio/github/dreammooncai/pvz2tool/pop/rton/RTON;")
                || !selected.contains("Landroidx/core/content/FileProvider;")) {
            throw new IllegalStateException("Missing the migration codec or declared content provider");
        }
        var ui = selected.stream().filter(t -> t.startsWith("Lio/github/dreammooncai/pvz2tool/ui/")).findFirst();
        if (ui.isPresent()) {
            String owner = ui.get();
            StringBuilder path = new StringBuilder(owner);
            while (referencedBy.containsKey(owner)) {
                owner = referencedBy.get(owner);
                path.append(" <- ").append(owner);
            }
            throw new IllegalStateException("The game still reaches the toolbox UI: " + path);
        }
        System.out.printf("Retained %d of %d classes from the old launcher DEX files.%n",
                selected.size(), candidates.size());
    }

    public static void main(String[] args) throws Exception {
        new PruneToolboxDex().recover(Path.of(args[0]), Path.of(args[1]));
    }
}

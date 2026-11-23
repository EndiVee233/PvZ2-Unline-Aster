// Offline calendar data and claim guards for Aster's original daily sign-in UI.
using Address = unsigned;
using Object = unsigned char*;
using Seconds = int;

template<class T> static T& field(Object object, unsigned offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R native(Address base, Address offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

struct CivilDate {
    int year;
    int month;
    int day;

    int monthKey() const { return year * 12 + month; }
    int dayKey() const { return monthKey() * 32 + day; }
};

struct Reward {
    const char* alias;
    unsigned type;
    unsigned amount;
};

#include "annual_rewards.inc"

// Only the sign-in screen reads this view of the original DailyRewardConfig.
struct Calendar {
    Address unusedVtable;
    unsigned version;
    int year;
    int month;
    int startDay;
    Reward* begin;
    Reward* end;
    Reward* capacity;
};

static constexpr unsigned signIndex = 0x3a0;
static constexpr unsigned signClaimed = 0x3a4;
static constexpr unsigned signDate = 0x3b4;
static constexpr unsigned signTileClaimed = 0x3c8;
static constexpr unsigned makeupPrice = 10;
// Store the month, claimed prefix and last free day together in the native
// profile's saved sign-in counter. Older versions used an untagged day number.
static constexpr unsigned progressTag = 0x53000000;
struct SignProgress { int count, freeDay; };
static constexpr unsigned noOwner = ~0U;
static constexpr char claimMarkKey[] = "IMAGE_EFFECTS_SIGNREWARD_GET_SIGNREWARD_GET_136X106";
static Reward rewards[31];
static DayReward resolvedRewards[31];
static const char* nativeAliases[unsigned(Item::Count)];
struct TileLabels {
    const char32_t* title;
    const char32_t* amount;
    const char32_t* firstLine;
    const char32_t* secondLine;
    Object stockFont;
    Object fittedFont;
    int fittedWidth;
    bool split;
};
static TileLabels tileLabels[31];
static Object claimMark;
static Object makeupDialog;
static Object makeupButton;
static SignProgress progress;
static Calendar calendar;
static unsigned calendarOwner = noOwner;
static Object calendarPlayer;
static int calendarDay = 0;
static bool openingCalendar;

static unsigned owner(Address base) {
    Object manager = field<Object>(reinterpret_cast<Object>(base), 0x18300a4);
    return manager ? field<unsigned>(manager, 0x74) : noOwner;
}

static Object profile(Address base) {
    if (owner(base) == noOwner) return nullptr;
    Object store = native<Object>(base, 0x1df738);
    return store ? native<Object>(base, 0x7a98dc, store) : nullptr;
}

static Object gameApp(Address base) {
    const auto holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return holder ? field<Object>(holder, 0) : nullptr;
}

static bool localDate(Address base, Seconds when, CivilDate& date) {
    if (when <= 0) return false;
    const auto* tm = native<const int*>(base, 0x147854, &when);
    if (!tm) return false;
    date = {tm[5] + 1900, tm[4] + 1, tm[3]};
    return date.year >= 1970 && date.month >= 1 && date.month <= 12 &&
        date.day >= 1 && date.day <= 31;
}

static Seconds now(Address base) {
    return native<Seconds>(base, 0x147824, nullptr);
}

static int monthLength(const CivilDate& date) {
    static constexpr int lengths[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return lengths[date.month - 1] +
        (date.month == 2 && date.year % 4 == 0 &&
         (date.year % 100 != 0 || date.year % 400 == 0));
}

static bool readProgress(Address base, Object player, const CivilDate& today, SignProgress& out) {
    const unsigned saved = field<unsigned>(player, signIndex);
    if ((saved & 0xff000000U) != progressTag) {
        CivilDate previous{};
        const bool hasDate = localDate(base, field<Seconds>(player, signDate), previous);
        if (hasDate && previous.dayKey() > today.dayKey()) return false;
        const bool usedFree = hasDate && previous.dayKey() == today.dayKey() &&
            field<unsigned char>(player, signClaimed);
        out = {0, usedFree ? today.day : 0};
        return true;
    }
    const int month = 2020 * 12 + 1 + int((saved & 0x00ffffffU) >> 10);
    if (month > today.monthKey()) return false;
    if (month != today.monthKey()) {
        out = {0, 0};
        return true;
    }
    out = {int((saved >> 5) & 31), int(saved & 31)};
    return out.count <= today.day && out.freeDay <= today.day;
}

static void storeProgress(Object player, const CivilDate& today, SignProgress next) {
    const unsigned month = today.monthKey() - (2020 * 12 + 1);
    field<unsigned>(player, signIndex) = progressTag | (month << 10) | (unsigned(next.count) << 5) | next.freeDay;
}

static bool freeAvailable(const CivilDate& date, SignProgress state) {
    return state.count < date.day && state.freeDay != date.day;
}

static bool makeupAvailable(const CivilDate& date, SignProgress state) {
    return state.count < date.day && state.freeDay == date.day;
}

extern "C" bool asterDailySignAvailable(Address base, Object player) {
    CivilDate today{};
    SignProgress state{};
    return player && localDate(base, now(base), today) && today.year >= 2020 &&
        readProgress(base, player, today, state) && freeAvailable(today, state);
}

static const DayReward* monthRewards(const CivilDate& date) {
    return annualRewards[date.month - 1];
}

static const char*& nativeAlias(Address base, Item item) {
    const unsigned index = item == Item::Gold || item == Item::Gems ? unsigned(Item::None) : unsigned(item);
    auto& alias = nativeAliases[index];
    if (!alias) {
        char allocator = 0;
        native<void>(base, 0x14ed0e1, &alias, items[index].alias, &allocator);
    }
    return alias;
}

static bool sameReward(DayReward left, DayReward right) {
    return left.kind == right.kind && left.item == right.item && left.amount == right.amount;
}

static DayReward resolveReward(Address base, Object player, DayReward reward) {
    if (reward.kind == Kind::Plant && native<bool>(base, 0x708e18, player, &nativeAlias(base, reward.item)))
        return {Kind::PlantShard, reward.item, 10};
    if (reward.kind == Kind::Costume && native<bool>(base, 0x708890, player, &nativeAlias(base, reward.item), 0U))
        return {Kind::CostumeShard, reward.item, 10};
    return reward;
}

static unsigned tileKind(Kind kind) {
    switch (kind) {
    case Kind::Coins: return 0;
    case Kind::Diamonds: return 1;
    case Kind::WorldKey: return 2;
    // The native plant tile requires a shop product. Resolve the icon separately.
    default: return 9;
    }
}

static void releaseLabel(Address base, const char32_t*& label) {
    if (!label) return;
    char allocator = 0;
    native<void>(base, 0x14ea239, label - 3, &allocator);
    label = nullptr;
}

static void releaseTileLabels(Address base, TileLabels& labels) {
    releaseLabel(base, labels.title);
    releaseLabel(base, labels.amount);
    releaseLabel(base, labels.firstLine);
    releaseLabel(base, labels.secondLine);
    labels.stockFont = nullptr;
}

static bool prepareCalendar(Address base, Object player, Seconds when) {
    CivilDate today{};
    SignProgress state{};
    if (!localDate(base, when, today) || today.year < 2020 || !readProgress(base, player, today, state))
        return false;
    const int days = monthLength(today);
    const bool claimUnavailable = !freeAvailable(today, state);
    field<unsigned char>(player, signClaimed) = claimUnavailable;
    field<unsigned char>(player, signTileClaimed) = claimUnavailable;

    const unsigned user = owner(base);
    const bool sameMonth = calendar.year == today.year && calendar.month == today.month &&
        calendarOwner == user && calendarPlayer == player;
    const DayReward* month = monthRewards(today);
    for (int index = 0; index < days; ++index) {
        if (sameMonth && index < state.count) continue;
        const DayReward day = index < state.count ? month[index] : resolveReward(base, player, month[index]);
        if (!sameReward(day, resolvedRewards[index])) {
            releaseTileLabels(base, tileLabels[index]);
        }
        resolvedRewards[index] = day;
        rewards[index] = {nativeAlias(base, day.item), tileKind(day.kind), day.amount};
    }
    calendar.unusedVtable = 0;
    calendar.version = 1;
    calendar.year = today.year;
    calendar.month = today.month;
    calendar.startDay = 1;
    calendar.begin = rewards;
    calendar.end = rewards + days;
    calendar.capacity = calendar.end;
    calendarOwner = user;
    calendarPlayer = player;
    calendarDay = today.dayKey();
    progress = state;
    claimMark = nullptr;
    return true;
}

extern "C" void asterDailySignOpen(Address base) {
    Object player = profile(base);
    Object app = gameApp(base);
    if (!player || !app || openingCalendar || !prepareCalendar(base, player, now(base))) return;
    openingCalendar = true;
    native<unsigned>(base, 0x4184f8, app);
    openingCalendar = false;
}

extern "C" Calendar* asterDailySignOpeningConfig(Address) {
    return openingCalendar ? &calendar : nullptr;
}

extern "C" Calendar* asterDailySignConfig(Address) {
    return &calendar;
}

extern "C" int asterDailySignCurrentSlot() {
    if (!calendar.begin) return 0;
    const int days = calendar.end - calendar.begin;
    const int slot = progress.count + 1;
    return slot < days ? slot : days;
}

static char32_t* writeLabel(char32_t* target, const char32_t* prefix, unsigned amount) {
    while (*prefix) *target++ = *prefix++;
    unsigned digits[5];
    unsigned count = 0;
    do {
        digits[count++] = '0' + amount % 10;
        amount /= 10;
    } while (amount);
    while (count) *target++ = digits[--count];
    return target;
}

static void makeLabel(Address base, const char32_t** output, const char32_t* text) {
    char allocator = 0;
    native<void>(base, 0x14eb451, output, text, &allocator);
}

struct ImageSkin { unsigned drawMode; Object image; unsigned options[6]; };

static void resolveSkin(Address base, ImageSkin& skin, const char* key, unsigned mode) {
    struct ImageDescriptor { unsigned reserved[3]; const char* key; unsigned ref[2]; };
    ImageDescriptor descriptor;
    descriptor.key = key;
    descriptor.ref[0] = descriptor.ref[1] = 0;
    skin.image = nullptr;
    native<void>(base, 0x7e8a28, &skin, &descriptor, mode);
    native<void>(base, 0x1d9bb4, &descriptor.ref, 0U, 0U, 0U);
}

static Object rewardImage(Address base, const char* key) {
    ImageSkin skin;
    resolveSkin(base, skin, key, 2U);
    return skin.image;
}

static Object wholePlantImage(Address base, Item plant, const ItemSpec& item) {
    // Use the artwork layer of the seed packet, without its card frame or sun price.
    if (plant == Item::Lotusshower) return rewardImage(base, "IMAGE_UI_PACKETS_LOTUSHOOTER");
    char key[sizeof("IMAGE_UI_PACKETS_") + sizeof(item.alias) - 1] = "IMAGE_UI_PACKETS_";
    auto* output = key + sizeof("IMAGE_UI_PACKETS_") - 1;
    for (const char* ch = item.alias; *ch; ++ch) *output++ = *ch - ('a' - 'A');
    *output = 0;
    return rewardImage(base, key);
}

extern "C" void asterDailySignTile(Address base, Object tile, const Reward* reward) {
    const Reward display{reward->alias, reward->type, 0};
    native<void>(base, 0xf6347c, tile, &display, 1);
    const int index = reward - rewards;
    if (index < 0 || index >= calendar.end - calendar.begin) return;
    const DayReward day = resolvedRewards[index];
    const ItemSpec& item = items[unsigned(day.item)];
    if (reward->type == 9) {
        const bool costume = day.kind == Kind::Costume || day.kind == Kind::CostumeShard;
        const auto image = day.kind == Kind::Plant ? wholePlantImage(base, day.item, item)
            : rewardImage(base, costume ? item.costumeIcon : item.icon);
        if (image) field<Object>(tile, 0xa4) = image;
    }
    if (index + 1 == asterDailySignCurrentSlot())
        claimMark = rewardImage(base, claimMarkKey);
    char32_t text[24];
    auto& labels = tileLabels[index];
    if (!labels.title) {
        char32_t* name = text;
        for (const auto* c = item.name; *c; ++c) *name++ = *c;
        char32_t* split = name;
        static constexpr char32_t suffixes[][5] = {
            U"", U"", U"", U"整株", U"碎片", U"装扮", U"装扮碎片", U"", U"",
        };
        const char32_t* suffix = suffixes[unsigned(day.kind)];
        while (*suffix) *name++ = *suffix++;
        *name = 0;
        makeLabel(base, &labels.title, text);
        if (name - text > 5) {
            if (day.kind == Kind::AccessoryShard && name - text == 7) split = name - 2;
            if (split == name || split - text > 5) split = text + (name - text + 1) / 2;
            makeLabel(base, &labels.secondLine, split);
            *split = 0;
            makeLabel(base, &labels.firstLine, text);
        }
        *writeLabel(text, U"×", day.amount) = 0;
        makeLabel(base, &labels.amount, text);
    }
}

struct DrawRegisters {
    Object font;
    Object graphics;
    float x;
    float y;
    Object tile;
};

struct DrawStack {
    float width;
    const char32_t* const* text;
    unsigned alignment;
    Object style;
    unsigned flags;
};

static void drawRewardImage(Address base, Object graphics, Object image,
                            int centerX, int centerY, int maxWidth, int maxHeight) {
    if (!image) return;
    const int width = field<int>(image, 0x28);
    const int height = field<int>(image, 0x2c);
    if (width <= 0 || height <= 0) return;
    const float fitX = float(maxWidth) / width;
    const float fitY = float(maxHeight) / height;
    const float scale = fitX < fitY ? fitX : fitY;
    const int drawnWidth = int(width * scale);
    const int drawnHeight = int(height * scale);
    native<void>(base, 0x11698b4, graphics, image, centerX - drawnWidth / 2, centerY - drawnHeight / 2,
                 drawnWidth, drawnHeight);
}

static void fitTitle(Address base, TileLabels& labels, Object stockFont, int width) {
    if (labels.stockFont == stockFont && labels.fittedWidth == width) return;
    labels.stockFont = stockFont;
    labels.fittedWidth = width;
    Object font = stockFont;
    int measured = native<int>(base, 0x13ae4f0, font, &labels.title);
    const int minimum = measured * 4 / 5;
    while (measured > width) {
        const Object smaller = field<Object>(font, 0x2c0);
        if (!smaller) break;
        const int nextWidth = native<int>(base, 0x13ae4f0, smaller, &labels.title);
        if (nextWidth < minimum || nextWidth >= measured) break;
        measured = nextWidth;
        font = smaller;
    }
    labels.split = measured > width && labels.secondLine;
    labels.fittedFont = font;
}

extern "C" void asterDailySignDraw(Address base, const DrawRegisters& args, const DrawStack& stack) {
    auto draw = [&](Object font, float y, const char32_t* const* text, float inset = 0.0f) {
        native<void>(base, 0x13af2d0, font, args.graphics, args.x + inset, y, stack.width - 2 * inset,
                     text, stack.alignment, stack.style, stack.flags);
    };
    const int index = field<int>(args.tile, 0xd8);
    if (index < 0 || index >= calendar.end - calendar.begin) {
        draw(args.font, args.y, stack.text);
        return;
    }
    auto& labels = tileLabels[index];
    const int width = field<int>(args.tile, 0x30);
    const int height = field<int>(args.tile, 0x34);
    const int inset = width / 10;
    fitTitle(base, labels, args.font, width - inset * 2);
    drawRewardImage(base, args.graphics, field<Object>(args.tile, 0xa4),
                    width / 2, height * (labels.split ? 51 : 45) / 100,
                    width * 68 / 100, height * (labels.split ? 30 : 44) / 100);
    if (labels.split) {
        draw(labels.fittedFont, args.y, &labels.firstLine, inset);
        draw(labels.fittedFont, args.y + height * 0.13f, &labels.secondLine, inset);
    } else {
        draw(labels.fittedFont, args.y, &labels.title, inset);
    }
    draw(args.font, height * 0.65f, &labels.amount);
    if (index < progress.count) {
        drawRewardImage(base, args.graphics, claimMark, width / 2, height * 72 / 100,
                        width * 45 / 100, height * 36 / 100);
    }
}

static unsigned walletBalance(Object player, unsigned offset) {
    const unsigned salt = field<unsigned>(player, offset + 4);
    const unsigned encoded = field<unsigned>(player, offset);
    const unsigned shift = salt & 31;
    return ((encoded >> shift) | (encoded << ((32 - shift) & 31))) ^ salt;
}

template<class... A> static void widgetCall(Object widget, unsigned slot, A... args) {
    field<void(*)(Object, A...)>(field<Object>(widget, 0), slot)(widget, args...);
}

static void updateMakeupButton(const CivilDate& today) {
    if (makeupButton) {
        const bool enabled = makeupAvailable(today, progress) &&
            walletBalance(calendarPlayer, 0xa0) >= makeupPrice;
        widgetCall(makeupButton, 0xa4, unsigned(!enabled));
    }
}

static unsigned plantBalance(Object player, unsigned plantId) {
    struct ShardBalance { unsigned id, count; };
    const auto* entry = field<const ShardBalance*>(player, 0x208);
    const auto* end = field<const ShardBalance*>(player, 0x20c);
    for (; entry != end; ++entry) {
        if (entry->id == plantId) return entry->count;
    }
    return 0;
}

static unsigned costumeBalance(Object player, unsigned plantId) {
    struct CostumeBalance { unsigned id; const unsigned* count; unsigned end, capacity; };
    const auto* entry = field<const CostumeBalance*>(player, 0x3c);
    const auto* end = field<const CostumeBalance*>(player, 0x40);
    for (; entry != end; ++entry) {
        if (entry->id == plantId && entry->count) return entry->count[0];
    }
    return 0;
}

static unsigned accessoryBalance(Object player, const char* name) {
    struct AccessoryBalance { const char* name; unsigned count; };
    const auto* entry = field<const AccessoryBalance*>(player, 0x2d8);
    const auto* end = field<const AccessoryBalance*>(player, 0x2dc);
    for (; entry != end; ++entry) {
        const char* left = entry->name;
        const char* right = name;
        while (*left && *left == *right) { ++left; ++right; }
        if (*left == *right) return entry->count;
    }
    return 0;
}

static unsigned balance(Address base, Object player, DayReward day, const char* const* alias) {
    const unsigned id = items[unsigned(day.item)].id;
    switch (day.kind) {
    case Kind::Coins: return walletBalance(player, 0x98);
    case Kind::Diamonds: return walletBalance(player, 0xa0);
    case Kind::Plant: return native<bool>(base, 0x708e18, player, alias);
    case Kind::PlantShard: return plantBalance(player, id);
    case Kind::Costume: return native<bool>(base, 0x708890, player, alias, 0U);
    case Kind::CostumeShard: return costumeBalance(player, id);
    case Kind::WorldKey: return native<unsigned>(base, 0x706da0, player, alias);
    case Kind::AccessoryShard: return accessoryBalance(player, *alias);
    default: return 0;
    }
}

static void grant(Address base, Object player, DayReward day, const char* const* alias) {
    const unsigned amount = day.amount;
    switch (day.kind) {
    case Kind::Coins: native<void>(base, 0x746164, player, amount); break;
    case Kind::Diamonds: native<void>(base, 0x745220, player, amount, 0U); break;
    case Kind::Plant:
        native<void>(base, 0x744554, player, alias, 1U);
        native<void>(base, 0x7233ec, player, alias, 0U);
        break;
    case Kind::PlantShard: native<void>(base, 0x729ebc, player, alias, amount); break;
    case Kind::Costume:
        native<void>(base, 0x722624, player, alias, 0U);
        native<void>(base, 0x717c24, player, alias, 0U);
        break;
    case Kind::CostumeShard: native<void>(base, 0x729e8c, player, alias, 0U, amount, 1U); break;
    case Kind::WorldKey: native<void>(base, 0x7492d4, player, alias, amount); break;
    case Kind::AccessoryShard: native<void>(base, 0x729440, player, alias, amount); break;
    default: break;
    }
}

static bool commit(Address base, Object player, const Reward* reward, bool makeup) {
    CivilDate today{};
    SignProgress saved{};
    if (!player || player != calendarPlayer || calendarOwner == noOwner ||
        owner(base) != calendarOwner || profile(base) != player ||
        !localDate(base, now(base), today) || today.dayKey() != calendarDay ||
        !readProgress(base, player, today, saved) ||
        saved.count != progress.count || saved.freeDay != progress.freeDay) return false;
    if (!(makeup ? makeupAvailable(today, saved) : freeAvailable(today, saved))) return false;
    const int index = saved.count;
    if (reward != rewards + index) return false;
    const DayReward day = resolveReward(base, player, monthRewards(today)[index]);
    if (!sameReward(day, resolvedRewards[index]) || day.kind == Kind::None) return false;
    const unsigned gems = walletBalance(player, 0xa0);
    if (makeup && gems < makeupPrice) return false;
    const unsigned gemReserve = field<unsigned>(player, 0xb8);
    const unsigned before = balance(base, player, day, &reward->alias);
    const unsigned expectedBefore = makeup && day.kind == Kind::Diamonds ? before - makeupPrice : before;
    const unsigned limit = day.kind == Kind::WorldKey ? 99 : 0x7fffffffU;
    if (expectedBefore > limit - day.amount) return false;

    // The native store has a save suppression flag. Let the usual award and
    // wallet methods notify the HUD, then save both changes with the progress.
    const Object store = native<Object>(base, 0x1df738);
    if (!store || field<unsigned char>(store, 0x81)) return false;
    field<unsigned char>(store, 0x81) = 1;
    if (makeup && native<int>(base, 0x747d00, player, makeupPrice) < 0) {
        field<unsigned char>(store, 0x81) = 0;
        return false;
    }
    grant(base, player, day, &reward->alias);
    if (balance(base, player, day, &reward->alias) != expectedBefore + day.amount) {
        if (makeup) {
            native<void>(base, 0x745220, player, makeupPrice, 1U);
            field<unsigned>(player, 0xb8) = gemReserve;
        }
        field<unsigned char>(store, 0x81) = 0;
        return false;
    }
    progress = {index + 1, makeup ? saved.freeDay : today.day};
    storeProgress(player, today, progress);
    field<unsigned char>(player, signClaimed) = 1;
    field<unsigned char>(player, signTileClaimed) = 1;
    field<unsigned char>(store, 0x81) = 0;
    // The stock free path calls this profile commit after the hook returns.
    // The footer action runs the same commit to mark the sign-in save dirty.
    if (makeup) native<void>(base, 0x712484, player);
    updateMakeupButton(today);
    return true;
}

extern "C" bool asterDailySignCommit(Address base, Object player, const Reward* reward) {
    return commit(base, player, reward, false);
}

extern "C" bool asterDailySignMakeupCommit(Address base, Object player) {
    return commit(base, player, rewards + progress.count, true);
}

extern "C" void asterDailySignMakeupClick(Address base, Object dialog) {
    const Object app = gameApp(base);
    if (app && dialog == makeupDialog && field<Object>(app, 0x1248) == dialog)
        asterDailySignMakeupCommit(base, profile(base));
}

extern "C" void asterDailySignFooter(Address base, Object dialog) {
    const Object app = gameApp(base);
    const Object scroll = field<Object>(dialog, 0xa8);
    if (!app || !scroll) return;
    makeupDialog = dialog;
    const auto button = native<Object>(base, 0x14c1a7d, 0x1f8U);
    if (!button) {
        makeupButton = nullptr;
        return;
    }
    const char32_t* text = nullptr;
    makeLabel(base, &text, U"补签  10钻石");
    unsigned color[4];
    native<void>(base, 0x112f868, color, 1U);
    native<void>(base, 0x7e8db4, button, 1U, dialog + 0xa4, &text, color);
    releaseLabel(base, text);
    ImageSkin normal, pressed;
    resolveSkin(base, normal, "IMAGE_UI_GENERIC_PURPLEBUTTON", 3U);
    resolveSkin(base, pressed, "IMAGE_UI_GENERIC_PURPLEBUTTON_DOWN", 3U);
    if (normal.image) native<void>(base, 0x7e90dc, button, &normal, pressed.image ? &pressed : &normal);
    const float scale = field<float>(app, 0x698);
    const int width = int(186 * scale);
    const int height = int(53 * scale);
    const int x = (field<int>(dialog, 0x30) - width) / 2;
    const int y = field<int>(scroll, 0x2c) + field<int>(scroll, 0x34) + int(15 * scale);
    widgetCall(button, 0xac, x, y, width, height);
    widgetCall(dialog, 0x10, button);
    makeupButton = button;
    CivilDate today{};
    if (localDate(base, now(base), today)) updateMakeupButton(today);
}

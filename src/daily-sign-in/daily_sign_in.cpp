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
static constexpr unsigned noOwner = ~0U;
static constexpr char claimMarkKey[] = "IMAGE_EFFECTS_SIGNREWARD_GET_SIGNREWARD_GET_136X106";
static Reward rewards[31];
static DayReward resolvedRewards[31];
static const char* nativeAliases[unsigned(Item::Count)];
struct TileLabels { const char32_t* lines[2]; };
static TileLabels tileLabels[31];
static Object claimMark;
static bool calendarClaimed;
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

static bool prepareCalendar(Address base, Object player, Seconds when) {
    CivilDate today{}, previous{};
    if (!localDate(base, when, today) || today.year < 2020) return false;
    const bool hasPrevious = localDate(base, field<Seconds>(player, signDate), previous);
    if (hasPrevious && previous.dayKey() > today.dayKey()) return false;

    const bool sameDay = hasPrevious && previous.dayKey() == today.dayKey();
    const int days = monthLength(today);
    field<int>(player, signIndex) = today.day;
    auto& claimed = field<unsigned char>(player, signClaimed);
    if (!sameDay) {
        claimed = 0;
        field<Seconds>(player, signDate) = when;
    }
    field<unsigned char>(player, signTileClaimed) = claimed;

    const unsigned user = owner(base);
    const bool samePanelDay = calendarDay == today.dayKey() && calendarOwner == user && calendarPlayer == player;
    if (calendar.year != today.year || calendar.month != today.month || calendarPlayer != player) {
        for (auto& tile : tileLabels) {
            for (auto& line : tile.lines) releaseLabel(base, line);
        }
    }
    const DayReward* month = monthRewards(today);
    for (int index = 0; index < days; ++index) {
        if (samePanelDay && claimed && index + 1 == today.day) continue;
        const DayReward day = resolveReward(base, player, month[index]);
        if (!sameReward(day, resolvedRewards[index])) {
            for (auto& line : tileLabels[index].lines) releaseLabel(base, line);
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
    calendarClaimed = claimed;
    return true;
}

extern "C" void asterDailySignOpen(Address base) {
    Object player = profile(base);
    Address holder = field<Address>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = holder ? field<Object>(reinterpret_cast<Object>(holder), 0) : nullptr;
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

static Object rewardImage(Address base, const char* key) {
    struct ImageDescriptor { unsigned reserved[3]; const char* key; unsigned ref[2]; };
    ImageDescriptor descriptor;
    descriptor.key = key;
    descriptor.ref[0] = descriptor.ref[1] = 0;
    struct ImageSkin { unsigned drawMode; Object image; unsigned options[6]; } skin;
    skin.image = nullptr;
    native<void>(base, 0x7e8a28, &skin, &descriptor, 2U);
    native<void>(base, 0x1d9bb4, &descriptor.ref, 0U, 0U, 0U);
    return skin.image;
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
        if (const auto image = rewardImage(base, costume ? item.costumeIcon : item.icon))
            field<Object>(tile, 0xa4) = image;
    }
    if (index + 1 == calendarDay % 32)
        claimMark = rewardImage(base, claimMarkKey);
    char32_t text[24];
    auto& labels = tileLabels[index];
    if (!labels.lines[0]) {
        char32_t* name = text;
        for (const auto* c = item.name; *c; ++c) *name++ = *c;
        static constexpr char32_t suffixes[][5] = {
            U"", U"", U"", U"整株", U"碎片", U"装扮", U"装扮碎片", U"", U"",
        };
        const char32_t* suffix = suffixes[unsigned(day.kind)];
        while (*suffix) *name++ = *suffix++;
        *name = 0;
        makeLabel(base, &labels.lines[0], text);
        *writeLabel(text, U"×", day.amount) = 0;
        makeLabel(base, &labels.lines[1], text);
    }
}

struct DrawRegisters {
    Object app;
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

extern "C" void asterDailySignPaper(Address base, Object graphics, const int* frame, Object texture) {
    native<void>(base, 0x9734b0, graphics, frame, texture);
    struct Color { int red, green, blue, alpha; };
    const Color previous = field<Color>(graphics, 0x4c);
    const Color paper{201, 183, 149, 255};
    const int border = 4;
    const int x = frame[0] + border;
    const int y = frame[1] + border;
    const int width = frame[2] - border * 2;
    const int height = frame[3] - border * 2;
    if (width <= 16 || height <= 16) return;
    native<void>(base, 0x1166c30, graphics, &paper);
    // Follow the rounded corners of the original inset.
    constexpr int corners[] = {6, 4, 3, 2, 1, 1};
    constexpr int radius = sizeof(corners) / sizeof(corners[0]);
    native<void>(base, 0x1167010, graphics, x, y + radius, width, height - radius * 2);
    for (int row = 0; row < radius; ++row) {
        const int inset = corners[row];
        native<void>(base, 0x1167010, graphics, x + inset, y + row, width - inset * 2, 1);
        native<void>(base, 0x1167010, graphics, x + inset, y + height - row - 1, width - inset * 2, 1);
    }
    native<void>(base, 0x1166c30, graphics, &previous);
}

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

extern "C" void asterDailySignDraw(Address base, const DrawRegisters& args, const DrawStack& stack) {
    auto draw = [&](float y, const char32_t* const* text) {
        native<void>(base, 0x13af2d0, args.app, args.graphics, args.x, y, stack.width,
                     text, stack.alignment, stack.style, stack.flags);
    };
    const int index = field<int>(args.tile, 0xd8);
    if (index < 0 || index >= calendar.end - calendar.begin) {
        draw(args.y, stack.text);
        return;
    }
    const auto& labels = tileLabels[index];
    const int width = field<int>(args.tile, 0x30);
    const int height = field<int>(args.tile, 0x34);
    drawRewardImage(base, args.graphics, field<Object>(args.tile, 0xa4),
                    width / 2, height * 45 / 100, width * 68 / 100, height * 44 / 100);
    draw(args.y, &labels.lines[0]);
    draw(height * 0.65f, &labels.lines[1]);
    if (calendarClaimed && index + 1 == calendarDay % 32) {
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

extern "C" bool asterDailySignCommit(Address base, Object player, const Reward* reward) {
    CivilDate today{}, claimedDate{};
    if (!player || player != calendarPlayer || calendarOwner == noOwner ||
        owner(base) != calendarOwner || profile(base) != player ||
        !localDate(base, now(base), today) || today.dayKey() != calendarDay ||
        !localDate(base, field<Seconds>(player, signDate), claimedDate) || claimedDate.dayKey() != calendarDay ||
        field<unsigned char>(player, signClaimed)) return false;
    const int index = field<int>(player, signIndex);
    if (index != today.day || index > calendar.end - calendar.begin || reward != rewards + index - 1)
        return false;
    const DayReward day = resolveReward(base, player, monthRewards(today)[index - 1]);
    if (!sameReward(day, resolvedRewards[index - 1]) || day.kind == Kind::None) return false;
    const unsigned before = balance(base, player, day, &reward->alias);
    const unsigned limit = day.kind == Kind::WorldKey ? 99 : 0x7fffffffU;
    if (before > limit - day.amount) return false;

    // These inventory changes and the claim flags belong to the same native profile.
    field<unsigned char>(player, signClaimed) = 1;
    field<unsigned char>(player, signTileClaimed) = 1;
    grant(base, player, day, &reward->alias);
    if (balance(base, player, day, &reward->alias) != before + day.amount) {
        field<unsigned char>(player, signClaimed) = 0;
        field<unsigned char>(player, signTileClaimed) = 0;
        return false;
    }
    calendarClaimed = true;
    return true;
}

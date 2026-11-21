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

#include "toolbox_rewards.inc"

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
static Reward rewards[31];
static const char* nativeAliases[PlantCount];
struct TileLabels { const char32_t* lines[4]; };
static TileLabels tileLabels[31];
static const char32_t* todayLabels[2];
static bool calendarClaimed;
static Calendar calendar;
static unsigned calendarOwner = noOwner;
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
    constexpr int months = sizeof(toolboxRewards) / sizeof(toolboxRewards[0]);
    const int index = date.monthKey() - firstRewardMonth;
    return toolboxRewards[index < 0 ? 0 : index >= months ? months - 1 : index];
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

    if (calendar.year != today.year || calendar.month != today.month) {
        for (auto& tile : tileLabels) {
            for (auto& line : tile.lines) releaseLabel(base, line);
        }
    }
    if (calendarDay != today.dayKey()) {
        for (auto& label : todayLabels) releaseLabel(base, label);
    }
    const DayReward* month = monthRewards(today);
    for (int index = 0; index < days; ++index) {
        const DayReward& day = month[index];
        auto& alias = nativeAliases[day.plant];
        if (!alias) {
            char allocator = 0;
            native<void>(base, 0x14ed0e1, &alias, plants[day.plant].alias, &allocator);
        }
        // The original calendar's generic plant-fragment view uses type 5.
        rewards[index] = {alias, 5, day.shards};
    }
    calendar.unusedVtable = 0;
    calendar.version = 1;
    calendar.year = today.year;
    calendar.month = today.month;
    calendar.startDay = 1;
    calendar.begin = rewards;
    calendar.end = rewards + days;
    calendar.capacity = calendar.end;
    calendarOwner = owner(base);
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

extern "C" void asterDailySignTile(Address base, Object tile, const Reward* reward) {
    // The fragment artwork path assumes a live shop product. Use the stock
    // generic tile and give it the complete bundle text without a shop lookup.
    constexpr unsigned genericTile = 9;
    const Reward display{reward->alias, genericTile, 0};
    native<void>(base, 0xf6347c, tile, &display, 1);
    const int index = reward - rewards;
    const DayReward& day = monthRewards({calendar.year, calendar.month, 1})[index];
    char32_t text[24];
    char32_t* end = writeLabel(text, U"", index + 1);
    *end++ = U'日';
    native<void>(base, 0x14ea6fd, tile + 0xc8, text, unsigned(end - text));
    if (index + 1 == calendarDay % 32 && !todayLabels[0]) {
        end[0] = U' '; end[1] = U'可'; end[2] = U'领'; end[3] = 0;
        makeLabel(base, &todayLabels[0], text);
        end[1] = U'已';
        makeLabel(base, &todayLabels[1], text);
    }
    auto& labels = tileLabels[index];
    if (!labels.lines[0]) {
        makeLabel(base, &labels.lines[0], plants[day.plant].name);
        *writeLabel(text, U"碎片 ×", day.shards) = 0;
        makeLabel(base, &labels.lines[1], text);
        *writeLabel(text, U"金币 ", day.coins) = 0;
        makeLabel(base, &labels.lines[2], text);
        *writeLabel(text, U"钻石 ", day.diamonds) = 0;
        makeLabel(base, &labels.lines[3], text);
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

extern "C" void asterDailySignDraw(Address base, const DrawRegisters& args, const DrawStack& stack) {
    auto draw = [&](float y, const char32_t* const* text) {
        native<void>(base, 0x13af2d0, args.app, args.graphics, args.x, y, stack.width,
                     text, stack.alignment, stack.style, stack.flags);
    };
    const int index = field<int>(args.tile, 0xd8);
    const bool current = index + 1 == calendarDay % 32;
    const auto* today = &todayLabels[calendarClaimed];
    draw(args.y, current && *today ? today : stack.text);
    if (index < 0 || index >= calendar.end - calendar.begin) return;
    const float spacing = float(field<int>(args.tile, 0x34)) * 0.15f;
    float y = args.y;
    for (const auto& line : tileLabels[index].lines) {
        if (!line) break;
        y += spacing;
        draw(y, &line);
    }
}

static bool walletFits(Object player, unsigned offset, unsigned amount) {
    const unsigned salt = field<unsigned>(player, offset + 4);
    const unsigned encoded = field<unsigned>(player, offset);
    const unsigned shift = salt & 31;
    const unsigned balance = ((encoded >> shift) | (encoded << ((32 - shift) & 31))) ^ salt;
    return balance <= 0x7fffffffU - amount;
}

static bool shardsFit(Object player, unsigned plantId, unsigned amount) {
    struct ShardBalance { unsigned id, count; };
    const auto* entry = field<const ShardBalance*>(player, 0x208);
    const auto* end = field<const ShardBalance*>(player, 0x20c);
    for (; entry != end; ++entry) {
        if (entry->id == plantId) return entry->count <= 0x7fffffffU - amount;
    }
    return true;
}

extern "C" bool asterDailySignCommit(Address base, Object player, const Reward* reward) {
    CivilDate today{};
    if (calendarOwner == noOwner || owner(base) != calendarOwner || profile(base) != player ||
        !localDate(base, now(base), today) || today.dayKey() != calendarDay ||
        field<unsigned char>(player, signClaimed)) return false;
    const int index = field<int>(player, signIndex);
    if (index != today.day || index > calendar.end - calendar.begin || reward != rewards + index - 1)
        return false;
    const DayReward& day = monthRewards(today)[index - 1];
    if (!walletFits(player, 0x98, day.coins) || !walletFits(player, 0xa0, day.diamonds) ||
        !shardsFit(player, plants[day.plant].nativeId, day.shards)) return false;

    // These inventory changes and the claim flags belong to the same native profile.
    field<unsigned char>(player, signClaimed) = 1;
    field<unsigned char>(player, signTileClaimed) = 1;
    calendarClaimed = true;
    native<void>(base, 0x729ebc, player, &reward->alias, unsigned(day.shards));
    native<void>(base, 0x746164, player, unsigned(day.coins));
    native<void>(base, 0x745220, player, unsigned(day.diamonds), 0);
    return true;
}

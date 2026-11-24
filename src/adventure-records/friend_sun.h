#pragma once

namespace {
constexpr Word giftSun = 25;
constexpr Word dailyGiftLimit = 5;
constexpr Word maxGiftFriends = 40;
constexpr Word friendSunRequest = 5;
constexpr Word friendSunReply = 5;
constexpr Word giftMagic = 0x31555346;
constexpr Word sunPageSize = 6;
constexpr Word sunShopOffset = 0x12cc;
constexpr Word sunShopProducts = 0xc8;
enum SunArt : Word {
    SunRow, SunRowDown, SunClaimSkin, SunClaimDown,
    SunCard, SunPortraitFrame, SunCheckOff, SunCheckOn, SunAmountIcon,
    SunAvatar, SunCommunityAvatar = SunAvatar + friendAvatarCount,
    SunArtCount = SunCommunityAvatar + communityAvatarCount
};
enum SunAction : Word { SunGifts = 1, SunBuy, SunClaim, SunPrevious, SunNext, SunPick = 16 };

struct SunButtonListener {
    using Method = void (*)(SunButtonListener*, Word);
    Method* methods;
};

struct GiftFriend {
    Word id, avatar;
    char32_t name[40];
};

struct GiftLedger {
    Word magic, day, count;
    Word claimed[dailyGiftLimit];
};

struct FriendSunShop {
    Object app, board, shop, stockTab, products, tabs[2];
    float startedAt;
    SocialMessage message;
    Word action, expires, lastPoll, count;
    Word visibleCount, visible[sunPageSize], page, remaining, available;
    Word pageControlCount;
    Object pageControls[6 * sunPageSize + 5];
    bool selected[maxGiftFriends];
    bool ready, giftsActive, heldCardArt;
    GiftFriend friends[maxGiftFriends];
    ButtonSkin art[SunArtCount];
    MenuRect body;
};

static FriendSunShop friendSun;

static void giftLedgerPath(char* out, Word player, bool temporary) {
    for (char ch : "/data/data/com.pvz2unline.aster/files/userdata/friend-sun-") {
        if (ch) *out++ = ch;
    }
    constexpr char hex[] = "0123456789abcdef";
    for (int bit = 28; bit >= 0; bit -= 4) *out++ = hex[(player >> bit) & 15];
    const char* suffix = temporary ? ".bin.tmp" : ".bin";
    while ((*out++ = *suffix++)) {}
}

static Word socialCalendarDay(Word base) {
    Word time[2];
    if (native<int>(base, 0x147974, time, nullptr) != 0 || time[0] < 86400 || time[0] > 0x7fffffff) {
        return 0;
    }
    Object local = native<Object>(base, 0x147854, time);
    const int offset = local ? field<int>(local, 0x24) : 0;
    return offset >= -86400 && offset <= 86400 ? (time[0] + offset) / 86400U : 0U;
}

static bool giftClaimed(const GiftLedger& ledger, Word id) {
    for (Word i = 0; i < ledger.count; ++i) {
        if (ledger.claimed[i] == id) return true;
    }
    return false;
}

static bool loadGifts(Word base, Word player, GiftLedger& ledger) {
    const Word day = socialCalendarDay(base);
    if (!day) return false;
    char path[96];
    giftLedgerPath(path, player, false);
    int fd = native<int>(base, 0x148448, path, 0, 0);
    if (fd >= 0) {
        char extra;
        const bool read = readExact(base, fd, &ledger, sizeof(ledger)) &&
            native<int>(base, 0x148460, fd, &extra, 1) == 0;
        native<int>(base, 0x147b90, fd);
        if (!read || ledger.magic != giftMagic || !ledger.day ||
            ledger.day > day || ledger.count > dailyGiftLimit) return false;
        if (ledger.day == day) return true;
    }
    ledger.magic = giftMagic;
    ledger.day = day;
    ledger.count = 0;
    for (volatile Word& id : ledger.claimed) id = 0;
    return true;
}

static void ignoreSunButton(SunButtonListener*, Word) {}

static void queueSunAction(SunButtonListener*, Word action) {
    if (friendSun.shop && !friendSun.action) friendSun.action = action;
}

static Object createGameButton(Word base, const char32_t* label, Word action, const MenuRect& box,
                               SunButtonListener* listener, const ButtonSkin* normal,
                               const ButtonSkin* pressed, const MenuColor* tint, bool alignLeft) {
    const char32_t* content = nullptr;
    makeText(base, content, label);
    MenuColor tintDefault;
    native<void>(base, 0x112f868, &tintDefault, 1U);
    Object button = native<Object>(base, 0x14c1a7d, 0x1f8U);
    if (button) {
        native<void>(base, 0x7e8db4, button, action, listener, &content, tint ? tint : &tintDefault);
        widgetCall(button, 0xac, box.x, box.y, box.width, box.height);
        field<MenuRect>(button, 0x1c4) = {0, 0, -1, -1};
        if (alignLeft) field<int>(button, 0x1c0) = -1;
        if (normal && normal->image) {
            native<void>(base, 0x7e90dc, button, normal, pressed && pressed->image ? pressed : normal);
        }
        if (!action) field<unsigned char>(button, 0x38) = 0;
    }
    freeText(base, content);
    return button;
}

static Object addSunControl(Word base, const char32_t* label, Word action, const MenuRect& box,
                            const ButtonSkin* normal = nullptr, const ButtonSkin* pressed = nullptr,
                            const MenuColor* tint = nullptr, bool alignLeft = false) {
    static SunButtonListener listener;
    static SunButtonListener::Method methods[7];
    methods[0] = methods[1] = methods[3] = methods[4] = methods[5] = methods[6] = ignoreSunButton;
    methods[2] = queueSunAction;
    listener.methods = methods;
    Object button = createGameButton(base, label, action, box, &listener, normal, pressed, tint, alignLeft);
    if (button) widgetCall(friendSun.shop, 0x10, button);
    return button;
}
static void removeSunControl(Object button) {
    if (!button) return;
    widgetCall(friendSun.shop, 0x14, button);
    widgetCall(friendSun.app, 0xa8, button);
}

static void clearSunPage() {
    while (friendSun.pageControlCount) removeSunControl(friendSun.pageControls[--friendSun.pageControlCount]);
}

static MenuRect fitSunPage(MenuRect box) {
    const auto& area = friendSun.body;
    return {area.x + box.x * area.width / 600, area.y + box.y * area.height / 360,
            box.width * area.width / 600, box.height * area.height / 360};
}

static void addSunPageControl(Word base, const char32_t* label, Word action, MenuRect box,
                              SunArt normal = SunArtCount, SunArt pressed = SunArtCount,
                              const MenuColor* tint = nullptr, bool alignLeft = false) {
    const auto* up = normal < SunArtCount ? &friendSun.art[normal] : nullptr;
    const auto* down = pressed < SunArtCount ? &friendSun.art[pressed] : nullptr;
    if (auto* button = addSunControl(base, label, action, fitSunPage(box), up, down, tint, alignLeft)) {
        friendSun.pageControls[friendSun.pageControlCount++] = button;
    }
}

static void loadSunArt(Word base) {
    if (!field<Object>(reinterpret_cast<Object>(base), 0x183607c)) return;
#ifdef ASTER_SOCIAL_ART
    changeMenuGroup(base, friendSun.app, 2, true);
    friendSun.heldCardArt = true;
#endif
    static constexpr char keys[][52] = {
        "IMAGE_UI_GENERIC_BROWNBUTTON", "IMAGE_UI_GENERIC_BROWNBUTTON_DOWN",
        "IMAGE_UI_GENERIC_PURPLEBUTTON", "IMAGE_UI_GENERIC_PURPLEBUTTON_DOWN",
        "IMAGE_ASTER_SOCIAL_FRIEND_ROW", "IMAGE_ASTER_SOCIAL_FRIEND_AVATAR",
        "IMAGE_UI_GENERIC_RADIO_N", "IMAGE_UI_GENERIC_RADIO_S", "IMAGE_UI_HUD_INGAME_SUN",
    };
    for (Word i = 0; i < SunAvatar; ++i) resolveMenuSkin(base, friendSun.art[i], keys[i], i < SunCard ? 3 : 2);
    for (Word i = 0; i < friendAvatarCount; ++i)
        resolveMenuSkin(base, friendSun.art[SunAvatar + i], friendAvatarKeys[i], 2);
    for (Word i = 0; i < communityAvatarCount; ++i)
        resolveMenuSkin(base, friendSun.art[SunCommunityAvatar + i], communityAvatarKeys[i], 2);
}

static Word selectedGiftCount() {
    Word count = 0;
    for (Word i = 0; i < friendSun.count; ++i) count += friendSun.selected[i];
    return count;
}

static void showSunGiftRows(Word base, const char32_t* notice = nullptr) {
    clearSunPage();
    friendSun.visibleCount = friendSun.available = friendSun.remaining = 0;
    GiftLedger ledger;
    constexpr MenuColor giftInk{65, 46, 23, 255};
    const bool valid = friendSun.ready && loadGifts(base, friendSun.message.owner, ledger);
    if (valid) {
        friendSun.remaining = dailyGiftLimit - ledger.count;
        for (Word i = 0; i < friendSun.count; ++i) {
            if (giftClaimed(ledger, friendSun.friends[i].id)) {
                friendSun.selected[i] = false;
                continue;
            }
            const Word offset = friendSun.available++;
            if (offset / sunPageSize != friendSun.page) continue;
            const Word slot = friendSun.visibleCount++;
            friendSun.visible[slot] = i;
            const int x = 10 + 292 * int(slot % 2), y = 8 + 85 * int(slot / 2);
            const Word action = friendSun.remaining ? SunPick + slot : 0;
            char32_t label[22];
            auto* end = append(label, friendSun.friends[i].name, 8);
            if (friendSun.friends[i].name[8]) append(end, U"…");
            const bool hasCard = friendSun.art[SunCard].image;
            addSunPageControl(base, U"", action, {x, y, 280, 77}, hasCard ? SunCard : SunRow);
            addSunPageControl(base, U"", action, {x + 7, y + 26, 23, 23},
                              friendSun.selected[i] ? SunCheckOn : SunCheckOff);
            const auto& player = friendSun.friends[i];
            const auto portrait = player.avatar < communityAvatarCount && friendSun.art[SunCommunityAvatar + player.avatar].image
                ? SunArt(SunCommunityAvatar + player.avatar)
                : SunArt(SunAvatar + friendAvatarIndex(friendSun.message.owner, player.id));
            addSunPageControl(base, U"", action, {x + 40, y + 13, 50, 50},
                              friendSun.art[portrait].image ? portrait : SunPortraitFrame);
            addSunPageControl(base, label, action, {x + 103, y + 2, 169, 36},
                              SunArtCount, SunArtCount, nullptr, true);
            addSunPageControl(base, U"送来的阳光 +25", action, {x + 103, y + 38, 169, 34},
                              SunArtCount, SunArtCount, hasCard ? &giftInk : nullptr, true);
        }
    }
    const char32_t* status = notice;
    char32_t remaining[48];
    if (!status) {
        if (!friendSun.ready) status = U"正在读取离线好友…";
        else if (!valid) status = U"暂时无法读取今日领取记录";
        else if (!friendSun.remaining) status = U"今日领取次数已用完";
        else if (!friendSun.visibleCount) status = U"暂无可领取的友情阳光";
        else {
            auto* end = append(remaining, U"今天还能领取 ");
            append(number(end, friendSun.remaining), U" 位好友的阳光");
            status = remaining;
        }
    }
    const int statusY = friendSun.visibleCount ? 260 : 135;
    addSunPageControl(base, status, 0, {65, statusY, 425, 44});
    if (friendSun.visibleCount) addSunPageControl(base, U"", 0, {453, statusY + 7, 30, 30}, SunAmountIcon);
    if (friendSun.page) addSunPageControl(base, U"上一页", SunPrevious, {20, 301, 110, 43}, SunRow, SunRowDown);
    if ((friendSun.page + 1) * sunPageSize < friendSun.available) {
        addSunPageControl(base, U"下一页", SunNext, {470, 301, 110, 43}, SunRow, SunRowDown);
    }
    const bool canClaim = friendSun.remaining && selectedGiftCount();
    constexpr MenuColor disabled{180, 165, 190, 255};
    addSunPageControl(base, U"领 取", canClaim ? SunClaim : 0, {228, 327, 144, 52},
                      SunClaimSkin, SunClaimDown, canClaim ? nullptr : &disabled);
}

static void showSunPage(Word base, bool gifts) {
    friendSun.giftsActive = gifts;
    for (Word i = 0; i < 2; ++i) {
        const auto* normal = &field<ButtonSkin>(friendSun.stockTab, 0x15c);
        const auto* selected = &field<ButtonSkin>(friendSun.stockTab, 0x19c);
        native<void>(base, 0x7e9028, friendSun.tabs[i], normal, selected, (i == 0) == gifts);
    }
    widgetCall(friendSun.products, 0x8c, !gifts);
    if (gifts) showSunGiftRows(base);
    else clearSunPage();
}

static bool sameSunBoard(Word base) {
    Object board = gameBoard(base);
    return board && board == friendSun.board && gameApp(base) == friendSun.app &&
        owner(ownerStore(base)) == friendSun.message.owner && field<Word>(board, 0xc0) == 5 &&
        !field<Word>(board, 0x7f4) && field<float>(board, 0xcc) == friendSun.startedAt;
}

static void detachFriendSun(Word base) {
    clearSunPage();
    for (auto& tab : friendSun.tabs) {
        removeSunControl(tab);
        tab = nullptr;
    }
#ifdef ASTER_SOCIAL_ART
    if (friendSun.heldCardArt) changeMenuGroup(base, friendSun.app, 2, false);
#endif
    friendSun.heldCardArt = false;
    friendSun.shop = friendSun.board = nullptr;
}

static void claimFriendSun(Word base) {
    GiftLedger ledger;
    const Word player = friendSun.message.owner;
    if (!loadGifts(base, player, ledger)) {
        showSunGiftRows(base, U"暂时无法领取");
        return;
    }
    const Word previous = ledger.count;
    for (Word i = 0; i < friendSun.count && ledger.count < dailyGiftLimit; ++i) {
        const Word id = friendSun.friends[i].id;
        if (friendSun.selected[i] && !giftClaimed(ledger, id)) {
            ledger.claimed[ledger.count++] = id;
        }
    }
    const Word amount = (ledger.count - previous) * giftSun;
    if (!amount) {
        showSunGiftRows(base);
        return;
    }
    Object board = friendSun.board;
    const Word key = field<Word>(board, 0x130);
    const Word shift = key & 31;
    const Word encoded = field<Word>(board, 0x12c);
    const Word sun = ((encoded >> shift) | (encoded << ((32 - shift) & 31))) ^ key;
    const Word cap = native<Word>(base, 0x2077e4, board);
    if (sun >= cap || amount > cap - sun) {
        showSunGiftRows(base, U"阳光即将达到上限");
        return;
    }
    char path[96], temp[96];
    giftLedgerPath(path, player, false);
    giftLedgerPath(temp, player, true);
    if (!writeBytes(base, &ledger, sizeof(ledger), path, temp)) {
        showSunGiftRows(base, U"领取失败，请重试");
        return;
    }
    native<void>(base, 0x221b1c, board, amount);
    if (sameRun(base, board)) current.friendSunUsed = true;
    native<void>(base, 0x418d18, friendSun.app);
}

static bool receiveSunFriends(Word base) {
    int fd = native<int>(base, 0x148448, replyFile, 0, 0);
    if (fd < 0) return false;
    SocialMessage response;
    Word count = 0;
    bool valid = readExact(base, fd, &response, sizeof(response)) &&
        response.token == friendSun.message.token && response.owner == friendSun.message.owner &&
        response.day == friendSun.message.day && response.kind == friendSunReply &&
        readExact(base, fd, &count, sizeof(count)) && count <= maxGiftFriends &&
        readExact(base, fd, friendSun.friends, count * sizeof(GiftFriend));
    for (Word i = 0; valid && i < count; ++i) {
        const auto& entry = friendSun.friends[i];
        valid = entry.id && validFriendAvatar(entry.avatar) && entry.name[0] && !entry.name[39];
    }
    char extra;
    valid = valid && native<int>(base, 0x148460, fd, &extra, 1) == 0;
    native<int>(base, 0x147b90, fd);
    native<int>(base, 0x148424, replyFile);
    if (valid) {
        friendSun.count = count;
    }
    return valid;
}

static void updateFriendSun(Word base) {
    if (!friendSun.shop) return;
    Object app = gameApp(base);
    if (!app || app != friendSun.app || field<Object>(app, sunShopOffset) != friendSun.shop) {
        friendSun.shop = nullptr;
        friendSun.tabs[0] = friendSun.tabs[1] = nullptr;
        friendSun.pageControlCount = 0;
        return;
    }
    if (!sameSunBoard(base)) {
        native<void>(base, 0x418d18, app);
        return;
    }
    const Word action = friendSun.action;
    friendSun.action = 0;
    if (action == SunGifts || action == SunBuy) {
        if (friendSun.giftsActive != (action == SunGifts)) showSunPage(base, action == SunGifts);
        return;
    }
    if (action == SunClaim && friendSun.giftsActive) {
        claimFriendSun(base);
        return;
    }
    if (action == SunPrevious || action == SunNext) {
        friendSun.page = action == SunPrevious ? friendSun.page - 1 : friendSun.page + 1;
        showSunGiftRows(base);
        return;
    }
    if (action >= SunPick && action < SunPick + friendSun.visibleCount) {
        auto& selected = friendSun.selected[friendSun.visible[action - SunPick]];
        if (!selected && selectedGiftCount() >= friendSun.remaining) {
            showSunGiftRows(base, U"已选满今日可领取的份数");
        } else {
            selected = !selected;
            showSunGiftRows(base);
        }
        return;
    }
    const Word clock = wallTime(base);
    if (!friendSun.ready && clock - friendSun.lastPoll >= 10) {
        friendSun.lastPoll = clock;
        if (receiveSunFriends(base) || static_cast<int>(clock - friendSun.expires) >= 0) {
            friendSun.ready = true;
            if (friendSun.giftsActive) showSunGiftRows(base);
        }
    }
}
}

extern "C" void asterFriendSunBeforeClose(Word base, Object app) {
    if (friendSun.shop && app == friendSun.app && field<Object>(app, sunShopOffset) == friendSun.shop) {
        detachFriendSun(base);
    }
}

extern "C" bool asterFriendSunShopScrollbar(Word base, Object products) {
    if (friendSun.shop && friendSun.giftsActive && products == friendSun.products) return false;
    return native<bool>(base, 0x1370bc0, products);
}

extern "C" void asterFriendSunOpen(Word base, Object app, Word mode) {
    Object board = gameBoard(base);
    const bool eligible = mode == 1 && app == gameApp(base) && board && playing(board) &&
        socialContentEnabled(base) && social.phase == SocialPhase::Idle &&
        AdventureRecords::formationSupported(field<const char*>(board, 0xc4));
    const Word player = eligible ? owner(ownerStore(base)) : ~0U;
    native<void>(base, 0x418e44, app, mode);
    if (player == ~0U) return;

    Object shop = field<Object>(app, sunShopOffset);
    if (!shop || gameBoard(base) != board || field<Word>(shop, 0xc4) != 1) return;
    Object products = field<Object>(shop, sunShopProducts);
    Object head = field<Object>(shop, 4);
    if (!products || !head || head == shop + 4) return;
    Object stockTab = field<Object>(head, 8);
    if (!stockTab || field<Word>(stockTab, 0) != base + 0x17b8d20 ||
        field<Word>(stockTab, 0xa0) != 0) return;

    friendSun.app = app;
    friendSun.board = board;
    friendSun.shop = shop;
    friendSun.stockTab = stockTab;
    friendSun.products = products;
    friendSun.startedAt = field<float>(board, 0xcc);
    friendSun.action = friendSun.count = friendSun.page = 0;
    for (volatile bool& selected : friendSun.selected) selected = false;
    friendSun.ready = false;
    const auto& scrollBounds = field<MenuRect>(products, 0x28);
    const auto& tabBounds = field<MenuRect>(stockTab, 0x28);
    friendSun.body = {scrollBounds.x, scrollBounds.y, scrollBounds.width, scrollBounds.height};
    constexpr char32_t texts[][5] = {U"友情阳光", U"购买阳光"};
    for (Word i = 0; i < 2; ++i) {
        const MenuRect rect{scrollBounds.x + (tabBounds.width + tabBounds.width / 14) * int(i), tabBounds.y,
                            tabBounds.width, tabBounds.height};
        friendSun.tabs[i] = addSunControl(base, texts[i], SunGifts + i, rect);
        if (!friendSun.tabs[i]) {
            detachFriendSun(base);
            return;
        }
        field<MenuRect>(friendSun.tabs[i], 0x1c4) = field<MenuRect>(stockTab, 0x1c4);
    }
    widgetCall(stockTab, 0x8c, false);
    loadSunArt(base);
    const Word clock = wallTime(base);
    friendSun.expires = clock + 200U;
    friendSun.lastPoll = clock;
    friendSun.message = {clock + ++sequence, player,
        AdventureRecords::levelId(field<const char*>(board, 0xc4)), friendSunRequest};
    native<int>(base, 0x148424, replyFile);
    writeBytes(base, &friendSun.message, sizeof(friendSun.message), dialogFile, dialogTemp);
    showSunPage(base, true);
}

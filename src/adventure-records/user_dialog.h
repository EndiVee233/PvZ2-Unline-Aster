#pragma once

namespace {
constexpr int userWidth = 620;
constexpr int userHeight = 324;
constexpr int cnUserWidth = 680;
constexpr int cnUserHeight = 448;
constexpr Word userSlots = 3;
constexpr Word userPageSize = 6;
constexpr Word userPlantCount = sizeof(plantPackets) / sizeof(plantPackets[0]);
constexpr MenuColor userWhite{255, 249, 227, 255};
constexpr MenuColor userInk{26, 63, 58, 255};
constexpr MenuColor userPaper{233, 242, 219, 255};

struct UserPreferences {
    Word version, owner, avatar;
    char loans[userSlots][32];
};
static_assert(sizeof(UserPreferences) == 108);

enum class UserPage { Home, Avatars, Loans, Plants, Friends, AddFriend };
enum UserAction : Word { UserClose = 1, UserBack, UserAvatars, UserLoans, UserCode,
                         UserPrev, UserNext, UserClear, UserConfirmAvatar, UserExport,
                         UserFriendList, UserFriendAdd,
                         UserSlot = 16, UserAvatar = 32, UserPlant = 64 };
constexpr Word friendRowAction = 0x100;
constexpr Word friendListRequest = 9, friendCatalogRequest = 10, friendAddRequest = 11, friendRemoveRequest = 12;
constexpr Word maxRoster = 6;
enum CnUserArt : Word {
    CnNone, CnFrame, CnDave, CnHint, CnGift, CnName, CnPaper, CnPreview, CnClose, CnCloseDown,
    CnCloseTab, CnCloseTabDown, CnAction, CnActionDown, CnArtCount
};
struct UserDialog {
    Object widget, friendWidget, dialog, app, artApp;
    bool requested, friendRequested, pressed, friendPressed, heldPackets;
    UserPreferences data;
    UserPage page;
    Word action, slot, plantPage, availableCount, avatarPreview;
    struct Choice { Word index, tier; } available[userPlantCount];
    ButtonSkin portraits[friendAvatarCount];
    ButtonSkin packets[4];
    ButtonSkin mapSkin, mapPressed, friendSkin, friendDown;
    const char32_t* friendCaption;
    const char32_t* signCaption;
    ButtonSkin cnArt[CnArtCount];
    struct Label { const char32_t* text; MenuRect rect; MenuColor color; } labels[20];
    struct Control { Object button; MenuRect rect; CnUserArt normal, pressed; } controls[12];
    struct Image { Object art; MenuRect rect; } images[24];
    struct LoanCard { BorrowRowView plant; MenuRect rect; Word tier; } cards[userPageSize];
    Word labelCount, controlCount, imageCount, cardCount;
};
static UserDialog user;

struct FriendBook {
    SocialMessage request;
    Word nextPoll, expires, status, rosterCount, total, page, count;
    bool pending;
    struct Entry { Word id, avatar; char32_t name[40]; } entries[maxRoster];
    enum Art { Tab, Selected, Topper, Row, Avatar, Close, Leaves, ArtCount };
    ButtonSkin art[ArtCount];
    const char32_t* captions[2];
};
static FriendBook friendBook;
constexpr int friendTabWidth = 140;
constexpr int friendTabBodyHeight = 73;
constexpr int friendTabX(Word index) { return 237 + 190 * int(index) - friendTabWidth / 2; }

static bool friendsPage() {
    return user.page == UserPage::Friends || user.page == UserPage::AddFriend;
}

static bool friendBookUsesBorrowFrame(Object dialog) {
    return dialog && dialog == user.dialog && friendsPage();
}

static bool userHasCnArt() {
    return user.cnArt[CnFrame].image != nullptr;
}

static bool userDrawsOwnFrame(Object dialog) {
    return dialog && dialog == user.dialog && userHasCnArt() && !friendsPage();
}

static bool cnUserUsesFullLayout() {
    return userHasCnArt() && (user.page == UserPage::Home || user.page == UserPage::Avatars);
}

static void userPreferencesPath(char* out, Word profile, bool temporary) {
    for (char c : "/data/data/com.pvz2unline.aster/files/userdata/user-menu-") if (c) *out++ = c;
    for (int shift = 28; shift >= 0; shift -= 4)
        *out++ = "0123456789abcdef"[(profile >> shift) & 15];
    for (const char* suffix = temporary ? ".tmp" : ".bin"; (*out++ = *suffix++);) {}
}

static void readUserPreferences(Word base, Word profile) {
    char path[104], extra;
    userPreferencesPath(path, profile, false);
    const int fd = native<int>(base, 0x148448, path, 0, 0);
    if (fd >= 0) {
        bool valid = readExact(base, fd, &user.data, sizeof(user.data)) &&
            native<int>(base, 0x148460, fd, &extra, 1U) == 0 &&
            user.data.version == 1 && user.data.owner == profile && user.data.avatar < friendAvatarCount;
        native<int>(base, 0x147b90, fd);
        for (const auto& slot : user.data.loans)
            valid = valid && (!slot[0] || AdventureRecords::validPlantType(slot));
        if (valid) return;
    }
    user.data.version = 1;
    user.data.owner = profile;
    user.data.avatar = 0;
    auto* loans = reinterpret_cast<volatile char*>(user.data.loans);
    for (Word i = 0; i < sizeof(user.data.loans); ++i) loans[i] = 0;
}

static bool saveUserPreferences(Word base) {
    const Word profile = user.data.owner;
    if (profile == ~0U || profile != owner(ownerStore(base))) return false;
    char path[104], temp[104];
    userPreferencesPath(path, profile, false);
    userPreferencesPath(temp, profile, true);
    return writeBytes(base, &user.data, sizeof(user.data), path, temp);
}

static bool sameUserPlant(const char* a, const char* b) {
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

static void findUserPlants(Word base, Object profile) {
    user.availableCount = 0;
    char allocator = 0;
    for (Word i = 0; i < userPlantCount; ++i) {
        const char* alias = nullptr;
        native<void>(base, 0x14ed0e1, &alias, plantPackets[i].alias, &allocator);
        const int tier = native<int>(base, 0x717300, profile, &alias, 0U);
        releaseString(base, alias);
        if (tier >= 0 && tier <= 4) user.available[user.availableCount++] = {i, tier ? Word(tier) : 1U};
    }
}

static bool exportUser(Word base, Object profile) {
    struct Export {
        Word version, owner, avatar;
        char32_t name[40];
        AdventureRecords::Card loans[userSlots];
    };
    static_assert(sizeof(Export) == 280);
    Export data;
    auto* bytes = reinterpret_cast<volatile unsigned char*>(&data);
    for (Word i = 0; i < sizeof(data); ++i) bytes[i] = 0;
    data.version = 1;
    data.owner = user.data.owner;
    data.avatar = user.data.avatar;
    const auto name = field<const char32_t*>(profile, 0x58);
    append(data.name, name && *name ? name : U"玩家", 39);
    findUserPlants(base, profile);
    for (Word slot = 0; slot < userSlots; ++slot) {
        for (Word i = 0; i < user.availableCount; ++i) {
            const auto& plant = user.available[i];
            const auto& type = plantPackets[plant.index].alias;
            if (!sameUserPlant(user.data.loans[slot], type)) continue;
            for (Word j = 0; type[j]; ++j) data.loans[slot].type[j] = type[j];
            data.loans[slot].level = plant.tier;
            break;
        }
    }
    return writeBytes(base, &data, sizeof(data), "/data/data/com.pvz2unline.aster/cache/aster-social-export",
                      "/data/data/com.pvz2unline.aster/cache/aster-social-export.tmp");
}

static bool userMounted(Object app) {
    return app && user.dialog && user.app == app &&
        field<Object>(field<Object>(app, 0x2c0), 0x88) == user.dialog;
}

static void resetUserPage(Word base) {
    for (Word i = 0; i < user.labelCount; ++i) freeText(base, user.labels[i].text);
    user.labelCount = user.controlCount = user.imageCount = user.cardCount = 0;
}

static void closeUserDialog(Word base) {
    Object app = gameApp(base);
    if (userMounted(app)) detachGameDialog(base, app, user.dialog);
    if (user.heldPackets && app && app == user.app)
        changeMenuGroup(base, app, packetResourceGroup, false);
    user.heldPackets = false;
    resetUserPage(base);
    user.dialog = user.app = nullptr;
    user.action = 0;
    friendBook.pending = false;
}

static MenuRect userLayout(Object dialog, MenuRect box) {
    const bool full = cnUserUsesFullLayout();
    const bool friends = friendsPage();
    const float xScale = float(field<int>(dialog, 0x30)) *
        (friends ? 1.0f / borrowWidth : full ? 1.0f / cnUserWidth : 1.0f / userWidth);
    const float yScale = float(field<int>(dialog, 0x34)) *
        (friends ? 1.0f / borrowHeight : full ? 1.0f / cnUserHeight : 1.0f / userHeight);
    return {int(box.x * xScale), int(box.y * yScale), int(box.width * xScale), int(box.height * yScale)};
}

static void placeUserButtons() {
    for (Word i = 0; i < user.controlCount; ++i) {
        const auto& item = user.controls[i];
        const auto box = userLayout(user.dialog, item.rect);
        widgetCall(item.button, 0xac, box.x, box.y, box.width, box.height);
        field<MenuRect>(item.button, 0x1c4) = {0, 0, box.width, box.height};
    }
}

static void queueUserAction(Word action) {
    if (user.dialog && !user.action) user.action = action;
}

static void userButton(Word base, const char32_t* caption, Word action, MenuRect rect, bool accent = false,
                       CnUserArt normal = CnNone, CnUserArt pressed = CnNone) {
    Object button = createDialogButton(base, user.dialog, caption, queueUserAction, action, accent);
    if (!button) return;
    if (!*caption) field<Word>(button, 0x13c) = 0;
    user.controls[user.controlCount++] = {button, rect, normal, pressed};
}

static void userLabel(Word base, const char32_t* caption, MenuRect rect, MenuColor color = userInk) {
    auto& label = user.labels[user.labelCount++];
    makeText(base, label.text, caption);
    label.rect = rect;
    label.color = color;
}

static void userImage(Object art, MenuRect rect) {
    if (art) user.images[user.imageCount++] = {art, rect};
}

static void loadFriendBookArt(Word base) {
    static constexpr char keys[][48] = {
        "IMAGE_ASTER_SOCIAL_TAB_NORMAL", "IMAGE_ASTER_SOCIAL_TAB_SELECTED",
        "IMAGE_ASTER_SOCIAL_BORROW_TOPPER", "IMAGE_ASTER_SOCIAL_BORROW_ROW",
        "IMAGE_ASTER_SOCIAL_FRIEND_AVATAR", "IMAGE_UI_DIALOG_ASSET_CLOSE_BTN",
        "IMAGE_UI_DIALOG_ASSET_CORNER_LEAVES",
    };
    for (Word i = 0; i < FriendBook::ArtCount; ++i) resolveMenuSkin(base, friendBook.art[i], keys[i], 2U);
    if (!friendBook.captions[0]) makeText(base, friendBook.captions[0], U"好友");
    if (!friendBook.captions[1]) makeText(base, friendBook.captions[1], U"添加好友");
}

static void requestFriendBook(Word base, Word operation, Word value) {
    const Word now = wallTime(base);
    friendBook.request = {now + ++sequence, user.data.owner, value, operation};
    friendBook.nextPoll = now;
    friendBook.expires = now + 550;
    friendBook.count = 0;
    friendBook.pending = writeBytes(base, &friendBook.request, sizeof(SocialMessage), dialogFile, dialogTemp);
    friendBook.status = friendBook.pending ? 0 : 3;
}

static bool pollFriendBook(Word base) {
    if (!friendBook.pending) return false;
    const Word now = wallTime(base);
    if (int(now - friendBook.nextPoll) < 0) return false;
    friendBook.nextPoll = now + 5;
    const int fd = native<int>(base, 0x148448, replyFile, 0, 0);
    if (fd >= 0) {
        SocialMessage reply;
        const auto& request = friendBook.request;
        const bool matches = readExact(base, fd, &reply, sizeof(reply)) &&
            reply.token == request.token && reply.owner == request.owner &&
            reply.day == request.day && reply.kind == friendListRequest;
        Word header[5];
        char extra;
        bool valid = matches && readExact(base, fd, header, sizeof(header)) &&
            header[0] <= 3 && header[1] <= maxRoster && header[2] <= 40 && header[3] <= 6 &&
            header[4] <= maxRoster && header[4] <= header[2] &&
            readExact(base, fd, friendBook.entries, header[4] * sizeof(FriendBook::Entry)) &&
            native<int>(base, 0x148460, fd, &extra, 1U) == 0;
        native<int>(base, 0x147b90, fd);
        if (matches) {
            native<int>(base, 0x148424, replyFile);
            if (valid) {
                for (Word i = 0; i < header[4]; ++i) {
                    const auto& row = friendBook.entries[i];
                    if (!row.id || !validFriendAvatar(row.avatar) || !row.name[0] || row.name[39])
                        valid = false;
                }
            }
            friendBook.pending = false;
            friendBook.status = valid ? header[0] : 3;
            if (valid) {
                friendBook.rosterCount = header[1];
                friendBook.total = header[2];
                friendBook.page = header[3];
                friendBook.count = header[4];
            }
            return true;
        }
    }
    if (int(now - friendBook.expires) < 0) return false;
    friendBook.pending = false;
    friendBook.status = 3;
    return true;
}

static void buildFriendBook(Word base) {
    const bool add = user.page == UserPage::AddFriend;
    const auto& art = friendBook.art;
    userImage(art[FriendBook::Topper].image, {18, 21, 634, 46});
    userImage(art[FriendBook::Close].image, {598, 12, 51, 48});
    userImage(art[FriendBook::Leaves].image, {7, 391, 158, 84});
    userImage(art[FriendBook::Leaves].image, {505, 391, 158, 84});
    userButton(base, U"", UserFriendList, {friendTabX(0), 0, friendTabWidth, friendTabBodyHeight});
    userButton(base, U"", UserFriendAdd, {friendTabX(1), 0, friendTabWidth, friendTabBodyHeight});
    userButton(base, U"", UserClose, {598, 12, 51, 48});
    constexpr MenuColor rowInk{65, 46, 23, 255};
    for (Word i = 0; i < friendBook.count; ++i) {
        const auto& row = friendBook.entries[i];
        const auto box = borrowRowBounds(i);
        userImage(art[FriendBook::Row].image, box);
        userImage(art[FriendBook::Avatar].image, {box.x + 6, box.y + 6, 66, 66});
        const Word avatar = row.avatar < friendAvatarCount ? row.avatar : friendAvatarIndex(user.data.owner, row.id);
        userImage(user.portraits[avatar].image, {box.x + 10, box.y + 10, 58, 58});
        char32_t name[18];
        auto* end = append(name, row.name, 10);
        if (row.name[10]) append(end, U"…");
        userLabel(base, name, {box.x + 78, box.y + 2, 214, 35}, userWhite);
        const MenuRect action{box.x + 192, box.y + 41, 102, 29};
        if (!add || friendBook.rosterCount < maxRoster) {
            userButton(base, U"", friendRowAction + i, action);
            userLabel(base, add ? U"添加" : U"移除", action, rowInk);
        }
    }
    if (friendBook.page) userButton(base, U"上一页", UserPrev, {35, 358, 112, 41});
    if ((friendBook.page + 1) * maxRoster < friendBook.total)
        userButton(base, U"下一页", UserNext, {523, 358, 112, 41});
    const char32_t* status = nullptr;
    static constexpr char32_t errors[][18] = {
        U"好友已满", U"这位玩家暂不可添加", U"好友列表暂不可用，请重试"
    };
    if (friendBook.pending) status = U"正在读取好友…";
    else if (friendBook.status) status = errors[friendBook.status - 1];
    else if (add && friendBook.rosterCount == maxRoster) status = U"好友已满";
    else if (!friendBook.count) status = add ? U"暂无可添加的玩家" : U"还没有好友";
    if (status) userLabel(base, status, {130, friendBook.count ? 342 : 187, 410, 39}, userWhite);
    char32_t count[24];
    append(number(append(count, U"好友 "), friendBook.rosterCount), U" / 6");
    userLabel(base, count, {195, 372, 280, 28}, userWhite);
}

static void showLoanPlant(Word base, const UserDialog::Choice& plant, MenuRect box) {
    const auto& alias = plantPackets[plant.index].alias;
    auto& card = user.cards[user.cardCount++];
    loadBorrowPacketArt(base, card.plant, alias);
    card.rect = {box.x + 14, box.y + 6, box.width - 28, box.height - 56};
    card.tier = plant.tier;
    char32_t label[40];
    borrowPlantName(base, label, alias);
    userLabel(base, label, {box.x, box.y + box.height - 49, box.width, 22});
    append(number(label, plant.tier), U"阶");
    userLabel(base, label, {box.x, box.y + box.height - 25, box.width, 20});
}

static MenuRect userChoiceBox(Word index) {
    return {30 + 189 * int(index % 3), 52 + 102 * int(index / 3), 182, 95};
}

static void cnAction(Word base, const char32_t* label, Word action, MenuRect box, int labelOffset = 0) {
    userButton(base, U"", action, box, false, CnAction, CnActionDown);
    const MenuRect labelBox{box.x + labelOffset, box.y, box.width - labelOffset, box.height - 4};
    userLabel(base, label, {labelBox.x + 1, labelBox.y + 2, labelBox.width, labelBox.height}, {25, 48, 15, 255});
    userLabel(base, label, labelBox, userWhite);
}

static void buildCnUserPage(Word base, Object profile, const char32_t* notice) {
    if (user.page == UserPage::Home) {
        userButton(base, U"", UserClose, {623, 3, 53, 55}, false, CnClose, CnCloseDown);
        userImage(user.cnArt[CnDave].image, {13, 141, 215, 292});
        userImage(user.cnArt[CnHint].image, {152, 73, 145, 136});
        const MenuRect portrait{391, 11, 132, 132};
        userImage(user.portraits[user.data.avatar].image, portrait);
        userButton(base, U"", UserAvatars, portrait);
        userImage(user.cnArt[CnName].image, {296, 144, 319, 41});
        const auto name = field<const char32_t*>(profile, 0x58);
        char32_t caption[28];
        append(caption, name && *name ? name : U"玩家", 24);
        userLabel(base, caption, {305, 144, 301, 39}, {73, 46, 16, 255});
        cnAction(base, U"导出玩家数据", UserExport, {294, 215, 326, 56});
        cnAction(base, U"出借的植物", UserLoans, {294, 286, 326, 56});
        cnAction(base, U"礼包码兑换", UserCode, {294, 357, 326, 56}, 42);
        userImage(user.cnArt[CnGift].image, {329, 342, 66, 76});
    } else {
        userButton(base, U"", UserBack, {264, 11, 52, 48}, false, CnCloseTab, CnCloseTabDown);
        userImage(user.portraits[user.data.avatar].image, {114, 14, 106, 106});
        for (Word i = 0; i < friendAvatarCount; ++i) {
            const MenuRect tile{33 + 101 * int(i % 3), 134 + 111 * int(i / 3), 85, 87};
            userImage(user.portraits[i].image, tile);
            userButton(base, U"", UserAvatar + i, tile);
            if (i == user.avatarPreview)
                userLabel(base, U"已选中", {tile.x, tile.y + 83, tile.width, 18}, {81, 92, 27, 255});
        }
        static constexpr char32_t names[][8] = {
            U"豌豆射手", U"向日葵", U"坚果", U"樱桃炸弹", U"路障僵尸", U"雪人僵尸"
        };
        userImage(user.portraits[user.avatarPreview].image, {424, 44, 172, 172});
        userLabel(base, names[user.avatarPreview], {357, 227, 303, 49}, {255, 228, 62, 255});
        cnAction(base, U"更换", UserConfirmAvatar, {401, 357, 220, 49});
    }
    if (notice) {
        if (user.page == UserPage::Home) userLabel(base, notice, {297, 183, 320, 28}, {124, 45, 20, 255});
        else userLabel(base, notice, {342, 298, 310, 28}, userWhite);
    }
}

static void buildUserPage(Word base, Object profile, const char32_t* notice = nullptr) {
    resetUserPage(base);
    if (Object controls = field<Object>(user.dialog, 0xa8)) native<void>(base, 0x9c0818, controls);
    if (friendsPage()) {
        buildFriendBook(base);
        placeUserButtons();
        return;
    }
    if (cnUserUsesFullLayout()) {
        buildCnUserPage(base, profile, notice);
        placeUserButtons();
        return;
    }
    const auto page = user.page;
    static constexpr char32_t headings[][8] = {U"用户", U"选择头像", U"出借的植物", U"选择出借植物"};
    userLabel(base, headings[Word(page)], {20, 9, 580, 31}, userHasCnArt() ? userInk : userWhite);
    const bool home = page == UserPage::Home;
    userButton(base, home ? U"关闭" : U"返回", home ? UserClose : UserBack, {249, 273, 122, 38}, true);
    if (home) {
        const auto name = field<const char32_t*>(profile, 0x58);
        char32_t caption[28];
        append(caption, name && *name ? name : U"玩家", 24);
        userImage(user.portraits[user.data.avatar].image, {55, 71, 116, 116});
        userButton(base, U"", UserAvatars, {55, 71, 116, 116});
        userLabel(base, caption, {25, 193, 176, 27});
        userButton(base, U"更换头像", UserAvatars, {50, 229, 126, 32});
        userButton(base, U"出借的植物", UserLoans, {248, 87, 328, 52}, true);
        userButton(base, U"礼包码兑换", UserCode, {248, 161, 328, 52});
        userButton(base, U"导出玩家数据", UserExport, {248, 229, 328, 32});
    } else if (page == UserPage::Avatars) {
        for (Word i = 0; i < friendAvatarCount; ++i) {
            const auto box = userChoiceBox(i);
            userImage(user.portraits[i].image, {box.x + 58, box.y + 5, 66, 66});
            userButton(base, U"", UserAvatar + i, box);
            if (i == user.data.avatar) userLabel(base, U"当前头像", {box.x, box.y + 69, box.width, 20});
        }
    } else if (page == UserPage::Loans) {
        for (Word slot = 0; slot < userSlots; ++slot) {
            const MenuRect box{30 + 188 * int(slot), 63, 181, 174};
            const UserDialog::Choice* chosen = nullptr;
            for (Word i = 0; i < user.availableCount; ++i) {
                if (sameUserPlant(user.data.loans[slot], plantPackets[user.available[i].index].alias))
                    chosen = user.available + i;
            }
            userButton(base, U"", UserSlot + slot, box);
            if (chosen) showLoanPlant(base, *chosen, box);
            else userLabel(base, U"＋ 添加植物", box);
        }
    } else {
        const Word first = user.plantPage * userPageSize;
        for (Word i = 0; i < userPageSize && first + i < user.availableCount; ++i) {
            const auto box = userChoiceBox(i);
            userButton(base, U"", UserPlant + first + i, box);
            showLoanPlant(base, user.available[first + i], box);
        }
        if (!user.availableCount) userLabel(base, U"暂无可出借的植物", {32, 92, 556, 75});
        if (user.plantPage) userButton(base, U"上一页", UserPrev, {32, 273, 101, 38});
        if (first + userPageSize < user.availableCount) userButton(base, U"下一页", UserNext, {482, 273, 106, 38});
        if (user.data.loans[user.slot][0]) userButton(base, U"清空槽位", UserClear, {141, 273, 98, 38});
    }
    if (notice) userLabel(base, notice, {133, 251, 354, 20}, userWhite);
    placeUserButtons();
}

static void userRect(Word base, Object graphics, MenuRect rect, const MenuColor& color) {
    native<void>(base, 0x1166c30, graphics, &color);
    native<void>(base, 0x1167010, graphics, rect.x, rect.y, rect.width, rect.height);
}

static void userSkinImage(Word base, Object graphics, Object bitmap, MenuRect box) {
    if (bitmap) native<void>(base, 0x11698b4, graphics, bitmap, box.x, box.y, box.width, box.height);
}

// Loaded by the stock UI from FZKATJW.TTF (FZKaTong-M19S).
constexpr Word katong18 = 0x184110c;
constexpr Word katong20 = 0x1841110;

static void drawFriendTabs(Word base, Object dialog, Object graphics) {
    const auto appBase = reinterpret_cast<Object>(base);
    auto font = field<Object>(appBase, katong20);
    const auto label = friendBook.captions[1];
    const int captionWidth = userLayout(dialog, {0, 0, friendTabWidth - 8, 0}).width;
    if (font && label && native<int>(base, 0x13ae4f0, font, &label) > captionWidth)
        font = field<Object>(appBase, katong18);
    const Word selected = user.page == UserPage::AddFriend ? 1U : 0U;
    for (Word i = 0; i < 2; ++i) {
        const auto sprite = friendBook.art[i == selected ? FriendBook::Selected : FriendBook::Tab].image;
        const MenuRect body = userLayout(dialog, {friendTabX(i), 0, friendTabWidth, friendTabBodyHeight});
        // Both sprites use a 672×352 tab body. The selected sprite extends
        // below it to include the pointer.
        MenuRect art = body;
        if (i == selected) art.height = body.height * 428 / 352;
        userSkinImage(base, graphics, sprite, art);
        if (font && friendBook.captions[i])
            native<void>(base, 0x13af2d0, font, graphics, body.x + (body.width - captionWidth) * 0.5f,
                         body.y + body.height * 0.24f, float(captionWidth), &friendBook.captions[i],
                         1U, &userWhite, 0U);
    }
}

static void drawUserDialog(Word base, Object dialog, Object graphics) {
    if (!dialog || dialog != user.dialog) return;
    placeUserButtons();
    const auto oldColor = field<MenuColor>(graphics, 0x4c);
    const auto oldTint = field<unsigned char>(graphics, 0x64);
    native<void>(base, 0x1166e74, graphics, false);
    if (friendsPage()) {
        for (int i = 0; i < 17; ++i)
            userRect(base, graphics, userLayout(dialog, {10, 353 + i * 5, 650, 5}),
                     {42, 27, 16, i * i * 58 / 256});
        native<void>(base, 0x1166e74, graphics, false);
    } else if (userHasCnArt()) {
        if (user.page == UserPage::Avatars) {
            userSkinImage(base, graphics, user.cnArt[CnPaper].image, userLayout(dialog, {7, 63, 337, 366}));
            userSkinImage(base, graphics, user.cnArt[CnPreview].image, userLayout(dialog, {354, 127, 306, 283}));
        } else {
            const MenuRect frame{0, 0, field<int>(dialog, 0x30), field<int>(dialog, 0x34)};
            userSkinImage(base, graphics, user.cnArt[CnFrame].image, frame);
        }
    } else {
        userRect(base, graphics, userLayout(dialog, {14, 44, 592, 221}), userPaper);
    }
    if (user.page == UserPage::Home && !userHasCnArt()) {
        userRect(base, graphics, userLayout(dialog, {18, 52, 188, 209}), {179, 210, 192, 255});
    } else if (user.page == UserPage::Loans) {
        for (int i = 0; i < int(userSlots); ++i)
            userRect(base, graphics, userLayout(dialog, {30 + 188 * i, 63, 181, 174}), {203, 225, 206, 255});
    }
    for (Word i = 0; i < user.controlCount; ++i) {
        const auto& control = user.controls[i];
        const auto style = control.pressed && field<unsigned char>(control.button, 0x1e4)
            ? control.pressed : control.normal;
        if (style) userSkinImage(base, graphics, user.cnArt[style].image, userLayout(dialog, control.rect));
    }
    for (Word i = 0; i < user.imageCount; ++i) {
        const auto& image = user.images[i];
        const auto box = fitBorrowImage(image.art, userLayout(dialog, image.rect));
        const float matrix[] = {box.scale, 0, box.x, 0, box.scale, box.y, 0, 0, 1};
        native<void>(base, 0x116a268, graphics, image.art, matrix);
    }
    if (friendsPage()) drawFriendTabs(base, dialog, graphics);
    for (Word i = 0; i < user.cardCount; ++i) {
        const auto& card = user.cards[i];
        drawSocialSeedPacket(base, graphics, card.plant, userLayout(dialog, card.rect),
                             user.packets[0].image, user.packets[card.tier - 1].image, card.tier, true);
    }

    auto& text = field<const char32_t*>(dialog, 0xb4);
    auto& rect = field<MenuRect>(dialog, 0xe4);
    auto& color = field<MenuColor>(dialog, 0x160);
    const auto oldText = text;
    const auto oldRect = rect;
    const auto oldInk = color;
    for (Word i = 0; i < user.labelCount; ++i) {
        const auto& label = user.labels[i];
        text = label.text;
        rect = userLayout(dialog, label.rect);
        color = label.color;
        native<void>(base, 0x7f17d4, dialog, graphics);
    }
    text = oldText;
    rect = oldRect;
    color = oldInk;
    native<void>(base, 0x1166c30, graphics, &oldColor);
    field<unsigned char>(graphics, 0x64) = oldTint;
}

static void updateUserDialog(Word base) {
    Object app = gameApp(base);
    if (app && user.widget && user.artApp != app && socialContentEnabled(base)) {
        changeMenuGroup(base, app, 2U, true);
        resolveMenuSkin(base, user.mapSkin, "IMAGE_ASTER_SOCIAL_USER_BUTTON", 2U);
        resolveMenuSkin(base, user.mapPressed, "IMAGE_ASTER_SOCIAL_USER_BUTTON_DOWN", 2U);
        resolveMenuSkin(base, user.friendSkin, "IMAGE_UI_HUD_WORLDMAP_DAILY_SIGN_REWARD", 2U);
        resolveMenuSkin(base, user.friendDown, "IMAGE_UI_HUD_WORLDMAP_DAILY_SGIN_REWARD_DOWN", 2U);
        if (!user.friendCaption) makeText(base, user.friendCaption, U"好友");
        static constexpr char artKeys[CnArtCount][44] = {
            "", "IMAGE_ASTER_SOCIAL_CN_USER_FRAME", "IMAGE_ASTER_SOCIAL_CN_USER_DAVE",
            "IMAGE_ASTER_SOCIAL_CN_USER_HINT", "IMAGE_ASTER_SOCIAL_CN_USER_GIFT", "IMAGE_ASTER_SOCIAL_CN_USER_NAME",
            "IMAGE_ASTER_SOCIAL_CN_USER_PAPER", "IMAGE_ASTER_SOCIAL_CN_USER_PREVIEW", "IMAGE_ASTER_SOCIAL_CN_USER_CLOSE",
            "IMAGE_ASTER_SOCIAL_CN_USER_CLOSE_DOWN", "IMAGE_ASTER_SOCIAL_CN_USER_CLOSE_TAB",
            "IMAGE_ASTER_SOCIAL_CN_USER_CLOSE_TAB_DOWN", "IMAGE_ASTER_SOCIAL_CN_USER_ACTION",
            "IMAGE_ASTER_SOCIAL_CN_USER_ACTION_DOWN"
        };
        for (Word i = 1; i < CnArtCount; ++i) resolveMenuSkin(base, user.cnArt[i], artKeys[i], 2U);
        user.artApp = app;
    }
    if (!user.dialog && !user.requested && !user.friendRequested) return;
    Object store = ownerStore(base);
    const Word id = owner(store);
    if (user.dialog && (!userMounted(app) || user.data.owner != id || !socialContentEnabled(base))) {
        closeUserDialog(base);
    }
    if (user.requested || user.friendRequested) {
        const bool openFriends = user.friendRequested;
        user.requested = user.friendRequested = false;
        if (user.dialog || gameBoard(base) || id == ~0U || !socialContentEnabled(base) ||
            social.phase != SocialPhase::Idle) return;
        const auto profile = native<Object>(base, 0x7a98dc, store);
        if (!profile) return;
        const bool cnArt = userHasCnArt();
        user.dialog = openGameDialog(base, app,
                                     openFriends ? borrowWidth : cnArt ? cnUserWidth : userWidth,
                                     openFriends ? borrowHeight : cnArt ? cnUserHeight : userHeight, 0, true);
        if (!user.dialog) return;
        user.app = app;
        readUserPreferences(base, id);
        for (Word i = 0; i < friendAvatarCount; ++i)
            resolveMenuSkin(base, user.portraits[i], cnArt ? communityAvatarKeys[i] : friendAvatarKeys[i], 2U);
        if (openFriends) {
            user.page = UserPage::Friends;
            friendBook.rosterCount = friendBook.total = friendBook.page = 0;
            loadFriendBookArt(base);
            requestFriendBook(base, friendListRequest, 0);
            buildUserPage(base, profile);
            return;
        }
        changeMenuGroup(base, app, packetResourceGroup, true);
        user.heldPackets = true;
        static constexpr char packetKeys[][28] = {"IMAGE_UI_PACKETS_READY", "IMAGE_UI_PACKETS_FRAME_2",
                                                    "IMAGE_UI_PACKETS_FRAME_3", "IMAGE_UI_PACKETS_FRAME_4"};
        for (Word i = 0; i < 4; ++i) resolveMenuSkin(base, user.packets[i], packetKeys[i], 2U);
        findUserPlants(base, profile);
        user.page = UserPage::Home;
        buildUserPage(base, profile);
        const SocialMessage refresh{0, id, 1, 7};
        writeBytes(base, &refresh, sizeof(refresh), dialogFile, dialogTemp);
        return;
    }
    if (user.dialog && friendsPage() && pollFriendBook(base))
        buildUserPage(base, nullptr);
    if (!user.dialog || !user.action) return;
    const Word action = user.action;
    user.action = 0;
    if (action == UserClose || action == UserCode) {
        closeUserDialog(base);
        if (action == UserCode) native<void>(base, 0x402ccc, app);
        return;
    }
    if (friendsPage()) {
        if (friendBook.pending && friendBook.request.kind >= friendAddRequest) return;
        if (action == UserFriendList || action == UserFriendAdd) {
            user.page = action == UserFriendList ? UserPage::Friends : UserPage::AddFriend;
            friendBook.page = friendBook.total = 0;
            requestFriendBook(base, action == UserFriendList ? friendListRequest : friendCatalogRequest, 0);
        } else if (!friendBook.pending && (action == UserPrev || action == UserNext)) {
            const Word page = action == UserPrev && friendBook.page ? friendBook.page - 1 : friendBook.page + 1;
            requestFriendBook(base, user.page == UserPage::Friends ? friendListRequest : friendCatalogRequest, page);
        } else if (!friendBook.pending && action >= friendRowAction && action - friendRowAction < friendBook.count) {
            const Word id = friendBook.entries[action - friendRowAction].id;
            requestFriendBook(base, user.page == UserPage::Friends ? friendRemoveRequest : friendAddRequest, id);
        } else return;
        buildUserPage(base, nullptr);
        return;
    }

    const char32_t* notice = nullptr;
    if (action == UserBack) user.page = user.page == UserPage::Plants ? UserPage::Loans : UserPage::Home;
    else if (action == UserAvatars) {
        user.avatarPreview = user.data.avatar;
        user.page = UserPage::Avatars;
    }
    else if (action == UserLoans) user.page = UserPage::Loans;
    else if (user.page == UserPage::Avatars) {
        const bool picked = action >= UserAvatar && action < UserAvatar + friendAvatarCount;
        if (picked) user.avatarPreview = action - UserAvatar;
        if (action == UserConfirmAvatar || (picked && !userHasCnArt())) {
            const Word before = user.data.avatar;
            user.data.avatar = user.avatarPreview;
            if (saveUserPreferences(base)) user.page = UserPage::Home;
            else {
                user.data.avatar = before;
                notice = U"保存失败";
            }
        }
    } else if (user.page == UserPage::Home && action == UserExport) {
        if (const auto profile = native<Object>(base, 0x7a98dc, store)) {
            if (!exportUser(base, profile)) buildUserPage(base, profile, U"导出失败，请重试");
        }
        return;
    } else if (user.page == UserPage::Loans && action >= UserSlot && action < UserSlot + userSlots) {
        user.slot = action - UserSlot;
        user.plantPage = 0;
        user.page = UserPage::Plants;
    } else if (user.page == UserPage::Plants) {
        if (action == UserPrev && user.plantPage) --user.plantPage;
        else if (action == UserNext && (user.plantPage + 1) * userPageSize < user.availableCount) ++user.plantPage;
        else if (action == UserClear || (action >= UserPlant && action < UserPlant + user.availableCount)) {
            const char* alias = action == UserClear ? "" : plantPackets[user.available[action - UserPlant].index].alias;
            for (Word i = 0; *alias && i < userSlots; ++i) {
                if (i != user.slot && sameUserPlant(user.data.loans[i], alias)) notice = U"这株植物已在其他槽位";
            }
            if (!notice) {
                auto& slot = user.data.loans[user.slot];
                volatile char before[32];
                for (Word i = 0; i < sizeof(slot); ++i) before[i] = slot[i];
                const char* next = alias;
                for (auto& c : slot) {
                    c = *next;
                    if (c) ++next;
                }
                if (saveUserPreferences(base)) user.page = UserPage::Loans;
                else {
                    for (Word i = 0; i < sizeof(slot); ++i) slot[i] = before[i];
                    notice = U"保存失败";
                }
            }
        }
    }
    if (const auto profile = native<Object>(base, 0x7a98dc, store)) buildUserPage(base, profile, notice);
}
}

extern "C" bool asterUserHasCodeEntry(Word base) {
    return socialContentEnabled(base);
}

extern "C" void asterUserAttach(Word base) {
    user.widget = createAdventureHudWidget(base, U"UIWorldMapUserButton");
    user.friendWidget = createAdventureHudWidget(base, U"UIWorldMapFriendButton");
    Object entries[] = {user.widget, user.friendWidget};
    for (const auto entry : entries) {
        if (!entry) continue;
        field<Word>(entry, 0x54) |= 12;
        native<void>(base, 0x9766f4, entry, 1U);
    }
}

static MenuRect userMapWidgetBounds(Object widget) {
    MenuRect bounds;
    const Word method = field<Word>(field<Object>(widget, 0), 0x5c);
    reinterpret_cast<void(*)(MenuRect*, Object)>(method)(&bounds, widget);
    return bounds;
}

static MenuRect userMapSkinBounds(Object sprite, MenuRect box, bool alignLeft, int inset) {
    if (!sprite || box.width <= 2 * inset || box.height <= 2 * inset) return {};
    const auto placement = fitBorrowImage(sprite, {box.x + inset, box.y + inset,
                                                    box.width - 2 * inset, box.height - 2 * inset});
    return {alignLeft ? box.x + inset : int(placement.x), int(placement.y),
            int(field<int>(sprite, 0x28) * placement.scale + 0.5f),
            int(field<int>(sprite, 0x2c) * placement.scale + 0.5f)};
}

extern "C" bool asterUserHit(Word base, Object widget, int x, int y) {
    if (!widget || (widget != user.widget && widget != user.friendWidget) || !socialContentEnabled(base) ||
        !native<bool>(base, 0x97680c, widget, x, y)) return false;
    const bool friends = widget == user.friendWidget;
    const auto box = userMapWidgetBounds(widget);
    const auto skin = userMapSkinBounds(friends ? user.friendSkin.image : user.mapSkin.image, box,
                                        !friends && userHasCnArt(), box.height / 10);
    return x >= skin.x && x < skin.x + skin.width && y >= skin.y && y < skin.y + skin.height;
}

extern "C" bool asterUserTouch(Word base, Object widget, int x, int y, bool pressed) {
    if (!widget || (widget != user.widget && widget != user.friendWidget)) return false;
    const bool hit = asterUserHit(base, widget, x, y);
    auto& wasPressed = widget == user.friendWidget ? user.friendPressed : user.pressed;
    auto& requested = widget == user.friendWidget ? user.friendRequested : user.requested;
    if (wasPressed && hit && !pressed) requested = true;
    wasPressed = pressed && hit;
    return hit;
}

static void drawMapCaption(Word base, Object graphics, MenuRect button, const char32_t* caption, bool pressed) {
    const auto font = field<Object>(reinterpret_cast<Object>(base), katong18);
    if (!font || !caption || button.width <= 0 || button.height <= 0) return;
    const auto previous = field<MenuColor>(graphics, 0x4c);
    const int width = button.width, height = button.height;
    // Reuse the stock jade border and repaint its flat center before drawing the live text.
    const MenuColor green = pressed ? MenuColor{48, 74, 60, 255} : MenuColor{120, 184, 150, 255};
    userRect(base, graphics, {button.x + width * 17 / 100, button.y + height * 24 / 100,
                              width * 68 / 100, height * 49 / 100}, green);
    constexpr MenuColor outline{20, 32, 26, 255};
    const MenuColor ink = pressed ? MenuColor{173, 186, 179, 255} : userWhite;
    const float textY = button.y + height * 0.24f;
    for (int shift = -1; shift <= 1; shift += 2) {
        native<void>(base, 0x13af2d0, font, graphics, float(button.x + shift), textY,
                     float(width), &caption, 1U, &outline, 0U);
        native<void>(base, 0x13af2d0, font, graphics, float(button.x), textY + shift,
                     float(width), &caption, 1U, &outline, 0U);
    }
    native<void>(base, 0x13af2d0, font, graphics, float(button.x), textY,
                 float(width), &caption, 1U, &ink, 0U);
    native<void>(base, 0x1166c30, graphics, &previous);
}

extern "C" void asterSignMapDraw(Word base, Object graphics, Object sprite, bool pressed) {
    native<void>(base, 0x11694c8, graphics, sprite, 0, 0);
    if (!sprite) return;
    if (!user.signCaption) makeText(base, user.signCaption, U"签到");
    drawMapCaption(base, graphics, {0, 0, field<int>(sprite, 0x28), field<int>(sprite, 0x2c)},
                   user.signCaption, pressed);
}

extern "C" void asterUserDraw(Word base, Object widget, Object graphics) {
    if (!widget || (widget != user.widget && widget != user.friendWidget) || !socialContentEnabled(base) ||
        !native<bool>(base, 0x976720, widget)) return;
    const auto box = userMapWidgetBounds(widget);
    if (box.width < 10 || box.height < 10) return;
    if (widget == user.friendWidget) {
        const auto tint = field<unsigned char>(graphics, 0x64);
        native<void>(base, 0x1166e74, graphics, false);
        const auto sprite = user.friendPressed && user.friendDown.image ? user.friendDown.image : user.friendSkin.image;
        const auto button = userMapSkinBounds(sprite, box, false, box.height / 10);
        userSkinImage(base, graphics, sprite, button);
        drawMapCaption(base, graphics, button, user.friendCaption, user.friendPressed);
        field<unsigned char>(graphics, 0x64) = tint;
        return;
    }
    if (!user.mapSkin.image) return;

    const int inset = box.height / 10 + (user.pressed ? box.height / 40 : 0);
    const auto image = user.pressed && user.mapPressed.image ? user.mapPressed.image : user.mapSkin.image;
    auto fitted = fitBorrowImage(image, {box.x + inset, box.y + inset,
                                         box.width - 2 * inset, box.height - 2 * inset});
    if (userHasCnArt()) fitted.x = float(box.x + inset);
    const auto tint = field<unsigned char>(graphics, 0x64);
    const float matrix[] = {fitted.scale, 0, fitted.x, 0, fitted.scale, fitted.y, 0, 0, 1};
    native<void>(base, 0x1166e74, graphics, false);
    native<void>(base, 0x116a268, graphics, image, matrix);
    field<unsigned char>(graphics, 0x64) = tint;
}

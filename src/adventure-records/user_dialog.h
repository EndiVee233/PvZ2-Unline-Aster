#pragma once

namespace {
constexpr int userWidth = 620;
constexpr int userHeight = 324;
constexpr int cnUserWidth = 680;
constexpr int cnUserHeight = 448;
constexpr Word userSlots = 3;
constexpr Word userPageSize = 6;
constexpr char userPlants[][32] = {
#include "adventure_user_plants.inc"
};
constexpr Word userPlantCount = sizeof(userPlants) / sizeof(userPlants[0]);
constexpr MenuColor userWhite{255, 249, 227, 255};
constexpr MenuColor userInk{26, 63, 58, 255};
constexpr MenuColor userPaper{233, 242, 219, 255};

struct UserPreferences {
    Word version, owner, avatar;
    char loans[userSlots][32];
};
static_assert(sizeof(UserPreferences) == 108);

enum class UserPage { Home, Avatars, Loans, Plants };
enum UserAction : Word { UserClose = 1, UserBack, UserAvatars, UserLoans, UserCode,
                         UserPrev, UserNext, UserClear, UserConfirmAvatar, UserExport,
                         UserSlot = 16, UserAvatar = 32, UserPlant = 64 };
enum CnUserArt : Word {
    CnNone, CnFrame, CnDave, CnHint, CnGift, CnName, CnPaper, CnPreview, CnClose, CnCloseDown,
    CnCloseTab, CnCloseTabDown, CnAction, CnActionDown, CnArtCount
};
struct UserDialog {
    Object widget, dialog, app, artApp;
    bool requested, pressed;
    UserPreferences data;
    UserPage page;
    Word action, slot, plantPage, availableCount, avatarPreview;
    struct Choice { Word index, tier; } available[userPlantCount];
    ButtonSkin portraits[friendAvatarCount];
    ButtonSkin packets[4];
    ButtonSkin mapSkin, mapPressed;
    ButtonSkin cnArt[CnArtCount];
    struct Label { const char32_t* text; MenuRect rect; MenuColor color; } labels[20];
    struct Control { Object button; MenuRect rect; CnUserArt normal, pressed; } controls[10];
    struct Image { Object art; MenuRect rect; } images[9];
    struct LoanCard { BorrowRowView plant; MenuRect rect; Word tier; } cards[userPageSize];
    Word labelCount, controlCount, imageCount, cardCount;
};
static UserDialog user;

static bool userHasCnArt() {
    return user.cnArt[CnFrame].image != nullptr;
}

static bool userDrawsOwnFrame(Object dialog) {
    return dialog && dialog == user.dialog && userHasCnArt();
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
        native<void>(base, 0x14ed0e1, &alias, userPlants[i], &allocator);
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
            const auto& type = userPlants[plant.index];
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
    resetUserPage(base);
    user.dialog = user.app = nullptr;
    user.action = 0;
}

static MenuRect userLayout(Object dialog, MenuRect box) {
    const bool full = cnUserUsesFullLayout();
    const float xScale = float(field<int>(dialog, 0x30)) * (full ? 1.0f / cnUserWidth : 1.0f / userWidth);
    const float yScale = float(field<int>(dialog, 0x34)) * (full ? 1.0f / cnUserHeight : 1.0f / userHeight);
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

static void showLoanPlant(Word base, const UserDialog::Choice& plant, MenuRect box) {
    const auto& alias = userPlants[plant.index];
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
                if (sameUserPlant(user.data.loans[slot], userPlants[user.available[i].index]))
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

static void drawUserDialog(Word base, Object dialog, Object graphics) {
    if (!dialog || dialog != user.dialog) return;
    placeUserButtons();
    const auto oldColor = field<MenuColor>(graphics, 0x4c);
    const auto oldTint = field<unsigned char>(graphics, 0x64);
    native<void>(base, 0x1166e74, graphics, false);
    if (userHasCnArt()) {
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
    for (Word i = 0; i < user.cardCount; ++i) {
        const auto& card = user.cards[i];
        drawSocialSeedPacket(base, graphics, card.plant, userLayout(dialog, card.rect),
                             user.packets[0].image, user.packets[card.tier - 1].image, card.tier);
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
    if (!user.dialog && !user.requested) return;
    Object store = ownerStore(base);
    const Word id = owner(store);
    if (user.dialog && (!userMounted(app) || user.data.owner != id || !socialContentEnabled(base))) {
        closeUserDialog(base);
    }
    if (user.requested) {
        user.requested = false;
        if (user.dialog || gameBoard(base) || id == ~0U || !socialContentEnabled(base) ||
            social.phase != SocialPhase::Idle) return;
        const auto profile = native<Object>(base, 0x7a98dc, store);
        if (!profile) return;
        const bool cnArt = userHasCnArt();
        user.dialog = openGameDialog(base, app, cnArt ? cnUserWidth : userWidth,
                                     cnArt ? cnUserHeight : userHeight, 0, true);
        if (!user.dialog) return;
        user.app = app;
        readUserPreferences(base, id);
        for (Word i = 0; i < friendAvatarCount; ++i)
            resolveMenuSkin(base, user.portraits[i], cnArt ? communityAvatarKeys[i] : friendAvatarKeys[i], 2U);
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
    if (!user.dialog || !user.action) return;
    const Word action = user.action;
    user.action = 0;
    if (action == UserClose || action == UserCode) {
        closeUserDialog(base);
        if (action == UserCode) native<void>(base, 0x402ccc, app);
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
            const char* alias = action == UserClear ? "" : userPlants[user.available[action - UserPlant].index];
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
    if (!user.widget) return;
    field<Word>(user.widget, 0x54) |= 8;
    native<void>(base, 0x9766f4, user.widget, 1U);
}

extern "C" bool asterUserHit(Word base, Object widget, int x, int y) {
    return widget == user.widget && socialContentEnabled(base) &&
        native<bool>(base, 0x97680c, widget, x, y);
}

extern "C" bool asterUserTouch(Word base, Object widget, int x, int y, bool pressed) {
    const bool hit = asterUserHit(base, widget, x, y);
    if (widget != user.widget) return false;
    if (user.pressed && hit && !pressed) user.requested = true;
    user.pressed = pressed && hit;
    return hit;
}

extern "C" void asterUserDraw(Word base, Object widget, Object graphics) {
    if (widget != user.widget || !user.mapSkin.image || !socialContentEnabled(base) ||
        !native<bool>(base, 0x976720, widget)) return;
    MenuRect box;
    const Word bounds = field<Word>(field<Object>(widget, 0), 0x5c);
    reinterpret_cast<void(*)(MenuRect*, Object)>(bounds)(&box, widget);
    if (box.width < 10 || box.height < 10) return;

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

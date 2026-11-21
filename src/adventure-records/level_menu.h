#pragma once

namespace {
struct FriendScore {
    Word stars;
    Word elapsedMs;
    char32_t name[40];
};

constexpr Word maxFriendScores = 160;
constexpr Word scoresPerPage = 3;
constexpr Word chooseFriend = 0x100;

struct MenuRect { int x, y, width, height; };
struct MenuColor { int red, green, blue, alpha; };

struct ButtonSkin {
    Word drawMode;
    Object image;
    Word options[6];
};

enum MenuArt : Word {
    Ribbon, Close, ClosePressed, InactiveTab, ActiveTab, GoalsCard,
    StarOff, StarOn, LockedTab, LockedTabPressed, ViewButton, ViewButtonPressed, MenuArtCount
};
static ButtonSkin menuArt[MenuArtCount];
static constexpr char menuGroups[][16] = {"UI_AwardDialog", "UI_GameIntro"};
static Word heldMenuGroups;

struct LevelMenu {
    Object dialog;
    Word action;
    Word stars;
    Word page;
    Word watch;
    Word chosenFriend;
    Word earnedStars;
    bool unlocked;
    Word bestTimes[4];
    Word scoreCount;
    FriendScore scores[maxFriendScores];
    struct ScoreRow {
        Object widget;
        bool selected;
        const char32_t* player;
        const char32_t* time;
    } scoreRows[scoresPerPage];
    Word scoreRowCount;
    struct Button {
        Object widget;
        int x, y, width, height, labelHeight;
    } buttons[12];
    Word buttonCount;
    const char32_t* headings[7];
};

static LevelMenu menu;
static Record menuBest;

enum MenuAction : Word { Dismiss = 1, Enter, PrevPage, NextPage, WatchFriend, SelectStars = 16 };

static Object gameApp(Word base) {
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return holder ? field<Object>(holder, 0) : nullptr;
}

template<class... Args> static void widgetCall(Object widget, Word slot, Args... args) {
    auto method = field<Word>(field<Object>(widget, 0), slot);
    reinterpret_cast<void(*)(Object, Args...)>(method)(widget, args...);
}

static bool menuMounted(Object app) {
    return app && menu.dialog && field<Object>(field<Object>(app, 0x2c0), 0x88) == menu.dialog;
}

static void makeText(Word base, const char32_t*& result, const char32_t* content) {
    char allocator = 0;
    native<void>(base, 0x14eb451, &result, content, &allocator);
}

static void freeText(Word base, const char32_t*& value) {
    if (!value) return;
    char allocator = 0;
    native<void>(base, 0x14ea239, value - 3, &allocator);
    value = nullptr;
}

static char32_t* append(char32_t* out, const char32_t* text, Word limit = 128) {
    for (Word i = 0; i < limit && text[i]; ++i) *out++ = text[i];
    *out = 0;
    return out;
}

static char32_t* number(char32_t* out, Word value, Word digits = 1) {
    char32_t reverse[10];
    Word count = 0;
    do {
        reverse[count++] = U'0' + value % 10;
        value /= 10;
    } while (value || count < digits);
    while (count) *out++ = reverse[--count];
    *out = 0;
    return out;
}

static void formatTime(char32_t* out, Word ms) {
    if (!ms) {
        append(out, U"暂无成绩");
        return;
    }
    out = append(number(out, ms / 60000), U"分");
    out = append(number(out, ms / 1000 % 60, 2), U".");
    append(number(out, ms % 1000, 3), U"秒");
}

static void releaseHeadings(Word base) {
    for (auto& heading : menu.headings) freeText(base, heading);
    for (Word i = 0; i < menu.scoreRowCount; ++i) {
        freeText(base, menu.scoreRows[i].player);
        freeText(base, menu.scoreRows[i].time);
    }
    menu.scoreRowCount = 0;
}

static void changeMenuGroup(Word base, Object app, Word index, bool load) {
    char allocator = 0;
    const char* name = nullptr;
    native<void>(base, 0x14ed0e1, &name, menuGroups[index], &allocator);
    native<void>(base, load ? 0x41c74c : 0x41c410, app, &name);
    releaseString(base, name);
}

static void closeMenu(Word base) {
    Object app = gameApp(base);
    if (app && menu.dialog) {
        Object manager = field<Object>(app, 0x2c0);
        widgetCall(manager, 0x14, menu.dialog);
        native<void>(base, 0x1317170, manager, menu.dialog);
        widgetCall(app, 0xa8, menu.dialog);
        for (Word i = 0; i < 2; ++i) {
            if (heldMenuGroups & (1U << i)) changeMenuGroup(base, app, i, false);
        }
    }
    menu.dialog = nullptr;
    menu.buttonCount = 0;
    heldMenuGroups = 0;
    releaseHeadings(base);
}

static void queueMenuAction(Word action) {
    if (menu.dialog && !menu.action && !menu.watch) menu.action = action;
}

static void loadMenuArt(Word base, Object app) {
    static constexpr char keys[][50] = {
        "IMAGE_UI_AWARDDIALOG_RIBBON",
        "IMAGE_UI_DIALOG_ASSET_CLOSE_BTN", "IMAGE_UI_DIALOG_ASSET_CLOSE_DOWN",
        "IMAGE_UI_GENERIC_TAB_N", "IMAGE_UI_GENERIC_TAB_S",
        "IMAGE_UI_GAME_INTRO_GAME_INTRO_DIALOG",
        "IMAGE_UI_STAR_REWARD_STAR_REWARD_152X148", "IMAGE_UI_STAR_REWARD_STAR_REWARD_141X137",
        "IMAGE_UI_AWARDDIALOG_RATING_GREY_BTN", "IMAGE_UI_AWARDDIALOG_RATING_GREY_BTN_DOWN",
        "IMAGE_UI_GENERIC_GREENBUTTON", "IMAGE_UI_GENERIC_GREENBUTTON_DOWN"
    };
    if (!field<Object>(reinterpret_cast<Object>(base), 0x183607c)) return;
    auto resolve = [&](Word i) {
        // The stock button-skin factory resolves the image by name. Footer
        // buttons use the same fixed corners and resizable middle as Pause.
        struct ImageDescriptor { Word reserved[3]; const char* key; WeakRef ref; };
        ImageDescriptor descriptor;
        descriptor.key = keys[i];
        descriptor.ref = {0, 0};
        const Word drawMode = i == ViewButton || i == ViewButtonPressed ? 3U : 2U;
        native<void>(base, 0x7e8a28, menuArt + i, &descriptor, drawMode);
        native<void>(base, 0x1d9bb4, &descriptor.ref, 0U, 0U, 0U);
    };
    for (Word i = 0; i < MenuArtCount; ++i) resolve(i);
    constexpr MenuArt delayed[] = {Ribbon, GoalsCard};
    for (Word i = 0; i < 2; ++i) {
        if (menuArt[delayed[i]].image) continue;
        changeMenuGroup(base, app, i, true);
        heldMenuGroups |= 1U << i;
        resolve(delayed[i]);
        if (delayed[i] == Ribbon) {
            resolve(LockedTab);
            resolve(LockedTabPressed);
        }
    }
}

static Object addMenuButton(Word base, const char32_t* label, Word action, int x, int y, int w, int h,
                            bool highlighted = false, MenuArt normal = MenuArtCount,
                            MenuArt pressed = MenuArtCount, int labelHeight = 0) {
    const char32_t* text = nullptr;
    makeText(base, text, label);
    // Stock member-function delegate. The adapter calls field 1 with the
    // context from field 3 after mouse-up has been dispatched.
    Word delegate[6] = {base + 0x1787408, reinterpret_cast<Word>(&queueMenuAction),
                        0, action, 1, base + 0x2cc954};
    Object button = native<Object>(base, 0x7f25ec, menu.dialog, &text, delegate, highlighted ? 0 : 1);
    freeText(base, text);
    if (!button) return nullptr;
    if (action >= chooseFriend) {
        // The row renders its own name and time. Keep the stock input handler.
        field<Word>(button, 0x13c) = 0;
    } else if (normal != MenuArtCount && menuArt[normal].image) {
        const auto& down = pressed != MenuArtCount && menuArt[pressed].image
            ? menuArt[pressed] : menuArt[normal];
        native<void>(base, 0x7e90dc, button, menuArt + normal, &down);
        if (menuArt[normal].drawMode == 2) field<Word>(button, 0x13c) = 1;
    }
    menu.buttons[menu.buttonCount++] = {button, x, y, w, h, labelHeight};
    return button;
}

static constexpr int menuWidth = 730;
static constexpr int menuHeight = 375;
static constexpr int menuTopGutter = 41;
static constexpr int menuWidgetHeight = menuTopGutter + menuHeight;
static constexpr int scoresPanelWidth = 253;
static constexpr int challengePanelLeft = 267;
static constexpr int footerButtonWidth = 150;
static constexpr int footerButtonHeight = 49;

static constexpr MenuRect scoreRowBounds(Word row) {
    return {16, 90 + 43 * int(row), 221, 41};
}

static void placeMenuButtons(Object dialog) {
    const int width = field<int>(dialog, 0x30);
    const int height = field<int>(dialog, 0x34);
    for (Word i = 0; i < menu.buttonCount; ++i) {
        auto& button = menu.buttons[i];
        const int w = button.width * width / menuWidth;
        const int h = button.height * height / menuWidgetHeight;
        widgetCall(button.widget, 0xac, button.x * width / menuWidth,
                   (menuTopGutter + button.y) * height / menuWidgetHeight, w, h);
        if (button.labelHeight) {
            // A tab's arrow extends past the body that contains the label.
            const int labelHeight = button.labelHeight * height / menuWidgetHeight;
            field<MenuRect>(button.widget, 0x1c4) = {0, 0, w, labelHeight - 4};
        } else {
            // Let the stock button renderer center the label in its new bounds.
            field<MenuRect>(button.widget, 0x1c4) = {0, 0, -1, -1};
        }
    }
}

static constexpr char egyptStarTrophyLevel[] = "egypt11";

static Word earnedStars(Word base, Object profile, const char* const* alias) {
    Word mask = 0;
    for (Word i = 0; i < 3; ++i) {
        if (native<bool>(base, 0x708f8c, profile, alias, i)) mask |= 1U << i;
    }
    return mask;
}

static bool starChallengesUnlocked(Word base, Word day, Word* earned = nullptr) {
    Object store = ownerStore(base);
    Object profile = store ? native<Object>(base, 0x7a98dc, store) : nullptr;
    if (!profile) return false;
    char allocator = 0;
    const char* alias = nullptr;
    native<void>(base, 0x14ed0e1, &alias, day == 1 ? "egypt1" : "egypt2", &allocator);
    bool cleared = native<bool>(base, 0x708190, profile, &alias);
    if (earned) *earned = earnedStars(base, profile, &alias);
    releaseString(base, alias);
    if (cleared) return true;

    // The engine checks the claimed progress of the world's StarChallengeUnlockLevel.
    // Egypt 11 awards the native world trophy on its first clear.
    native<void>(base, 0x14ed0e1, &alias, egyptStarTrophyLevel, &allocator);
    cleared = native<bool>(base, 0x708190, profile, &alias);
    releaseString(base, alias);
    return cleared;
}

static constexpr char32_t conditions[2][4][72] = {
    {U"击败所有僵尸，完成主线关卡",
     U"别让僵尸踩坏花坛\n保住全部小推车",
     U"场上最多同时有 12 株植物\n遵守种植线限制\n保住全部小推车",
     U"最多损失 1 株植物\n最多使用 1250 阳光\n保住全部小推车"},
    {U"击败所有僵尸，完成主线关卡",
     U"30 秒内不使用阳光\n保住全部小推车",
     U"别让僵尸踩坏花坛\n最多损失 2 株植物\n保住全部小推车",
     U"至少生产 2500 阳光\n场上最多同时有 15 株植物\n保住全部小推车"},
};

static bool showMenu(Word base, Word day) {
    Object app = gameApp(base);
    if (!app) return false;
    if (menu.dialog) {
        if (!menuMounted(app)) return false;
        native<void>(base, 0x9c0818, field<Object>(menu.dialog, 0xa8));
        menu.buttonCount = 0;
        releaseHeadings(base);
    } else {
        if (field<Object>(app, 0x1370) || field<Word>(app, 0x1374)) return false;
        // Match the engine's centered window coordinates across aspect ratios.
        const float scale = field<float>(app, 0x698);
        const float maxWidth = float(field<int>(app, 0x524)) * 0.92f;
        const float maxHeight = float(field<int>(app, 0x528)) * 0.92f;
        if (!(scale > 0) || maxWidth <= 0 || maxHeight <= 0) return false;
        const float width = menuWidth * scale < maxWidth ? menuWidth * scale : maxWidth;
        const float height = menuWidgetHeight * scale < maxHeight ? menuWidgetHeight * scale : maxHeight;
        menu.dialog = native<Object>(base, 0x14c1a7d, 0x170U);
        if (!menu.dialog) return false;
        native<void>(base, 0x7f1b6c, menu.dialog);
        field<unsigned char>(menu.dialog, 0xcd) = 1; // Native full-window dimmer.
        field<float>(menu.dialog, 0xd0) = 0.5f;
        const float topGutter = height * menuTopGutter / menuWidgetHeight;
        const float y = (field<int>(app, 0x528) - height - topGutter) * 0.5f;
        widgetCall(menu.dialog, 0xac, int((field<int>(app, 0x524) - width) * 0.5f),
                   y > 0 ? int(y) : 0, int(width), int(height));
        // Use WidgetManager's modal input stack without promoting the map's
        // full-screen transition widgets above this dialog.
        Object manager = field<Object>(app, 0x2c0);
        widgetCall(manager, 0x10, menu.dialog);
        widgetCall(manager, 0x38, menu.dialog);
        native<void>(base, 0x1317158, manager, menu.dialog);
        widgetCall(manager, 0x2c, menu.dialog);
        loadMenuArt(base, app);
    }

    makeText(base, menu.headings[0], day == 1 ? U"神秘埃及 · 第 1 天" : U"神秘埃及 · 第 2 天");
    makeText(base, menu.headings[1], U"过关条件");
    const char32_t* goals = conditions[day - 1][menu.stars];
    if (!menu.unlocked) {
        goals = menu.stars ? U"完成本关主线，或领取\n第 11 天的三星罐头"
                           : U"完成本关主线可解锁三星\n也可领取第 11 天的三星罐头";
    }
    makeText(base, menu.headings[2], goals);
    makeText(base, menu.headings[3], U"我的成绩");
    makeText(base, menu.headings[5], U"好友成绩");
    char32_t label[64];
    formatTime(label, menu.bestTimes[menu.stars]);
    makeText(base, menu.headings[6], label);

    Word rank = 0;
    for (Word i = 0; i < menu.scoreCount; ++i) {
        const auto& score = menu.scores[i];
        if (score.stars != menu.stars) continue;
        ++rank;
        if (rank <= menu.page * scoresPerPage || menu.scoreRowCount == scoresPerPage) continue;
        if (!menu.chosenFriend) menu.chosenFriend = chooseFriend + i;
        const auto bounds = scoreRowBounds(menu.scoreRowCount);
        auto& row = menu.scoreRows[menu.scoreRowCount++];
        row.selected = menu.chosenFriend == chooseFriend + i;
        row.widget = addMenuButton(base, U"", chooseFriend + i, bounds.x, bounds.y, bounds.width, bounds.height);
        auto* end = append(append(number(label, rank), U"  "), score.name, 7);
        if (score.name[7]) append(end, U"…");
        makeText(base, row.player, label);
        formatTime(label, score.elapsedMs);
        makeText(base, row.time, label);
    }
    if (!rank) {
        makeText(base, menu.headings[4], U"暂无好友成绩");
    } else if (rank > scoresPerPage) {
        if (menu.page) addMenuButton(base, U"上一页", PrevPage, 17, 219, 92, 32);
        if ((menu.page + 1) * scoresPerPage < rank) {
            addMenuButton(base, U"下一页", NextPage, 144, 219, 92, 32);
        }
    }

    static constexpr char32_t tabs[][4] = {U"无星", U"第一星", U"第二星", U"第三星"};
    for (Word i = 0; i < 4; ++i) {
        const bool selected = i == menu.stars;
        const bool locked = i && !menu.unlocked;
        const MenuArt skin = locked ? (selected ? LockedTabPressed : LockedTab)
                                    : (selected ? ActiveTab : InactiveTab);
        // The green tab extends below its shoulders into the conditions card.
        constexpr int tabHeight = 46;
        const int height = skin == ActiveTab ? 58 : tabHeight;
        addMenuButton(base, tabs[i], SelectStars + i, 286 + int(i) * 105, 147, 100, height,
                      selected, skin, locked ? LockedTabPressed : skin, tabHeight);
    }
    addMenuButton(base, menuArt[Close].image ? U"" : U"×", Dismiss, 669, -35, 45, 36,
                  false, Close, ClosePressed);
    if (menu.chosenFriend) {
        addMenuButton(base, U"查看阵型", WatchFriend, (scoresPanelWidth - footerButtonWidth) / 2, 317,
                      footerButtonWidth, footerButtonHeight, true, ViewButton, ViewButtonPressed);
    }
    if (!menu.stars || menu.unlocked) {
        addMenuButton(base, U"进入游戏", Enter, (challengePanelLeft + menuWidth - footerButtonWidth) / 2, 317,
                      footerButtonWidth, footerButtonHeight, true);
    }
    return true;
}

static void renderMenu(Word base, Object dialog, Object graphics) {
    // Dialog titles, text and buttons all use the engine's existing HD fonts.
    // Draw the original body renderer in the two columns with local text rectangles.
    auto& body = field<const char32_t*>(dialog, 0xb4);
    auto& bodyRect = field<MenuRect>(dialog, 0xe4);
    auto& bodyColor = field<MenuColor>(dialog, 0x160);
    const auto previousRect = bodyRect;
    const auto previousBody = body;
    const auto previousBodyColor = bodyColor;
    const auto previousColor = field<MenuColor>(graphics, 0x4c);
    const int width = field<int>(dialog, 0x30);
    const int height = field<int>(dialog, 0x34);
    auto fit = [&](MenuRect r) -> MenuRect {
        return {r.x * width / menuWidth, (menuTopGutter + r.y) * height / menuWidgetHeight,
                r.width * width / menuWidth, r.height * height / menuWidgetHeight};
    };
    auto fill = [&](MenuRect r, const MenuColor& color) {
        const auto box = fit(r);
        native<void>(base, 0x1166c30, graphics, &color);
        native<void>(base, 0x1167010, graphics, box.x, box.y, box.width, box.height);
    };
    auto drawImage = [&](MenuArt style, MenuRect r) {
        if (!menuArt[style].image) return;
        const auto box = fit(r);
        native<void>(base, 0x11698b4, graphics, menuArt[style].image, box.x, box.y, box.width, box.height);
    };
    auto drawText = [&](const char32_t* text, MenuRect r, const MenuColor& color) {
        if (!text) return;
        body = text;
        bodyRect = fit(r);
        bodyColor = color;
        native<void>(base, 0x7f17d4, dialog, graphics);
    };

    constexpr MenuColor border{81, 42, 23, 255};
    constexpr MenuColor paper{239, 228, 190, 255};
    constexpr MenuColor ink{70, 47, 17, 255};
    constexpr MenuColor scoreInk{117, 44, 21, 255};
    constexpr MenuColor selectedScore{81, 106, 48, 255};
    constexpr MenuColor pressedScore{50, 68, 32, 255};
    constexpr MenuColor white{255, 249, 220, 255};
    constexpr MenuRect goalsCard{280, 189, 436, 122};
    constexpr MenuRect personalScoreCard{22, 252, 209, 63};
    if (!menuArt[GoalsCard].image) {
        fill(goalsCard, border);
        fill({goalsCard.x + 2, goalsCard.y + 2, goalsCard.width - 4, goalsCard.height - 5}, paper);
        fill(personalScoreCard, paper);
    }
    native<void>(base, 0x1166c30, graphics, &white);
    drawImage(GoalsCard, goalsCard);
    drawImage(GoalsCard, personalScoreCard);
    drawImage(Ribbon, {275, -14, 446, 98});
    for (Word i = 0; i < 3; ++i) {
        const MenuArt star = (menu.earnedStars & (1U << i)) ? StarOn : StarOff;
        drawImage(star, {375 + int(i) * 94, i == 1 ? -5 : 10, 58, 55});
    }

    for (Word i = 0; i < menu.scoreRowCount; ++i) {
        const auto& row = menu.scoreRows[i];
        const auto box = scoreRowBounds(i);
        const bool pressed = row.widget && field<unsigned char>(row.widget, 0x1e4);
        native<void>(base, 0x1166c30, graphics, &white);
        if (menuArt[GoalsCard].image) drawImage(GoalsCard, box);
        else fill(box, paper);
        if (row.selected || pressed) {
            fill({box.x + 5, box.y + 5, 3, box.height - 11}, pressed ? pressedScore : selectedScore);
        }
        drawText(row.player, {box.x + 11, box.y, box.width - 22, 21}, ink);
        drawText(row.time, {box.x + 11, box.y + 19, box.width - 22, 22}, row.selected ? selectedScore : scoreInk);
    }

    constexpr MenuRect boxes[] = {
        {13, 30, 227, 28}, {280, 99, 436, 29}, {298, 203, 400, 96},
        {27, 250, 198, 34}, {15, 126, 223, 50},
        {13, 59, 227, 31}, {27, 280, 198, 33}
    };
    for (Word i = 0; i < 7; ++i) {
        drawText(menu.headings[i], boxes[i], i == 6 ? scoreInk : i == 2 || i == 3 ? ink : white);
    }
    body = previousBody;
    bodyRect = previousRect;
    bodyColor = previousBodyColor;
    native<void>(base, 0x1166c30, graphics, &previousColor);
}
}

extern "C" void asterAdventureDrawMenuPanel(Word base, Object dialog, Object graphics, const MenuRect* bounds) {
    if (menu.dialog != dialog) {
        native<void>(base, 0x7f3470, dialog, graphics, bounds);
        return;
    }
    // Both frames share the modal hit area. The gutter above them holds the
    // close button and the top of the challenge ribbon.
    const int gutter = field<int>(dialog, 0x34) * menuTopGutter / menuWidgetHeight;
    const int scoresWidth = bounds->width * scoresPanelWidth / menuWidth;
    const int challengeLeft = bounds->width * challengePanelLeft / menuWidth;
    const MenuRect scores{bounds->x, bounds->y + gutter, scoresWidth, bounds->height - gutter};
    const MenuRect challenge{bounds->x, scores.y, bounds->width - challengeLeft, scores.height};
    native<void>(base, 0x7f3470, dialog, graphics, &scores);
    // The stock renderer starts its fill tiles at the graphics origin.
    auto& originX = field<float>(graphics, 8);
    const float previousX = originX;
    originX += float(challengeLeft);
    native<void>(base, 0x7f3470, dialog, graphics, &challenge);
    originX = previousX;
}

extern "C" void asterAdventureDrawMenu(Word base, Object dialog, Object graphics) {
    if (menu.dialog == dialog) {
        placeMenuButtons(dialog);
        renderMenu(base, dialog, graphics);
    }
}

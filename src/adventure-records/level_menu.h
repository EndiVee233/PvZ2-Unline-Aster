#pragma once

namespace {
static bool drawBorrowDialogPanel(Word base, Object dialog, Object graphics, const struct MenuRect* bounds);
static void drawBorrowDialogContents(Word base, Object dialog, Object graphics);
static void drawUserDialog(Word base, Object dialog, Object graphics);
static bool userDrawsOwnFrame(Object dialog);
struct FriendScore {
    Word id;
    Word stars;
    Word elapsedMs;
    Word avatar;
    char32_t name[40];
};

constexpr Word maxFriendScores = 160;
constexpr Word scoresPerPage = 3;
constexpr Word chooseFriend = 0x100;
constexpr Word chooseSelf = chooseFriend + maxFriendScores;
constexpr char32_t selfName[] = U"我";

struct MenuRect { int x, y, width, height; };
struct MenuColor { int red, green, blue, alpha; };

struct ButtonSkin {
    Word drawMode;
    Object image;
    Word options[6];
};

enum MenuArt : Word {
    Ribbon, Close, ClosePressed, InactiveTab, ActiveTab, GoalsCard,
    StarOff, StarOn, LockedTab, LockedTabPressed, ViewButton, ViewButtonPressed,
#ifdef ASTER_SOCIAL_ART
    ScorePaper, SocialTab, SocialTabSelected, SocialTabLocked,
    GoalLineLeft, GoalLineRight, FriendRow, FriendAvatar, FriendHover,
    FriendPortrait,
    CommunityPortrait = FriendPortrait + friendAvatarCount,
    MenuArtCount = CommunityPortrait + friendAvatarCount
#else
    MenuArtCount
#endif
};
static ButtonSkin menuArt[MenuArtCount];
static constexpr char menuGroups[][16] = {"UI_AwardDialog", "UI_GameIntro", "UI_AsterSocial"};
static Word heldMenuGroups;

struct LevelMenu {
    Object dialog;
    const AdventureRecords::LevelInfo* level;
    Word action;
    Word stars;
    Word page;
    Word watch;
    Word selectedScore;
    Word earnedStars;
    bool unlocked;
    Word bestTimes[4];
    Word scoreCount;
    FriendScore scores[maxFriendScores];
    struct ScoreRow {
        Object widget;
        bool selected;
        Word friendId, avatar;
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

enum MenuAction : Word { Dismiss = 1, Enter, PrevPage, NextPage, WatchFormation, SelectStars = 16 };

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

static Object openGameDialog(Word base, Object app, int designWidth, int designHeight, int gutter,
                             bool keepAspect = false) {
    if (!app || field<Object>(app, 0x1370) || field<Word>(app, 0x1374)) return nullptr;
    const float scale = field<float>(app, 0x698);
    const float maxWidth = float(field<int>(app, 0x524)) * 0.92f;
    const float maxHeight = float(field<int>(app, 0x528)) * 0.92f;
    if (!(scale > 0) || maxWidth <= 0 || maxHeight <= 0) return nullptr;
    float width = designWidth * scale < maxWidth ? designWidth * scale : maxWidth;
    float height = designHeight * scale < maxHeight ? designHeight * scale : maxHeight;
    if (keepAspect) {
        const float uniformScale = width / designWidth < height / designHeight
            ? width / designWidth : height / designHeight;
        width = designWidth * uniformScale;
        height = designHeight * uniformScale;
    }
    Object dialog = native<Object>(base, 0x14c1a7d, 0x170U);
    if (!dialog) return nullptr;
    native<void>(base, 0x7f1b6c, dialog);
    field<unsigned char>(dialog, 0xcd) = 1;
    field<float>(dialog, 0xd0) = 0.5f;
    const float y = (field<int>(app, 0x528) - height - height * gutter / designHeight) * 0.5f;
    widgetCall(dialog, 0xac, int((field<int>(app, 0x524) - width) * 0.5f),
               y > 0 ? int(y) : 0, int(width), int(height));
    Object manager = field<Object>(app, 0x2c0);
    widgetCall(manager, 0x10, dialog);
    widgetCall(manager, 0x38, dialog);
    native<void>(base, 0x1317158, manager, dialog);
    widgetCall(manager, 0x2c, dialog);
    return dialog;
}

static void detachGameDialog(Word base, Object app, Object dialog) {
    Object manager = field<Object>(app, 0x2c0);
    widgetCall(manager, 0x14, dialog);
    native<void>(base, 0x1317170, manager, dialog);
    widgetCall(app, 0xa8, dialog);
}

static Object createDialogButton(Word base, Object dialog, const char32_t* label,
                                 void (*callback)(Word), Word action, bool highlighted) {
    const char32_t* text = nullptr;
    makeText(base, text, label);
    Word delegate[6] = {base + 0x1787408, reinterpret_cast<Word>(callback),
                        0, action, 1, base + 0x2cc954};
    Object button = native<Object>(base, 0x7f25ec, dialog, &text, delegate, highlighted ? 0 : 1);
    freeText(base, text);
    return button;
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
        detachGameDialog(base, app, menu.dialog);
        for (Word i = 0; i < sizeof(menuGroups) / sizeof(menuGroups[0]); ++i) {
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

static void resolveMenuSkin(Word base, ButtonSkin& skin, const char* key, Word drawMode) {
    struct ImageDescriptor { Word reserved[3]; const char* key; WeakRef ref; };
    ImageDescriptor descriptor;
    descriptor.key = key;
    descriptor.ref = {0, 0};
    native<void>(base, 0x7e8a28, &skin, &descriptor, drawMode);
    native<void>(base, 0x1d9bb4, &descriptor.ref, 0U, 0U, 0U);
}

static void loadMenuArt(Word base, Object app) {
    static constexpr char keys[][50] = {
        "IMAGE_UI_AWARDDIALOG_RIBBON",
        "IMAGE_UI_DIALOG_ASSET_CLOSE_BTN", "IMAGE_UI_DIALOG_ASSET_CLOSE_DOWN",
        "IMAGE_UI_GENERIC_TAB_N", "IMAGE_UI_GENERIC_TAB_S",
        "IMAGE_UI_GAME_INTRO_GAME_INTRO_DIALOG",
        "IMAGE_UI_STAR_REWARD_STAR_REWARD_152X148", "IMAGE_UI_STAR_REWARD_STAR_REWARD_141X137",
        "IMAGE_UI_AWARDDIALOG_RATING_GREY_BTN", "IMAGE_UI_AWARDDIALOG_RATING_GREY_BTN_DOWN",
        "IMAGE_UI_GENERIC_GREENBUTTON", "IMAGE_UI_GENERIC_GREENBUTTON_DOWN",
#ifdef ASTER_SOCIAL_ART
        "IMAGE_ASTER_SOCIAL_SCORE_PAPER", "IMAGE_ASTER_SOCIAL_TAB_NORMAL",
        "IMAGE_ASTER_SOCIAL_TAB_SELECTED", "IMAGE_ASTER_SOCIAL_TAB_LOCKED",
        "IMAGE_ASTER_SOCIAL_LINE_LEFT", "IMAGE_ASTER_SOCIAL_LINE_RIGHT",
        "IMAGE_ASTER_SOCIAL_FRIEND_ROW", "IMAGE_ASTER_SOCIAL_FRIEND_AVATAR", "IMAGE_ASTER_SOCIAL_FRIEND_HOVER",
#endif
    };
    if (!field<Object>(reinterpret_cast<Object>(base), 0x183607c)) return;
    auto resolve = [&](Word i) {
        // The stock button-skin factory resolves the image by name. Footer
        // buttons use the same fixed corners and resizable middle as Pause.
        const Word drawMode = i == ViewButton || i == ViewButtonPressed ? 3U : 2U;
        resolveMenuSkin(base, menuArt[i], keys[i], drawMode);
    };
#ifdef ASTER_SOCIAL_ART
    changeMenuGroup(base, app, 2, true);
    heldMenuGroups |= 1U << 2;
#endif
    for (Word i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i) resolve(i);
#ifdef ASTER_SOCIAL_ART
    for (Word i = 0; i < friendAvatarCount; ++i) {
        resolveMenuSkin(base, menuArt[FriendPortrait + i], friendAvatarKeys[i], 2U);
        resolveMenuSkin(base, menuArt[CommunityPortrait + i], communityAvatarKeys[i], 2U);
    }
#endif
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
    Object button = createDialogButton(base, menu.dialog, label, queueMenuAction, action, highlighted);
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

static Word earnedStars(Word base, Object profile, const char* const* alias, Word count) {
    Word mask = 0;
    for (Word i = 0; i < count; ++i) {
        if (native<bool>(base, 0x708f8c, profile, alias, i)) mask |= 1U << i;
    }
    return mask;
}

static bool starChallengesUnlocked(Word base, const AdventureRecords::LevelInfo& level, Word* earned = nullptr) {
    Object store = ownerStore(base);
    Object profile = store ? native<Object>(base, 0x7a98dc, store) : nullptr;
    if (!profile) return false;
    char allocator = 0;
    const char* alias = nullptr;
    native<void>(base, 0x14ed0e1, &alias, level.alias, &allocator);
    bool cleared = native<bool>(base, 0x708190, profile, &alias);
    if (earned) *earned = earnedStars(base, profile, &alias, level.stars);
    releaseString(base, alias);
    if (cleared || level.alwaysAvailable) return true;

    for (const auto& unlock : level.unlocks) {
        if (!unlock[0]) break;
        native<void>(base, 0x14ed0e1, &alias, unlock, &allocator);
        cleared = native<bool>(base, 0x708190, profile, &alias);
        releaseString(base, alias);
        if (cleared) return true;
    }
    return false;
}

static void addScoreRow(Word base, Word rank, Word action, const char32_t* name, Word elapsedMs,
                        Word friendId = 0, Word avatar = unknownFriendAvatar) {
    if (rank <= menu.page * scoresPerPage || menu.scoreRowCount == scoresPerPage) return;
    if (!menu.selectedScore) menu.selectedScore = action;
    const auto bounds = scoreRowBounds(menu.scoreRowCount);
    auto& row = menu.scoreRows[menu.scoreRowCount++];
    row.selected = menu.selectedScore == action;
    row.friendId = friendId;
    row.avatar = avatar;
    row.widget = addMenuButton(base, U"", action, bounds.x, bounds.y, bounds.width, bounds.height);
    char32_t label[64];
    auto* end = append(number(label, rank), U"  ");
    Word length = 0;
    while (length < 7 && name[length]) ++length;
    end = append(end, name, length);
    if (name[length]) append(end, U"…");
    makeText(base, row.player, label);
    formatTime(label, elapsedMs);
    makeText(base, row.time, label);
}

static bool showMenu(Word base) {
    Object app = gameApp(base);
    if (!app || !menu.level) return false;
    const auto& level = *menu.level;
    if (menu.dialog) {
        if (!menuMounted(app)) return false;
        native<void>(base, 0x9c0818, field<Object>(menu.dialog, 0xa8));
        menu.buttonCount = 0;
        releaseHeadings(base);
    } else {
        menu.dialog = openGameDialog(base, app, menuWidth, menuWidgetHeight, menuTopGutter);
        if (!menu.dialog) return false;
        loadMenuArt(base, app);
    }

    makeText(base, menu.headings[0], AdventureRecords::levelTexts + level.title);
    makeText(base, menu.headings[1], U"过关条件");
    const char32_t* goals = AdventureRecords::levelTexts + level.goals[menu.stars];
    if (!menu.unlocked) {
        goals = level.unlocks[0][0] ? U"完成本关主线，或领取\n本世界的三星罐头"
                                   : U"完成本关主线解锁星级挑战";
    }
    makeText(base, menu.headings[2], goals);
    makeText(base, menu.headings[3], U"我的成绩");
    makeText(base, menu.headings[5], U"好友成绩");
    char32_t label[64];
    formatTime(label, menu.bestTimes[menu.stars]);
    makeText(base, menu.headings[6], label);

    Word rank = 0;
    Word selfTime = menu.bestTimes[menu.stars];
    for (Word i = 0; i < menu.scoreCount; ++i) {
        const auto& score = menu.scores[i];
        if (score.stars != menu.stars) continue;
        if (selfTime && selfTime < score.elapsedMs) {
            addScoreRow(base, ++rank, chooseSelf, selfName, selfTime);
            selfTime = 0;
        }
        addScoreRow(base, ++rank, chooseFriend + i, score.name, score.elapsedMs, score.id, score.avatar);
    }
    if (selfTime) addScoreRow(base, ++rank, chooseSelf, selfName, selfTime);
    if (!rank) {
        makeText(base, menu.headings[4], U"暂无好友成绩");
    } else if (rank > scoresPerPage) {
        if (menu.page) addMenuButton(base, U"上一页", PrevPage, 17, 219, 92, 32);
        if ((menu.page + 1) * scoresPerPage < rank) {
            addMenuButton(base, U"下一页", NextPage, 144, 219, 92, 32);
        }
    }

    static constexpr char32_t tabs[][4] = {U"无星", U"第一星", U"第二星", U"第三星"};
    for (Word i = level.stars == 1 ? 1 : 0; i <= level.stars; ++i) {
        const bool selected = i == menu.stars;
        const bool locked = i && !menu.unlocked;
        MenuArt skin = locked ? (selected ? LockedTabPressed : LockedTab)
                              : (selected ? ActiveTab : InactiveTab);
        MenuArt pressed = locked ? LockedTabPressed : skin;
        bool pointed = skin == ActiveTab;
#ifdef ASTER_SOCIAL_ART
        if (menuArt[SocialTab].image && menuArt[SocialTabSelected].image && menuArt[SocialTabLocked].image) {
            skin = locked ? SocialTabLocked : selected ? SocialTabSelected : SocialTab;
            pressed = skin;
            pointed = skin == SocialTabSelected;
        }
#endif
        // The green tab extends below its shoulders into the conditions card.
        constexpr int tabHeight = 46;
        const int height = pointed ? 58 : tabHeight;
        const int x = level.stars == 1 ? 448 : 286 + int(i) * 105;
        addMenuButton(base, tabs[i], SelectStars + i, x, 147, 100, height,
                      selected, skin, pressed, tabHeight);
    }
    addMenuButton(base, menuArt[Close].image ? U"" : U"×", Dismiss, 669, -35, 45, 36,
                  false, Close, ClosePressed);
    if (level.formation && menu.selectedScore) {
        addMenuButton(base, U"查看阵型", WatchFormation, (scoresPanelWidth - footerButtonWidth) / 2, 317,
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
#ifdef ASTER_SOCIAL_ART
    const bool hasScorePaper = menuArt[ScorePaper].image;
    if (hasScorePaper) {
        drawImage(ScorePaper, {22, 245, 209, 90});
    } else
#endif
        drawImage(GoalsCard, personalScoreCard);
    constexpr MenuRect ribbon{275, -14, 446, 98};
    drawImage(Ribbon, ribbon);
    // The atlas star is tilted 18 degrees clockwise. Correct the center star
    // and fan the outer stars out by 18 degrees on either side of it.
    constexpr float cosines[] = {0.809017f, 0.951057f, 1.0f};
    constexpr float sines[] = {-0.587785f, -0.309017f, 0.0f};
    const bool single = menu.level->stars == 1;
    for (Word i = single ? 1 : 0; i < (single ? 2U : 3U); ++i) {
        const MenuArt star = (menu.earnedStars & (1U << (single ? 0 : i))) ? StarOn : StarOff;
        const int centerX = ribbon.x + ribbon.width / 2 + (int(i) - 1) * 94;
        const MenuRect bounds{centerX - 29, i == 1 ? -5 : 15, 58, 55};
        const Object image = menuArt[star].image;
        if (!image) continue;
        const MenuRect box = fit(bounds);
        const float scaleX = float(box.width) / field<int>(image, 0x28);
        const float scaleY = float(box.height) / field<int>(image, 0x2c);
        const float c = cosines[i], s = sines[i];
        // DrawImageMatrix starts at the image's top-left. Preserve the
        // midpoint of the scaled bounds while rotating the quad around it.
        const float halfWidth = box.width * 0.5f;
        const float halfHeight = box.height * 0.5f;
        const float matrix[] = {
            c * scaleX, -s * scaleY, box.x + halfWidth - c * halfWidth + s * halfHeight,
            s * scaleX,  c * scaleY, box.y + halfHeight - s * halfWidth - c * halfHeight,
            0,           0,          1,
        };
        native<void>(base, 0x116a268, graphics, image, matrix);
    }
#ifdef ASTER_SOCIAL_ART
    drawImage(GoalLineLeft, {286, 109, 138, 21});
    drawImage(GoalLineRight, {574, 109, 138, 21});
#endif

    for (Word i = 0; i < menu.scoreRowCount; ++i) {
        const auto& row = menu.scoreRows[i];
        const auto box = scoreRowBounds(i);
        const bool pressed = row.widget && field<unsigned char>(row.widget, 0x1e4);
        native<void>(base, 0x1166c30, graphics, &white);
#ifdef ASTER_SOCIAL_ART
        if (menuArt[FriendRow].image) {
            drawImage(FriendRow, box);
            drawImage(FriendAvatar, {box.x + 19, box.y + 3, 35, 35});
            if (row.friendId) {
                const auto portrait = row.avatar < friendAvatarCount && menuArt[CommunityPortrait + row.avatar].image
                    ? MenuArt(CommunityPortrait + row.avatar)
                    : MenuArt(FriendPortrait + friendAvatarIndex(social.id.owner, row.friendId));
                drawImage(portrait, {box.x + 21, box.y + 5, 31, 31});
            }
            if (row.selected || pressed) drawImage(FriendHover, box);
            drawText(row.player, {box.x + 56, box.y + 1, box.width - 61, 19}, white);
            drawText(row.time, {box.x + 56, box.y + 20, box.width - 61, 19}, ink);
            continue;
        }
#endif
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
#ifdef ASTER_SOCIAL_ART
        if (hasScorePaper && i == 3) continue;
        if (hasScorePaper && i == 6) {
            drawText(menu.headings[i], {27, 276, 198, 31}, scoreInk);
            continue;
        }
        if (i == 1 && menuArt[GoalLineLeft].image && menuArt[GoalLineRight].image) {
            constexpr MenuColor heading{50, 80, 18, 255};
            drawText(menu.headings[i], boxes[i], heading);
            continue;
        }
#endif
        drawText(menu.headings[i], boxes[i], i == 6 ? scoreInk : i == 2 || i == 3 ? ink : white);
    }
    body = previousBody;
    bodyRect = previousRect;
    bodyColor = previousBodyColor;
    native<void>(base, 0x1166c30, graphics, &previousColor);
}
}

extern "C" void asterAdventureDrawMenuPanel(Word base, Object dialog, Object graphics, const MenuRect* bounds) {
    if (drawBorrowDialogPanel(base, dialog, graphics, bounds)) return;
    if (userDrawsOwnFrame(dialog)) return;
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
    } else {
        drawBorrowDialogContents(base, dialog, graphics);
        drawUserDialog(base, dialog, graphics);
    }
}

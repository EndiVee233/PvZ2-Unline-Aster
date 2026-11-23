#pragma once

namespace {
constexpr Word borrowRequest = 6;
constexpr Word borrowPageSize = 6;
constexpr Word maxBorrowOffers = 3 * maxGiftFriends;
constexpr Word borrowEntry = 1;
constexpr Word borrowClose = 2;
constexpr Word borrowClear = 3;
constexpr Word borrowPrevious = 4;
constexpr Word borrowNext = 5;
constexpr Word borrowPick = 16;

struct BorrowOffer {
    Word id, avatar;
    char32_t friendName[40];
    AdventureRecords::Card card;
};

enum BorrowArt : Word {
    BorrowTab, BorrowClose, BorrowCloseDown, BorrowTopper, BorrowRow, BorrowBorder,
    BorrowAvatarFrame, BorrowLeaves, BorrowPacket, BorrowPacketTier2, BorrowPacketTier3,
    BorrowPacketTier4, BorrowCancel, BorrowCancelDown, BorrowPortrait,
    BorrowCommunityPortrait = BorrowPortrait + friendAvatarCount,
    BorrowArtCount = BorrowCommunityPortrait + friendAvatarCount
};

struct BorrowRowView {
    Object button, packet;
    int packetX, packetY;
    const char32_t* name;
    const char32_t* details;
    const char32_t* cost;
};

struct BorrowDialogControl {
    Object widget, image;
    MenuRect bounds;
};

struct BorrowChooser {
    Object app, board, chooser, entry, dialog;
    Object cancelButton;
    Object entryArt, entryPressed;
    ButtonSkin art[BorrowArtCount];
    BorrowRowView rows[borrowPageSize];
    Word rowCount;
    BorrowDialogControl controls[borrowPageSize + 4];
    Word controlCount;
    SocialMessage request;
    Word action, count, selected, page, expires, nextPoll;
    bool ready, heldArt, hiding;
    Word motion, motionSample;
    float reveal, foreground;
    MenuRect entryBox;
    BorrowOffer offers[maxBorrowOffers];
};

static BorrowChooser borrow;
static const char32_t* borrowHeading;
static const char32_t* borrowEmpty;
static const char32_t* borrowLoading;

static void queueBorrowAction(Word action) {
    if (!borrow.hiding && !borrow.action) borrow.action = action;
}

static void queueBorrowEntry(SunButtonListener*, Word action) {
    queueBorrowAction(action);
}

static bool borrowMounted() {
    return borrow.app && borrow.dialog &&
        field<Object>(field<Object>(borrow.app, 0x2c0), 0x88) == borrow.dialog;
}

static void releaseBorrowRows(Word base) {
    for (Word i = 0; i < borrow.rowCount; ++i) {
        auto& row = borrow.rows[i];
        freeText(base, row.name);
        freeText(base, row.details);
        freeText(base, row.cost);
    }
    borrow.rowCount = 0;
}

static void closeBorrowDialog(Word base) {
    if (borrowMounted()) detachGameDialog(base, borrow.app, borrow.dialog);
    borrow.dialog = nullptr;
    borrow.cancelButton = nullptr;
    borrow.action = 0;
    borrow.controlCount = 0;
    releaseBorrowRows(base);
    freeText(base, borrowHeading);
    freeText(base, borrowEmpty);
    freeText(base, borrowLoading);
}

static void removeBorrowEntry(Word base) {
    closeBorrowDialog(base);
    if (borrow.entry) {
        widgetCall(field<Object>(borrow.app, 0x2c0), 0x14, borrow.entry);
        widgetCall(borrow.app, 0xa8, borrow.entry);
        borrow.entry = nullptr;
    }
    borrow.entryArt = borrow.entryPressed = nullptr;
    borrow.chooser = nullptr;
    borrow.hiding = false;
    borrow.motion = borrow.motionSample = 0;
    borrow.reveal = borrow.foreground = 0;
    if (borrow.heldArt) {
        changeMenuGroup(base, borrow.app, 2, false);
        borrow.heldArt = false;
    }
}

static void resetBorrowChoice(Word base) {
    removeBorrowEntry(base);
    borrow.app = nullptr;
    borrow.board = nullptr;
    borrow.request.token = 0;
    borrow.count = borrow.selected = borrow.page = 0;
    borrow.ready = false;
}

static Object borrowPlantType(Word base, const char* alias) {
    Object names = field<Object>(reinterpret_cast<Object>(base), 0x183049c);
    Object registry = native<Object>(base, 0x11d74b4);
    if (!names || !registry) return nullptr;
    alignas(8) WeakRef handle{0, 0};
    const char* text = nullptr;
    char allocator = 0;
    native<void>(base, 0x14ed0e1, &text, alias, &allocator);
    native<void>(base, 0x20cea8, &handle, names, &text);
    releaseString(base, text);
    Object type = native<Object>(base, 0x1da034, registry, &handle);
    native<void>(base, 0x1d9bb4, &handle, 0U, 0U, 0U);
    return type;
}

static void borrowPlantName(Word base, char32_t* text, const char* alias) {
    char32_t key[35];
    auto* current = key;
    *current++ = U'[';
    for (const char* ch = alias; *ch; ++ch) {
        *current++ = *ch >= 'a' && *ch <= 'z' ? *ch - 'a' + U'A' : *ch;
    }
    *current++ = U']';
    *current = 0;
    const char32_t* raw = nullptr;
    const char32_t* translated = nullptr;
    makeText(base, raw, key);
    native<void>(base, 0xd07bb4, &translated, &raw);
    if (translated && translated[0] && translated[0] != U'[') {
        append(text, translated, 12);
    } else {
        while ((*text++ = *alias++)) {}
    }
    freeText(base, translated);
    freeText(base, raw);
}

constexpr int borrowWidth = 670;
constexpr int borrowHeight = 490;
constexpr int borrowTop = 59;
constexpr int borrowBottom = 444;
constexpr MenuRect borrowCancelBounds{272, 392, 126, 42};

static MenuRect fitBorrowDialog(MenuRect rect) {
    const int width = field<int>(borrow.dialog, 0x30);
    const int height = field<int>(borrow.dialog, 0x34);
    return {rect.x * width / borrowWidth, rect.y * height / borrowHeight,
            rect.width * width / borrowWidth, rect.height * height / borrowHeight};
}

struct BorrowImagePlacement {
    float x, y, scale;
};

static BorrowImagePlacement fitBorrowImage(Object image, MenuRect box) {
    const float width = float(field<int>(image, 0x28));
    const float height = float(field<int>(image, 0x2c));
    if (width <= 0 || height <= 0) return {0, 0, 0};
    const float scaleX = float(box.width) / width;
    const float scaleY = float(box.height) / height;
    const float scale = scaleX < scaleY ? scaleX : scaleY;
    return {box.x + (box.width - width * scale) * 0.5f,
            box.y + (box.height - height * scale) * 0.5f, scale};
}

static MenuRect borrowRowBounds(Word index) {
    return {23 + int(index % 2) * 316, 87 + int(index / 2) * 85, 304, 76};
}

static Object borrowDialogButton(Word base, const char32_t* label, Word action, MenuRect rect,
                                 const ButtonSkin* art = nullptr, const ButtonSkin* down = nullptr) {
    Object button = createDialogButton(base, borrow.dialog, label, queueBorrowAction, action, false);
    if (!button) return nullptr;
    if (art && art->image) {
        native<void>(base, 0x7e90dc, button, art, down && down->image ? down : art);
        if (art->drawMode == 2) field<Word>(button, 0x13c) = 1;
    } else if (action >= borrowPick) {
        field<Word>(button, 0x13c) = 0;
    }
    borrow.controls[borrow.controlCount++] = {
        button, art && art->drawMode == 2 ? art->image : nullptr, rect
    };
    return button;
}

static void placeBorrowDialogControls() {
    // GameDialog lays out its child buttons as a footer when that list changes.
    for (Word i = 0; i < borrow.controlCount; ++i) {
        const auto& control = borrow.controls[i];
        auto box = fitBorrowDialog(control.bounds);
        if (control.image) {
            const auto placement = fitBorrowImage(control.image, box);
            box = {int(placement.x), int(placement.y),
                   int(field<int>(control.image, 0x28) * placement.scale + 0.5f),
                   int(field<int>(control.image, 0x2c) * placement.scale + 0.5f)};
        }
        widgetCall(control.widget, 0xac, box.x, box.y, box.width, box.height);
        if (control.widget == borrow.cancelButton) {
            field<MenuRect>(control.widget, 0x1c4) = {0, 0, box.width, box.height};
        }
    }
}

static void loadBorrowDialogArt(Word base) {
    static constexpr char keys[][50] = {
        "IMAGE_ASTER_SOCIAL_TAB_SELECTED", "IMAGE_UI_DIALOG_ASSET_CLOSE_BTN",
        "IMAGE_UI_DIALOG_ASSET_CLOSE_DOWN", "IMAGE_ASTER_SOCIAL_BORROW_TOPPER",
        "IMAGE_ASTER_SOCIAL_BORROW_ROW", "IMAGE_ASTER_SOCIAL_FRIEND_HOVER",
        "IMAGE_ASTER_SOCIAL_FRIEND_AVATAR", "IMAGE_UI_DIALOG_ASSET_CORNER_LEAVES",
        "IMAGE_UI_PACKETS_READY", "IMAGE_UI_PACKETS_FRAME_2",
        "IMAGE_UI_PACKETS_FRAME_3", "IMAGE_UI_PACKETS_FRAME_4",
        "IMAGE_UI_GENERIC_BROWNBUTTON", "IMAGE_UI_GENERIC_BROWNBUTTON_DOWN",
    };
    for (Word i = 0; i < BorrowPortrait; ++i) {
        resolveMenuSkin(base, borrow.art[i], keys[i], i >= BorrowCancel ? 3U : 2U);
    }
    for (Word i = 0; i < friendAvatarCount; ++i) {
        resolveMenuSkin(base, borrow.art[BorrowPortrait + i], friendAvatarKeys[i], 2U);
        resolveMenuSkin(base, borrow.art[BorrowCommunityPortrait + i], communityAvatarKeys[i], 2U);
    }
    if (!borrow.art[BorrowTab].image) {
        resolveMenuSkin(base, borrow.art[BorrowTab], "IMAGE_UI_GENERIC_TAB_S", 2U);
        resolveMenuSkin(base, borrow.art[BorrowRow], "IMAGE_UI_GAME_INTRO_GAME_INTRO_DIALOG", 2U);
    }
}

struct PacketAnchor {
    char key[49];
    int x, y;
};

struct PlantPacketName { char alias[32], sprite[49]; };
static constexpr PlantPacketName plantPackets[] = {
#include "adventure_user_plants.inc"
};
static constexpr PacketAnchor packetAnchors[] = {
#include "adventure_packet_anchors.inc"
};

static const PacketAnchor* packetAnchor(const char* key) {
    for (const auto& anchor : packetAnchors) {
        const char* source = anchor.key;
        const char* query = key;
        while (*source && *source == *query) {
            ++source;
            ++query;
        }
        if (*source == *query) return &anchor;
    }
    return nullptr;
}

static void loadBorrowPacketArt(Word base, BorrowRowView& row, const char* alias) {
    char key[66];
    const char* sprite = nullptr;
    for (const auto& plant : plantPackets) {
        const char* source = plant.alias;
        const char* query = alias;
        while (*source && *source == *query) { ++source; ++query; }
        if (*source == *query) {
            sprite = plant.sprite;
            break;
        }
    }
    char* output = key;
    for (char ch : "IMAGE_UI_PACKETS_") if (ch) *output++ = ch;
    for (const char* ch = sprite ? sprite : alias; *ch; ++ch) {
        *output++ = *ch >= 'a' && *ch <= 'z' ? *ch - 'a' + 'A' : *ch;
    }
    *output = 0;
    ButtonSkin packet;
    resolveMenuSkin(base, packet, key, 2U);
    if (!packet.image) {
        // Some multiword plant aliases use the compact spelling in the atlas.
        output = key + 17;
        for (const char* ch = alias; *ch; ++ch) {
            if (*ch != '_') *output++ = *ch >= 'a' && *ch <= 'z' ? *ch - 'a' + 'A' : *ch;
        }
        *output = 0;
        resolveMenuSkin(base, packet, key, 2U);
    }
    const auto* anchor = packetAnchor(key + 17);
    row.packet = packet.image;
    row.packetX = anchor ? anchor->x : 10;
    row.packetY = anchor ? anchor->y : 10;
}

static void drawSocialSeedPacket(Word base, Object graphics, const BorrowRowView& row,
                                 MenuRect bounds, Object background, Object border, Word tier,
                                 bool centerArtwork = false) {
    const auto draw = [&](Object image, BorrowImagePlacement placement) {
        if (!image || placement.scale <= 0.0f) return;
        const float matrix[] = {placement.scale, 0, placement.x, 0, placement.scale,
                                placement.y, 0, 0, 1};
        native<void>(base, 0x116a268, graphics, image, matrix);
    };
    const auto* anchor = packetAnchor("READY");
    if (!background || !anchor) {
        if (row.packet) draw(row.packet, fitBorrowImage(row.packet, bounds));
        return;
    }
    const auto placement = fitBorrowImage(background, bounds);
    const float x = placement.x - anchor->x * placement.scale;
    const float y = placement.y - anchor->y * placement.scale;
    draw(background, placement);
    const auto clip = field<MenuRect>(graphics, 0x20);
    native<void>(base, 0x116b2c4, graphics, &bounds);
    if (centerArtwork && row.packet) {
        const int width = int(field<int>(background, 0x28) * placement.scale);
        const int height = int(field<int>(background, 0x2c) * placement.scale);
        const int insetX = width / 9, insetY = height / 9;
        const MenuRect inner{int(placement.x) + insetX, int(placement.y) + insetY,
                             width - 2 * insetX, height - 2 * insetY};
        draw(row.packet, fitBorrowImage(row.packet, inner));
    } else {
        draw(row.packet, {x + row.packetX * placement.scale, y + row.packetY * placement.scale, placement.scale});
    }
    field<MenuRect>(graphics, 0x20) = clip;
    if (border && tier >= 2 && tier <= 4) {
        static constexpr char frames[][8] = {"FRAME_2", "FRAME_3", "FRAME_4"};
        const auto* frame = packetAnchor(frames[tier - 2]);
        if (frame) draw(border, {x + frame->x * placement.scale, y + frame->y * placement.scale, placement.scale});
    }
}

static void refreshBorrowOffers(Word base) {
    if (!borrowMounted()) return;
    releaseBorrowRows(base);
    Object controls = field<Object>(borrow.dialog, 0xa8);
    if (controls) native<void>(base, 0x9c0818, controls);
    borrow.controlCount = 0;
    borrowDialogButton(base, U"", borrowClose, {598, 12, 51, 48},
                       borrow.art + BorrowClose, borrow.art + BorrowCloseDown);
    const Word first = borrow.page * borrowPageSize;
    for (Word i = 0; i < borrowPageSize && first + i < borrow.count; ++i) {
        const auto& offer = borrow.offers[first + i];
        auto& row = borrow.rows[borrow.rowCount++];
        row.button = borrowDialogButton(base, U"", borrowPick + first + i, borrowRowBounds(i));
        loadBorrowPacketArt(base, row, offer.card.type);
        char32_t label[40];
        auto* end = append(label, offer.friendName, 10);
        if (offer.friendName[10]) append(end, U"…");
        makeText(base, row.name, label);
        borrowPlantName(base, label, offer.card.type);
        makeText(base, row.details, label);
        if (const auto plant = borrowPlantType(base, offer.card.type)) {
            // The seed packet reads the plant's normal price through this method.
            const auto price = field<Word>(field<Object>(plant, 0), 0x2c);
            const int sun = reinterpret_cast<int(*)(Object, int)>(price)(plant, -2);
            if (sun >= 0) {
                number(label, Word(sun));
                makeText(base, row.cost, label);
            }
        }
    }
    if (borrow.page) borrowDialogButton(base, U"上一页", borrowPrevious, {142, 396, 108, 39});
    if (first + borrowPageSize < borrow.count)
        borrowDialogButton(base, U"下一页", borrowNext, {419, 396, 108, 39});
    borrow.cancelButton = borrow.selected
        ? borrowDialogButton(base, U"取消借用", borrowClear, borrowCancelBounds,
                             borrow.art + BorrowCancel, borrow.art + BorrowCancelDown) : nullptr;
    if (borrow.cancelButton) {
        const auto family = field<Object>(reinterpret_cast<Object>(base), 0x1842b50);
        const auto font = family ? field<Object>(family, 0x24) : nullptr;
        if (font) {
            int textWidth;
            const auto& label = field<const char32_t*>(borrow.cancelButton, 0xa4);
            const auto caption = fitBorrowDialog({0, 0, 80, 1});
            // Use the stock dialog button's font fitting routine and clone the
            // resulting font into this button only.
            const auto fitted = native<Object>(base, 0x13aee38, font, &label, caption.width, &textWidth);
            widgetCall(borrow.cancelButton, 0x184, fitted);
        }
    }
    placeBorrowDialogControls();
}

static bool drawBorrowDialogPanel(Word base, Object dialog, Object graphics, const MenuRect* bounds) {
    const bool friends = friendBookUsesBorrowFrame(dialog);
    if (dialog != borrow.dialog && !friends) return false;
    const int top = bounds->height * borrowTop / borrowHeight;
    const int bottom = friends ? 461 : borrowBottom;
    const MenuRect frame{bounds->x, bounds->y + top, bounds->width,
                         bounds->height * (bottom - borrowTop) / borrowHeight};
    if (friends) drawFriendBookBackdrop(base, dialog, graphics);
    native<void>(base, 0x7f3470, dialog, graphics, &frame);
    return true;
}

static void drawBorrowDialogContents(Word base, Object dialog, Object graphics) {
    if (!dialog || dialog != borrow.dialog) return;
    placeBorrowDialogControls();
    auto& body = field<const char32_t*>(dialog, 0xb4);
    auto& bodyRect = field<MenuRect>(dialog, 0xe4);
    auto& bodyColor = field<MenuColor>(dialog, 0x160);
    auto& bodyAlign = field<Word>(dialog, 0x12c);
    const auto previousBody = body;
    const auto previousRect = bodyRect;
    const auto previousInk = bodyColor;
    const auto previousAlign = bodyAlign;
    const auto previousColor = field<MenuColor>(graphics, 0x4c);
    const auto previousTint = field<unsigned char>(graphics, 0x64);
    constexpr MenuColor white{255, 250, 229, 255};
    constexpr MenuColor ink{67, 47, 21, 255};
    auto drawAt = [&](Object bitmap, const BorrowImagePlacement& placement, bool mirror = false) {
        if (placement.scale <= 0) return;
        const float x = placement.x + (mirror ? field<int>(bitmap, 0x28) * placement.scale : 0);
        const float matrix[] = {mirror ? -placement.scale : placement.scale, 0, x,
                                0, placement.scale, placement.y, 0, 0, 1};
        native<void>(base, 0x116a268, graphics, bitmap, matrix);
    };
    auto draw = [&](Object bitmap, MenuRect rect, bool mirror = false) {
        if (!bitmap) return;
        drawAt(bitmap, fitBorrowImage(bitmap, fitBorrowDialog(rect)), mirror);
    };
    auto drawText = [&](const char32_t* text, MenuRect rect, const MenuColor& color) {
        body = text;
        bodyRect = fitBorrowDialog(rect);
        bodyColor = color;
        native<void>(base, 0x7f17d4, dialog, graphics);
    };
    auto fill = [&](MenuRect rect, const MenuColor& color) {
        const auto box = fitBorrowDialog(rect);
        native<void>(base, 0x1166c30, graphics, &color);
        native<void>(base, 0x1167010, graphics, box.x, box.y, box.width, box.height);
    };
    native<void>(base, 0x1166e74, graphics, false);
    // Shade the panel itself, with the gradient stopping inside its frame.
    for (int i = 0; i < 17; ++i) {
        fill({10, 353 + i * 5, 650, 5}, {42, 27, 16, i * i * 58 / 256});
    }
    draw(borrow.art[BorrowTopper].image, {18, 21, 634, 46});
    draw(borrow.art[BorrowTab].image, {226, 0, 218, 76});
    const auto leaves = borrow.art[BorrowLeaves].image;
    draw(leaves, {7, 391, 158, 84});
    draw(leaves, {505, 391, 158, 84}, true);
    // GameDialog's text renderer expects an engine string, just like the level menu.
    drawText(borrowHeading, {243, 13, 184, 40}, white);
    if (!borrow.rowCount) drawText(borrow.ready ? borrowEmpty : borrowLoading, {110, 184, 450, 58}, white);
    for (Word i = 0; i < borrow.rowCount; ++i) {
        const auto& row = borrow.rows[i];
        const auto box = borrowRowBounds(i);
        const Word index = borrow.page * borrowPageSize + i;
        const Word tier = borrow.offers[index].card.level;
        const bool selected = borrow.selected == index + 1;
        const bool pressed = row.button && field<unsigned char>(row.button, 0x1e4);
        native<void>(base, 0x1166e74, graphics, false);
        draw(borrow.art[BorrowRow].image, box);
        draw(borrow.art[BorrowAvatarFrame].image, {box.x + 6, box.y + 6, 66, 66});
        const auto& offer = borrow.offers[index];
        const Word portrait = offer.avatar < friendAvatarCount && borrow.art[BorrowCommunityPortrait + offer.avatar].image
            ? BorrowCommunityPortrait + offer.avatar
            : BorrowPortrait + friendAvatarIndex(borrow.request.owner, offer.id);
        draw(borrow.art[portrait].image, {box.x + 10, box.y + 10, 58, 58});
        const MenuRect packetBounds{box.x + 210, box.y + 9, 87, 57};
        drawSocialSeedPacket(base, graphics, row, fitBorrowDialog(packetBounds),
                             borrow.art[BorrowPacket].image, borrow.art[BorrowPacket + tier - 1].image, tier);
        if (row.cost) {
            bodyAlign = 4;
            const MenuRect price{box.x + 224, box.y + 43, 69, 24};
            drawText(row.cost, {price.x + 1, price.y + 1, price.width, price.height}, {24, 22, 20, 255});
            drawText(row.cost, price, white);
            bodyAlign = previousAlign;
        }
        drawText(row.name, {box.x + 77, box.y + 1, 132, 34}, white);
        drawText(row.details, {box.x + 77, box.y + 40, 132, 29}, ink);
        if (selected || pressed) {
            fill({box.x + 4, box.y + 5, box.width - 8, box.height - 10}, {19, 26, 13, 98});
            native<void>(base, 0x1166e74, graphics, false);
            draw(borrow.art[BorrowBorder].image, {box.x - 5, box.y - 4, box.width + 10, box.height + 8});
        }
    }
    body = previousBody;
    bodyRect = previousRect;
    bodyColor = previousInk;
    native<void>(base, 0x1166c30, graphics, &previousColor);
    field<unsigned char>(graphics, 0x64) = previousTint;
}

static void requestBorrowOffers(Word base, Word clock) {
    borrow.request = {clock + ++sequence, owner(ownerStore(base)),
                      AdventureRecords::levelId(field<const char*>(borrow.board, 0xc4)), borrowRequest};
    borrow.nextPoll = clock;
    borrow.expires = clock + 300;
    borrow.ready = !writeBytes(base, &borrow.request, sizeof(borrow.request), dialogFile, dialogTemp);
}

static void pollBorrowOffers(Word base, Word clock) {
    if (borrow.ready || int(clock - borrow.nextPoll) < 0) return;
    borrow.nextPoll = clock + 5;
    int fd = native<int>(base, 0x148448, replyFile, 0, 0);
    if (fd < 0) {
        if (int(clock - borrow.expires) >= 0) {
            borrow.ready = true;
            refreshBorrowOffers(base);
        }
        return;
    }
    SocialMessage reply;
    Word count;
    char extra;
    const auto& request = borrow.request;
    const bool valid = readExact(base, fd, &reply, sizeof(reply)) && reply.token == request.token &&
        reply.owner == request.owner && reply.day == request.day && reply.kind == borrowRequest &&
        readExact(base, fd, &count, sizeof(count)) && count <= maxBorrowOffers &&
        readExact(base, fd, borrow.offers, count * sizeof(BorrowOffer)) &&
        native<int>(base, 0x148460, fd, &extra, 1) == 0;
    native<int>(base, 0x147b90, fd);
    native<int>(base, 0x148424, replyFile);
    if (!valid) return;
    borrow.count = 0;
    for (Word i = 0; i < count; ++i) {
        const auto& offer = borrow.offers[i];
        if (!offer.id || !validFriendAvatar(offer.avatar) || !offer.friendName[0] || offer.friendName[39] ||
            !offer.card.level || offer.card.level > 4 ||
            !AdventureRecords::validPlantType(offer.card.type) || !borrowPlantType(base, offer.card.type)) continue;
        auto& slot = borrow.offers[borrow.count++];
        if (&slot != &offer) {
            slot.id = offer.id;
            slot.avatar = offer.avatar;
            for (Word j = 0; j < 40; ++j) slot.friendName[j] = offer.friendName[j];
            for (Word j = 0; j < 32; ++j) slot.card.type[j] = offer.card.type[j];
            slot.card.level = offer.card.level;
        }
    }
    borrow.ready = true;
    refreshBorrowOffers(base);
}

constexpr Word borrowSlide = 24;
constexpr Word borrowFade = 15;
constexpr Word borrowMotionLength = borrowSlide + borrowFade;

static float easeBorrow(float t) {
    return t * t * (3.0f - 2.0f * t);
}

static void updateBorrowMotion(Word base, Object chooser) {
    const Word time = wallTime(base);
    const Word step = borrow.motionSample ? time - borrow.motionSample : 0;
    borrow.motionSample = time;
    if (borrow.hiding) {
        borrow.motion = step < borrow.motion ? borrow.motion - step : 0;
        if (!borrow.motion) {
            borrow.hiding = false;
            native<void>(base, 0x8f25cc, chooser);
        }
    } else if (field<Word>(chooser, 0xf8) == 1) {
        const Word remaining = borrowMotionLength - borrow.motion;
        borrow.motion += step < remaining ? step : remaining;
    } else {
        borrow.motion = 0;
    }
    const Word slide = borrow.motion < borrowSlide ? borrow.motion : borrowSlide;
    const Word fade = borrow.motion - slide;
    borrow.reveal = easeBorrow(float(slide) / borrowSlide);
    borrow.foreground = easeBorrow(float(fade) / borrowFade);
}

static MenuRect borrowEntryBounds(Object chooser, int originX, int screenWidth, float reveal) {
    const auto& panel = field<MenuRect>(chooser, 0x1a8);
    const int edge = panel.x + panel.width;
    const int width = panel.width * 17 / 100;
    const int height = width * 465 / 270;
    const int hidden = edge - width - 4;
    int open = edge - width / 5;
    if (open + originX + width > screenWidth) open = screenWidth - originX - width;
    if (open < hidden) open = hidden;
    return {hidden + int(float(open - hidden) * reveal), panel.y + panel.height * 54 / 100, width, height};
}

static void renderBorrowEntry(Word base, Object chooser, Object graphics, bool foreground) {
    if (chooser != borrow.chooser || !borrow.entry || borrow.reveal <= 0 ||
        field<unsigned char>(chooser, 0x14c)) return;
    if (foreground && borrow.foreground <= 0) return;
    Object art = borrow.entryPressed && field<unsigned char>(borrow.entry, 0x1e4)
        ? borrow.entryPressed : borrow.entryArt;
    if (!art) return;
    const auto box = borrowEntryBounds(chooser, int(field<float>(graphics, 8)),
                                       field<int>(borrow.app, 0x524), borrow.reveal);
    const auto savedClip = field<MenuRect>(graphics, 0x20);
    const auto savedColor = field<MenuColor>(graphics, 0x4c);
    const auto savedTint = field<unsigned char>(graphics, 0x64);
    if (foreground) {
        // Redraw only the overlap. The outer portion already came from the
        // pass behind the chooser, so its antialiased edge stays intact.
        const auto& panel = field<MenuRect>(chooser, 0x1a8);
        const int overlap = panel.x + panel.width - box.x;
        if (overlap <= 0) return;
        const MenuRect clip{box.x, box.y, overlap, box.height};
        native<void>(base, 0x116b2c4, graphics, &clip);
    }
    const float alpha = foreground ? borrow.foreground : 1.0f;
    const MenuColor tint{255, 255, 255, int(alpha * 255.0f + 0.5f)};
    native<void>(base, 0x1166e74, graphics, true);
    native<void>(base, 0x1166c30, graphics, &tint);
    native<void>(base, 0x11698b4, graphics, art, box.x, box.y, box.width, box.height);
    field<MenuRect>(graphics, 0x20) = savedClip;
    native<void>(base, 0x1166c30, graphics, &savedColor);
    field<unsigned char>(graphics, 0x64) = savedTint;
}

static void updateBorrowChooser(Word base) {
    Object app = gameApp(base);
    Object board = gameBoard(base);
    if (borrow.board != board || borrow.app != app) resetBorrowChoice(base);
    const Word phase = board ? field<Word>(board, 0xc0) : 0;
    if (social.phase != SocialPhase::Idle || !app || (phase != 3 && phase != 4) ||
        !socialContentEnabled(base) ||
        !AdventureRecords::formationSupported(field<const char*>(board, 0xc4)) || !ordinarySeedBank(base, board)) {
        if (borrow.entry || borrow.dialog) removeBorrowEntry(base);
        return;
    }
    Object chooser = formationHud(base, "UISeedChooser");
    if (!chooser || field<Word>(chooser, 0) != base + 0x17c0370 ||
        !native<bool>(base, 0x976720, chooser)) {
        if (borrow.entry || borrow.dialog) removeBorrowEntry(base);
        return;
    }

    if (!borrow.entry) {
        if (field<Object>(app, 0x1370) || field<Word>(app, 0x1374)) return;
        borrow.app = app;
        borrow.board = board;
        borrow.chooser = chooser;
        ButtonSkin normal, pressed;
#ifdef ASTER_SOCIAL_ART
        if (!borrow.heldArt) {
            changeMenuGroup(base, app, 2, true);
            borrow.heldArt = true;
        }
        resolveMenuSkin(base, normal, "IMAGE_ASTER_SOCIAL_BORROW_NORMAL", 2U);
        resolveMenuSkin(base, pressed, "IMAGE_ASTER_SOCIAL_BORROW_PRESSED", 2U);
#else
        resolveMenuSkin(base, normal, "IMAGE_UI_CHOOSER_BTN_BORROWP", 2U);
        resolveMenuSkin(base, pressed, "IMAGE_UI_CHOOSER_BTN_BORROWP_DOWN", 2U);
#endif
        borrow.entryArt = normal.image;
        borrow.entryPressed = pressed.image;
        static SunButtonListener listener;
        static SunButtonListener::Method methods[7];
        methods[0] = methods[1] = methods[3] = methods[4] = methods[5] = methods[6] = ignoreSunButton;
        methods[2] = queueBorrowEntry;
        listener.methods = methods;
        const MenuRect initial{0, 0, 1, 1};
        borrow.entry = createGameButton(base, U"", borrowEntry, initial, &listener,
                                        nullptr, nullptr, nullptr, false);
        if (!borrow.entry) return;
        field<Word>(borrow.entry, 0x13c) = 0;
        field<unsigned char>(borrow.entry, 0x38) = 0;
        borrow.entryBox = initial;
        Object manager = field<Object>(app, 0x2c0);
        widgetCall(manager, 0x10, borrow.entry);
        widgetCall(manager, 0x2c, borrow.entry);
    }

    updateBorrowMotion(base, chooser);
    if (borrow.hiding && borrow.dialog) closeBorrowDialog(base);
    MenuRect chooserBounds;
    native<void>(base, 0x97636c, &chooserBounds, chooser);
    auto box = borrowEntryBounds(chooser, chooserBounds.x, field<int>(app, 0x524), borrow.reveal);
    box.x += chooserBounds.x;
    box.y += chooserBounds.y;
    const bool usable = !borrow.hiding && borrow.motion == borrowMotionLength && borrow.entryArt &&
        field<Word>(chooser, 0xf8) == 1 && !field<unsigned char>(chooser, 0x14c);
    field<unsigned char>(borrow.entry, 0x38) = usable;
    if (box.width > 0 && box.height > 0 && (box.x != borrow.entryBox.x || box.y != borrow.entryBox.y ||
        box.width != borrow.entryBox.width || box.height != borrow.entryBox.height)) {
        borrow.entryBox = box;
        widgetCall(borrow.entry, 0xac, box.x, box.y, box.width, box.height);
    }

    if (borrow.dialog && !borrowMounted()) closeBorrowDialog(base);
    const Word action = borrow.action;
    borrow.action = 0;
    if (action == borrowEntry && usable && !borrow.dialog) {
        borrow.dialog = openGameDialog(base, app, borrowWidth, borrowHeight, 0, true);
        if (borrow.dialog) {
            loadBorrowDialogArt(base);
            makeText(base, borrowHeading, U"借用植物");
            makeText(base, borrowEmpty, U"暂无可借用的植物");
            makeText(base, borrowLoading, U"正在读取离线好友…");
            if (!borrow.ready) requestBorrowOffers(base, wallTime(base));
            refreshBorrowOffers(base);
        }
    } else if (borrow.dialog && action) {
        if (action >= borrowPick && action - borrowPick < borrow.count) {
            borrow.selected = action - borrowPick + 1;
            closeBorrowDialog(base);
        } else if (action == borrowClear || action == borrowClose) {
            if (action == borrowClear) borrow.selected = 0;
            closeBorrowDialog(base);
        } else {
            if (action == borrowPrevious && borrow.page) --borrow.page;
            if (action == borrowNext && (borrow.page + 1) * borrowPageSize < borrow.count) ++borrow.page;
            refreshBorrowOffers(base);
        }
    }
    if (borrow.dialog && !borrow.ready) pollBorrowOffers(base, wallTime(base));
}
}

extern "C" bool asterBorrowDeferChooserHide(Word base, Object chooser) {
    if (!borrow.entry || !borrow.entryArt || chooser != borrow.chooser || !borrow.motion ||
        borrow.board != gameBoard(base)) return false;
    if (!borrow.hiding) {
        borrow.hiding = true;
        borrow.motionSample = wallTime(base);
        borrow.action = 0;
        field<unsigned char>(borrow.entry, 0x38) = 0;
    }
    return true;
}

extern "C" void asterBorrowDrawBehindChooser(Word base, Object chooser, Object graphics) {
    native<void>(base, 0x976438, chooser, graphics);
    renderBorrowEntry(base, chooser, graphics, false);
}

extern "C" void asterBorrowDrawOverChooser(Word base, Object chooser, Object graphics) {
    renderBorrowEntry(base, chooser, graphics, true);
    native<void>(base, 0x116d764, graphics);
}

static void bindBorrowedCard(Object board) {
    if (board != borrow.board || borrow.request.owner != current.owner || !borrow.selected ||
        borrow.request.day != current.day || borrow.selected > borrow.count) return;
    const auto& card = borrow.offers[borrow.selected - 1].card;
    for (Word i = 0; i < 32; ++i) current.borrowedCard.type[i] = card.type[i];
    current.borrowedCard.level = card.level;
    current.borrowedDropTime = 35.0f;
    borrow.selected = 0;
}

static void dropBorrowedCard(Word base, Object board) {
    char allocator = 0;
    const char* kind = nullptr;
    const char* alias = nullptr;
    const Word columns = field<Word>(board, 0xb4);
    const Word rows = field<Word>(board, 0xb8);
    if (!columns || !rows || !borrowPlantType(base, current.borrowedCard.type)) {
        current.borrowedCard.level = 0;
        return;
    }
    native<void>(base, 0x14ed0e1, &kind, "seed_rain", &allocator);
    int lawn[4];
    native<void>(base, 0x240dbc, lawn, 0U, 0U, columns, rows);
    constexpr int horizontalInset = 48;
    constexpr int verticalInset = 36;
    const int x = lawn[0] + (lawn[2] > 2 * horizontalInset
        ? horizontalInset + native<int>(base, 0x11317a8, lawn[2] - 2 * horizontalInset)
        : lawn[2] / 2);
    const int y = lawn[1] + (lawn[3] > 2 * verticalInset
        ? verticalInset + native<int>(base, 0x11317a8, lawn[3] - 2 * verticalInset)
        : lawn[3] / 2);
    // The pickup lands at its world X/Y when its height reaches zero.
    const float start[3] = {float(x), float(y), float(y + 50)};
    Object drop = native<Object>(base, 0x21f5bc, board, &kind, start);
    releaseString(base, kind);
    if (!drop) {
        current.borrowedCard.level = 0;
        return;
    }
    native<void>(base, 0x14ed0e1, &alias, current.borrowedCard.type, &allocator);
    native<void>(base, 0x28fad8, drop, &alias);
    releaseString(base, alias);
    const Word content[2]{0, 0};
    native<void>(base, 0x28fd90, drop, content);
    const float velocity[3] = {0.0f, 0.0f, 0.0f};
    const float acceleration[3] = {0.0f, 0.0f, -600.0f};
    native<void>(base, 0x279230, drop, velocity, acceleration, 1U);
    native<void>(base, 0x278de4, drop, 1U);
    native<void>(base, 0x278ecc, drop);
    current.borrowedDrop = {field<Word>(drop, 8), field<Word>(drop, 12)};
    if (!(current.borrowedDrop.id | current.borrowedDrop.serial)) current.borrowedCard.level = 0;
    native<int>(base, 0x147adc, 4, "AsterAdventure", "borrow-drop type=%s level=%u x=%d y=%d",
                current.borrowedCard.type, current.borrowedCard.level, x, y);
}

extern "C" bool asterAdventureBindBorrowCursor(Word base, Object board, Object cursor, Object drop) {
    const bool accepted = native<bool>(base, 0x229e8c, board, cursor);
    if (sameRun(base, board) && current.borrowedCard.level) {
        current.borrowedCursor = accepted && field<Word>(drop, 8) == current.borrowedDrop.id &&
            field<Word>(drop, 12) == current.borrowedDrop.serial &&
            (current.borrowedDrop.id || current.borrowedDrop.serial) ? cursor : nullptr;
    }
    return accepted;
}

extern "C" Object asterAdventurePlaceBorrowed(Word base, Object cursor, Word column, Word row, int grade) {
    const bool borrowed = sameRun(base, gameBoard(base)) && current.borrowedCursor == cursor &&
        current.borrowedCard.level;
    Object plant = native<Object>(base, 0x4e719c, cursor, column, row,
                                  borrowed ? int(current.borrowedCard.level) : grade);
    if (borrowed && plant) {
        native<int>(base, 0x147adc, 4, "AsterAdventure", "borrow-placed type=%s requested=%u actual=%u",
                    current.borrowedCard.type, current.borrowedCard.level, field<Word>(plant, 0x38));
        current.borrowedCursor = nullptr;
        current.borrowedCard.level = 0;
    }
    return plant;
}

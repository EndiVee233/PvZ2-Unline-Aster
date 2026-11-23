// The Chinese HUD uses an anchored price bubble for paid Tactical Cucumber.
using Word = unsigned;
using Object = unsigned char*;

template<class T> static T& field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R native(Word base, Word offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

struct Rect {
    int x, y, width, height;

    bool contains(int px, int py) const {
        return px >= x && px < x + width && py >= y && py < y + height;
    }
};

struct Touch {
    Word id, pad;
    int x, y, previousX, previousY, taps, pad2;
    Word time[2], phase;
};

struct Offer {
    Object app, board, button, type, image;
    int price;
    Word touchId;
    bool pressed, draggedOff;
};

static Offer offer;
static constexpr char resourceGroup[] = "UI_AsterSocial";
static constexpr char artKey[] = "IMAGE_ASTER_SOCIAL_CUKE_BUY_CONFIRMATION";
static constexpr Word activatePowerup = 0x224508;

static Object gameApp(Word base) {
    const auto holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return holder ? field<Object>(holder, 0) : nullptr;
}

static bool interactive(Word base, Object app, Object board, Object button) {
    if (!app || !board || !button || field<Object>(app, 0x6bc) != board ||
        (field<Word>(board, 0xc0) != 4 && field<Word>(board, 0xc0) != 5) ||
        field<unsigned char>(board, 0x8d5) ||
        !(field<Word>(button, 0x54) & 4) || field<unsigned char>(button, 0x114)) return false;
    const auto modal = field<int(*)(Object, Word)>(field<Object>(app, 0), 0x12c);
    return !modal(app, 1U) && native<int>(base, 0x976720, button) &&
        !native<int>(base, 0x209554, board) && !native<Object>(base, 0x224474, board);
}

static bool sameName(const char* name, const char* expected) {
    if (!name) return false;
    while (*name && *name == *expected) { ++name; ++expected; }
    return *name == *expected;
}

static int purchasePrice(Word base, Object board, Object type) {
    if (!type || !sameName(field<const char*>(type, 8), "PowerupTacticalCuke")) return 0;
    const auto manager = native<Object>(base, 0x223db8, board);
    if (!manager) return 0;
    const auto state = native<Object>(base, 0x78403c, manager, type);
    if (!state || !field<unsigned char>(state, 0x20) || field<unsigned char>(state, 0x1a)) return 0;
    const auto store = native<Object>(base, 0x1df738);
    const auto player = store ? native<Object>(base, 0x7a98dc, store) : nullptr;
    const int inventory = player ? native<int>(base, 0x71899c, player, type + 4) : 0;
    if (!player || inventory != 0) return 0;
    // Aster displays and debits diamonds even though its legacy type uses currency enum zero.
    return field<int>(type, 0x28) * field<int>(manager, 0x80);
}

static void holdArt(Word base, Object app, bool load) {
    const char* name = nullptr;
    char allocator = 0;
    native<void>(base, 0x14ed0e1, &name, resourceGroup, &allocator);
    if (!name) return;
    native<void>(base, load ? 0x41c74c : 0x41c410, app, &name);
    native<void>(base, 0x14ebf59, name - 12, &allocator);
}

static void close(Word base) {
    const auto app = offer.app;
    offer.button = nullptr;
    offer.pressed = false;
    if (app && app == gameApp(base)) holdArt(base, app, false);
    offer.app = nullptr;
}

static Object bubbleArt(Word base) {
    struct Descriptor { Word reserved[3]; const char* key; Word ref[2]; };
    struct Skin { Word mode; Object image; Word options[6]; };
    Descriptor descriptor;
    descriptor.key = artKey;
    descriptor.ref[0] = descriptor.ref[1] = 0;
    Skin skin;
    skin.image = nullptr;
    native<void>(base, 0x7e8a28, &skin, &descriptor, 2U);
    native<void>(base, 0x1d9bb4, &descriptor.ref, 0U, 0U, 0U);
    return skin.image;
}

static Rect bubble(const Rect& button) {
    // Match the Chinese confirmation sprite (196 × 228) to the HUD's 128 px icon.
    const int width = button.width * 196 / 128;
    const int height = button.width * 228 / 128;
    return {button.x + (button.width - width) / 2,
            button.y + button.height / 6 - height, width, height};
}

extern "C" void asterCukeOffer(Word base, Object board, Object type, Object button) {
    const int price = purchasePrice(base, board, type);
    if (price <= 0) {
        native<void>(base, activatePowerup, board, type, 0U);
        return;
    }
    const auto app = gameApp(base);
    if (!interactive(base, app, board, button)) return;
    if (offer.button) close(base);
    holdArt(base, app, true);
    const auto image = bubbleArt(base);
    if (!image) {
        holdArt(base, app, false);
        return;
    }
    offer = {app, board, button, type, image, price, 0, false, false};
    native<void>(base, 0x20963c, board);
}

extern "C" bool asterCukeTouch(Word base, Object board, const Touch* event) {
    if (!offer.button || offer.board != board || !event) return false;
    if (!interactive(base, gameApp(base), board, offer.button)) {
        close(base);
        return false;
    }
    Rect bounds;
    native<void>(base, 0x97636c, &bounds, offer.button);
    // Board receives the original touch relative to its origin, before the camera transforms it.
    const int x = event->x + field<int>(board, 0x2c);
    const int y = event->y + field<int>(board, 0x30);
    const bool onButton = bounds.contains(x, y);
    const bool hit = !onButton && bubble(bounds).contains(x, y);
    if (event->phase == 0) {
        if (offer.pressed) return hit || onButton;
        if (hit) {
            offer.pressed = true;
            offer.touchId = event->id;
            return true;
        }
        close(base);
        return onButton;
    }
    if (!offer.pressed || offer.touchId != event->id) return false;
    if (event->phase == 1 && !hit) offer.draggedOff = true;
    if (event->phase == 3 || event->phase == 4) {
        const auto type = offer.type;
        const auto price = offer.price;
        const bool confirmed = event->phase == 3 && hit && !offer.draggedOff;
        close(base);
        if (confirmed && purchasePrice(base, board, type) == price)
            native<void>(base, activatePowerup, board, type, 0U);
    }
    return true;
}

extern "C" void asterCukeDraw(Word base, Object button, Object graphics) {
    native<void>(base, 0x797918, button, graphics);
    if (offer.button != button) return;
    if (!interactive(base, gameApp(base), offer.board, button)) {
        close(base);
        return;
    }
    const auto rect = bubble({0, 0, field<int>(button, 0x30), field<int>(button, 0x34)});
    native<void>(base, 0x11698b4, graphics, offer.image, rect.x, rect.y, rect.width, rect.height);

    char32_t digits[11];
    auto* start = digits + 10;
    *start = 0;
    Word price = offer.price;
    do {
        *--start = U'0' + price % 10;
        price /= 10;
    } while (price);
    const auto font = field<Object>(reinterpret_cast<Object>(base), 0x184110c);
    if (!font) return;
    const char32_t* text = nullptr;
    char allocator = 0;
    native<void>(base, 0x14eb451, &text, start, &allocator);
    if (text) {
        const int ink[] = {42, 33, 22, 255};
        native<void>(base, 0x13af2d0, font, graphics, float(rect.x + rect.width * 33 / 100),
                     float(rect.y + rect.height * 63 / 100), float(rect.width * 46 / 100),
                     &text, 1U, &ink, 0U);
        native<void>(base, 0x14ea239, text - 3, &allocator);
    }
}

extern "C" void asterCukeDismiss(Word base, Object button) {
    if (offer.button == button) close(base);
}

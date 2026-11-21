// Use the existing A184 world/UI matrix ABI after the stock camera.
using U = unsigned;
using I = int;
using P = unsigned char*;

template<class T> static T& field(P object, U offset) {
    return *reinterpret_cast<T*>(object + offset);
}
template<class T, class... Args> static T call(U base, U address, Args... args) {
    return reinterpret_cast<T(*)(Args...)>(base + address)(args...);
}

// A184's UI and screen-message draw callbacks read this context.
struct ViewDrawContext {
    U base;
    P graphics, device;
    float matrix[9];
    bool ui;
    ViewDrawContext* prior;
};

struct ViewportTransform {
    float zoom, x, y;
};

static constexpr float NormalZoom = 1.2f;
static constexpr float LawnLeft = 200.0f;
static constexpr float LawnWidth = 9.0f * 64.0f;
static constexpr float ArenaWidth = 11.0f * 64.0f; // Includes the two deployment columns.
static constexpr U IntroDurationMs = 550;

// The pose stores the screen position of the board's local (0, 0).
struct BoardPose {
    float zoom, x, y;
};
struct IntroCamera {
    P board;
    I width;
    float scale;
    bool preview, moving;
    U started;
    BoardPose start, rendered;
};
static IntroCamera intro;

static bool inArena(P board) {
    const char* name = field<const char*>(board, 0xc4);
    return name && name[0]=='a' && name[1]=='r' && name[2]=='e' && name[3]=='n' && name[4]=='a' && name[5]=='_';
}

static ViewportTransform fitViewport(P board, P app, float originX, float originY) {
    const float width = float(field<I>(app, 0x524));
    const float scale = field<float>(app, 0x690);
    const bool arena = inArena(board);
    const U phase = field<U>(board, 0xc0);
    float zoom = NormalZoom;
    float shiftX = width * (1.0f - zoom);
    // Let the ordinary level introduction keep its native horizontal pan.
    if (width > 0.0f && scale > 0.0f && (arena || phase == 4 || phase == 5)) {
        const float lawnWidth = (arena ? ArenaWidth : LawnWidth) * scale;
        float leftInset = (arena ? 144.0f : 112.0f) * scale;
        const float rightInset = 12.0f * scale;
        if (leftInset > width * 0.25f) leftInset = width * 0.25f;
        const float fit = (width - leftInset - rightInset) / lawnWidth;
        if (fit > 0.0f) {
            if (fit < zoom) zoom = fit;
            // Keep the card bank and scout panel clear of the first grid cell.
            const float lawnStart = (originX + LawnLeft * scale) * zoom;
            const float minShift = leftInset - lawnStart;
            const float maxShift = width - rightInset - lawnStart - lawnWidth * zoom;
            shiftX = width * (1.0f - zoom);
            if (shiftX < minShift) shiftX = minShift;
            if (shiftX > maxShift) shiftX = maxShift;
        }
    }
    return {zoom, shiftX, (originY + 540.0f * scale) * (1.0f - zoom)};
}

static P appAt(U base) {
    P holder = field<P>(reinterpret_cast<P>(base), 0x1821674);
    return holder ? field<P>(holder, 0) : nullptr;
}

static bool sameViewport(P board, P app) {
    return intro.board == board && intro.width == field<I>(app, 0x524)
           && intro.scale == field<float>(app, 0x690);
}

static bool monotonicMs(U base, U& time) {
    struct Timespec { I seconds, nanoseconds; } stamp{};
    auto clockGettime = reinterpret_cast<I(*)(I, Timespec*)>(
            field<U>(reinterpret_cast<P>(base), 0x1822ee0));
    if (!clockGettime || clockGettime(1, &stamp) != 0) return false;
    time = U(stamp.seconds) * 1000U + U(stamp.nanoseconds) / 1000000U;
    return true;
}

static ViewportTransform drawViewport(U base, P board, P app, float x, float y) {
    const ViewportTransform target = fitViewport(board, app, x, y);
    if (inArena(board)) {
        intro.board = nullptr;
        return target;
    }
    if (!sameViewport(board, app)) {
        intro.board = board;
        intro.width = field<I>(app, 0x524);
        intro.scale = field<float>(app, 0x690);
        intro.preview = intro.moving = false;
    }
    const BoardPose end{target.zoom, x * target.zoom + target.x, y * target.zoom + target.y};
    const U phase = field<U>(board, 0xc0);
    if (phase != 4 && phase != 5) {
        intro.rendered = end;
        intro.preview = true;
        intro.moving = false;
        return target;
    }

    const bool begin = intro.preview;
    if (begin) {
        intro.preview = false;
        // Only ease the handoff if fitting changes the stock camera. A wide
        // viewport that already fits can keep the original pan by itself.
        intro.moving = target.zoom != NormalZoom || target.x != float(intro.width) * (1.0f - NormalZoom);
        intro.start = intro.rendered;
    }
    if (!intro.moving) return target;
    U now;
    if (!monotonicMs(base, now)) {
        intro.moving = false;
        return target;
    }
    if (begin) intro.started = now;
    const U elapsed = now - intro.started;
    if (elapsed >= IntroDurationMs) {
        intro.moving = false;
        return target;
    }
    const float t = float(elapsed) / float(IntroDurationMs);
    const float progress = t * t * (3.0f - 2.0f * t);
    intro.rendered = {
        intro.start.zoom + (end.zoom - intro.start.zoom) * progress,
        intro.start.x + (end.x - intro.start.x) * progress,
        intro.start.y + (end.y - intro.start.y) * progress
    };
    const BoardPose& pose = intro.rendered;
    return {pose.zoom, pose.x - x * pose.zoom, pose.y - y * pose.zoom};
}

extern "C" void asterViewportDraw(U base, P board, P graphics) {
    constexpr U DrawBoard = 0x235048;
    if (!graphics || !call<bool>(base, 0x1a2d264, base, board)) {
        intro.board = nullptr;
        call<void>(base, DrawBoard, board, graphics);
        return;
    }
    P device = call<P>(base, 0x1166bc4, graphics);
    if (!device) {
        call<void>(base, DrawBoard, board, graphics);
        return;
    }

    const float x = field<float>(graphics, 8);
    const float y = field<float>(graphics, 12);
    const ViewportTransform view = drawViewport(base, board, appAt(base), x, y);
    P state = reinterpret_cast<P>(base);
    field<P>(state, 0x1b02008) = board;
    field<I>(state, 0x1b0200c) = I(x);
    field<I>(state, 0x1b02010) = I(y);
    ViewDrawContext*& drawing = field<ViewDrawContext*>(state, 0x1b02018);
    ViewDrawContext context{base, graphics, device,
                            {view.zoom, 0, view.x, 0, view.zoom, view.y, 0, 0, 1},
                            false, drawing};
    drawing = &context;
    call<void>(base, 0x116c9ac, device, context.matrix, 1U);
    call<void>(base, DrawBoard, board, graphics);
    call<void>(base, 0x116c9f0, device);
    drawing = context.prior;
}

static I floorPixel(float value) {
    const I truncated = I(value);
    return truncated - (float(truncated) > value);
}

extern "C" void asterViewportPoint(U base, P board, I* point) {
    if (!point || !call<bool>(base, 0x1a2d264, base, board)) return;
    // WidgetManager subtracts Board's origin before dispatch. Add it back
    // before inverting the world matrix, then return Board-local coordinates.
    const float x = float(field<I>(board, 0x2c));
    const float y = float(field<I>(board, 0x30));
    P app = appAt(base);
    if (intro.moving && sameViewport(board, app) && !inArena(board)) {
        const BoardPose& pose = intro.rendered;
        point[0] = floorPixel((float(point[0]) + x - pose.x) / pose.zoom);
        point[1] = floorPixel((float(point[1]) + y - pose.y) / pose.zoom);
        return;
    }
    const ViewportTransform view = fitViewport(board, app, x, y);
    point[0] = floorPixel((float(point[0]) + x - view.x) / view.zoom - x);
    point[1] = floorPixel((float(point[1]) + y - view.y) / view.zoom - y);
}

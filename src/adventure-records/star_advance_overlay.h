// The installed social payload owns the live selection and progress lookup.
// Keep those same objects when adding the two result-dialog hooks to it.
using Word = U;
using Object = P;

template<class T> static T& field(Object object, Word offset) {
    return at<T>(object, offset);
}

template<class R, class... A> static R native(Word base, Word offset, A... args) {
    return call<R>(base, offset, args...);
}

#include "star_advance.h"

extern "C" int asterAdventureNextStar(Word base, Object object, Word apply) {
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = holder ? field<Object>(holder, 0) : nullptr;
    Object board = app ? field<Object>(app, 0x6bc) : nullptr;
    Object store = field<Object>(reinterpret_cast<Object>(base), 0x18300a4);
    if (!store) return stockStarFlow;
    auto& choice = field<ChallengeChoice>(reinterpret_cast<Object>(base), ASTER_SOCIAL_CHALLENGE_CHOICE);
    return advanceAdventureStar(base, apply ? currentStarResult(object) : object, board,
                                field<Word>(store, 0x74), choice, apply,
                                [](Word b, Word count, Word index, Word mode) {
                                    return native<int>(b, ASTER_SOCIAL_STAR_MASK, b, count, index, mode);
                                },
                                [base](const char* alias) {
                                    return native<Word>(base, ASTER_SOCIAL_LEVEL_ID, alias);
                                },
                                starAdvanceTime);
}

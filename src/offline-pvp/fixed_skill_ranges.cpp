// Build the range module against the retained shared engine without moving
// any accepted input, economy or lifecycle entry points.
using U=unsigned;using I=int;using P=unsigned char*;
template<class T> static T& at(P p,U o){return *reinterpret_cast<T*>(p+o);}
template<class R,class... A> static R call(U b,U o,A... a){return reinterpret_cast<R(*)(A...)>(b+o)(a...);}
#define PVP_WEEKLY_RULES
#include "skill_ranges.h"

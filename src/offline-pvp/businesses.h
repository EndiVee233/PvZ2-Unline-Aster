// First restore independent business map records and their native detail panel.
// Ownership, garrisons and rent are deliberately separate from residential raids.
enum class BusinessKind { Coffee, HotDog, Store };
struct BusinessRules {
 U attackFee,coinCapacity,medalCapacity,coinRate,medalRate;
 U threeStarCoins;
 char terrain[20];
};
struct BusinessPlot {U id,zone,position;BusinessKind kind;BusinessRules rules;};
// Keep the native Arena level name. The board loader selects each shop's
// stage definition while preserving Arena UI, input and settlement.
static constexpr BusinessRules SHOP_RULES={1,2000,2000,40,20,300,"arena_battle_test"};
// The native street renderer uses ((zone-2)*3+position+4)%3 for shop
// art: 2 is Coffee, 0 is Hot Dog and 1 is STORE. Match the boards to it.
static constexpr BusinessPlot BUSINESSES[]={
 {0x71000001,3,2,BusinessKind::HotDog,SHOP_RULES},
 {0x71000002,3,3,BusinessKind::Store,SHOP_RULES},
#ifdef PVP_DISTRICT_SHOPS
 {0x71000003,2,1,BusinessKind::Coffee,SHOP_RULES},
 {0x71000004,2,2,BusinessKind::HotDog,SHOP_RULES},
 {0x71000005,2,3,BusinessKind::Store,SHOP_RULES},
 {0x71000006,3,1,BusinessKind::Coffee,SHOP_RULES},
 {0x71000007,4,1,BusinessKind::Coffee,SHOP_RULES},
 {0x71000008,4,2,BusinessKind::HotDog,SHOP_RULES},
 {0x71000009,4,3,BusinessKind::Store,SHOP_RULES},
 {0x7100000a,5,1,BusinessKind::Coffee,SHOP_RULES},
 {0x7100000b,5,2,BusinessKind::HotDog,SHOP_RULES},
 {0x7100000c,5,3,BusinessKind::Store,SHOP_RULES},
 {0x7100000d,6,1,BusinessKind::Coffee,SHOP_RULES},
 {0x7100000e,6,2,BusinessKind::HotDog,SHOP_RULES},
 {0x7100000f,6,3,BusinessKind::Store,SHOP_RULES},
#endif
};
static constexpr U BUSINESS_COUNT=sizeof(BUSINESSES)/sizeof(BUSINESSES[0]);
static U businessIndex(U id){return id-0x71000001u;}
#ifdef PVP_DISTRICT_SHOPS
static bool activeBusiness(const BusinessPlot& plot);
#endif
static const char32_t* businessName(const BusinessPlot& plot){
 return plot.kind==BusinessKind::Coffee?U"咖啡店":plot.kind==BusinessKind::HotDog?U"热狗店":U"商店";
}
static bool businessLand(const BusinessPlot& plot,U row,U col){
 return plot.kind!=BusinessKind::HotDog||col<5||(row!=1&&row!=3);
}
static void businessTitle(U* title,const U* occupier){
 if(!occupier){
  const char32_t vacant[]=U"空置的小屋";
  for(U i=0;i<sizeof(vacant)/sizeof(*vacant);++i)title[i]=vacant[i];
  return;
 }
 U count=0;
 while(count<39&&occupier[count]){title[count]=occupier[count];++count;}
 title[count]=0;
}
#ifdef PVP_BUSINESS_REPLACE
static P businessReplacePanel;
static U businessReplaceUser;
static U replaceBusinessOpponent(U b,P panel);
#endif
extern "C" U offlineBusinessMapMode(){return 1;}
#ifdef PVP_BUSINESS_OWNER
// The original getter parses the server account id, which is zero offline.
// Zero is also the unoccupied-owner sentinel. Use the selected local profile
// for native ownership comparisons; keep wallet/save keys unchanged. A local
// profile numbered zero receives a nonzero UI identity, never the sentinel.
extern "C" U offlineBusinessIdentity(U b){
 if(!regular(b))return 0;U user=owner(b);return user?user:0x7fffffff;
}
#endif
static const BusinessPlot* businessPlot(U zone,U position){
 for(U i=0;i<BUSINESS_COUNT;++i)
  if(BUSINESSES[i].zone==zone&&BUSINESSES[i].position==position)return BUSINESSES+i;
 return nullptr;
}
#ifdef PVP_BUSINESS_SCOUT
extern "C" U offlineBusinessScoutMode(){return 1;}
static const BusinessPlot* businessId(U id){
 U index=businessIndex(id);return index<BUSINESS_COUNT?BUSINESSES+index:nullptr;
}
static bool scoutBusiness(U b,const BusinessPlot&s,bool attack=false);
#endif
#ifdef PVP_BUSINESS_BATTLE
extern "C" U offlineBusinessBattleMode(){return 1;}
static U businessBit(U id){U index=businessIndex(id);return index<BUSINESS_COUNT?1u<<index:0;}
static void projectBusinessOwners(U b,P m);
static bool attackBusiness(U b,const BusinessPlot&s);
#endif
#ifdef PVP_BUSINESS_DEFENSE
extern "C" U offlineBusinessDefenseMode(){return 1;}
static bool defendBusiness(U b,const BusinessPlot&s);
#endif
#ifdef PVP_BUSINESS_COLLECTION
static bool collectBusiness(U b,const BusinessPlot&s);
#endif
static void projectBusinesses(U b,P m){
 if(!regular(b))return;
 for(U i=0;i<BUSINESS_COUNT;++i){
  const BusinessPlot&s=BUSINESSES[i];bool occupied=false;
#ifdef PVP_DISTRICT_SHOPS
  if(!activeBusiness(s))continue;
#endif
#ifdef PVP_REGIONS
  if(!regionOpen(s.zone))continue;
#endif
  P begin=at<P>(m,0x110),end=at<P>(m,0x114);
  if((begin&&end<begin)||U(end-begin)>64*256||U(end-begin)%64)return;
  for(P p=begin;p<end;p+=64)if(at<U>(p,48)==s.zone&&at<U>(p,52)==s.position){occupied=true;break;}
  // Never replace a server/foreign record or manufacture player ownership.
  if(occupied)continue;
  P first=at<P>(m,0x128),last=at<P>(m,0x12c);
  if((first&&last<first)||U(last-first)>64*256||U(last-first)%64)return;
  for(P p=first;p<last;p+=64)if(at<U>(p,28)==s.zone&&at<U>(p,32)==s.position){occupied=true;break;}
  if(occupied)continue;
  // Local unoccupied fixtures: no accrued funds or production before capture.
  // Capacity is a provisional local value, not a recovered server economy.
  alignas(8) U record[16]={s.id,0,0,0,0,1,0,s.rules.medalCapacity,0,s.rules.coinCapacity,0,0,s.zone,s.position,1,0};
  U title[40]{};businessTitle(title,nullptr);
  char alloc=0;call<void>(b,0x14eb451,reinterpret_cast<P>(record)+16,title,&alloc);
  call<void>(b,0x1046a04,m,record);release(b,reinterpret_cast<P>(record[4]),true);
  log(b,"business-map-added",s.zone,s.position);
 }
#ifdef PVP_BUSINESS_BATTLE
 projectBusinessOwners(b,m);
#endif
}
static bool localBusinessPanel(U b,P panel){
 if(!panel||!regular(b))return false;
 U kind=at<U>(panel,0xa4);if(kind!=3
#ifdef PVP_BUSINESS_BATTLE
 &&kind!=2
#endif
 )return false;
 const BusinessPlot*s=businessPlot(at<U>(panel,0xac),at<U>(panel,0xa8));if(!s)return false;
 P m=manager(b),begin=at<P>(m,0x110),end=at<P>(m,0x114);
 if(!begin||end<begin||U(end-begin)>64*256||U(end-begin)%64)return false;
 for(P p=begin;p<end;p+=64)if(at<U>(p,48)==s->zone&&at<U>(p,52)==s->position)
  return at<U>(p,0)==s->id&&(at<U64>(p,8)==0
#ifdef PVP_BUSINESS_BATTLE
  ||at<U64>(p,8)==offlineBusinessIdentity(b)
#endif
#ifdef PVP_SILENT_RAIDS
  ||localRaidOccupier(b,at<U64>(p,8))
#endif
  );
 return false;
}
// Scouting is local when enabled; other unfinished shop actions must not fall
// through into old server requests. Closing the panel remains the original
// handler; residence and own-base events pass.
extern "C" U offlineBusinessAction(U b,P panel,U button){
#ifdef PVP_BUSINESS_REPLACE
 if(button==204&&panel&&panel==businessReplacePanel&&businessReplaceUser!=owner(b))return 1;
#endif
#ifdef PVP_RANDOM_NEIGHBORS
 if(neighborAction(b,panel,button))return 1;
#endif
#ifdef PVP_REGIONS
 if(regionAction(b,panel,button))return 1;
#endif
 if(button==203||!localBusinessPanel(b,panel))return 0;
#ifdef PVP_BUSINESS_REPLACE
 if(button==204)return replaceBusinessOpponent(b,panel);
#endif
#ifdef PVP_BUSINESS_COLLECTION
 if(button==200&&at<U>(panel,0xa4)==2){
  const BusinessPlot*s=businessPlot(at<U>(panel,0xac),at<U>(panel,0xa8));
  if(s&&collectBusiness(b,*s))if(P map=at<P>(panel,0xc0))call<void>(b,0x100a864,map);
  return 1;
 }
#endif
#ifdef PVP_BUSINESS_DEFENSE
 if(button==201&&at<U>(panel,0xa4)==2){
  const BusinessPlot*s=businessPlot(at<U>(panel,0xac),at<U>(panel,0xa8));
  if(s&&defendBusiness(b,*s))call<void>(b,0x100a864,at<P>(panel,0xc0));
  return 1;
 }
#endif
#ifdef PVP_BUSINESS_SCOUT
 if(button==205){
  const BusinessPlot*s=businessPlot(at<U>(panel,0xac),at<U>(panel,0xa8));
  if(s&&scoutBusiness(b,*s))call<void>(b,0x100a864,at<P>(panel,0xc0));
  return 1;
 }
#endif
 log(b,"business-action-pending",button);return 1;
}
extern "C" U offlineBusinessRaidInput(U b,P panel){
 if(!localBusinessPanel(b,panel))return 0;
#ifdef PVP_BUSINESS_BATTLE
 // Keep the original big-button hit test and army validation. The request
 // reaches offlineAttack only when the user actually clicks its rectangle.
 if(at<U>(panel,0xa4)==3)return 0;
#endif
 log(b,"business-raid-pending");return 1;
}

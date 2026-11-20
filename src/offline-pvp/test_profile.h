// The setting is a view of the actual PlayerInfo registry. Renaming, deleting
// or restoring a player therefore requires no second preference to synchronize.
#include "all_one_template.h"
static constexpr U testUid[]={1,193,0x41535452};
enum class ProfileError { none, full, save, create };
static ProfileError profileError;

static P testStore(U b){return call<P>(b,0x864900,call<P>(b,0x20ec10),0x2d);}
static P managedSlot(P db){
 if(!db)return nullptr;
 P end=db+0x30,slot=at<P>(end,0);
 for(U left=at<U>(db,0x50);left&&slot&&slot!=end;--left,slot=at<P>(slot,0)){
  if(at<U>(slot,0x14)==testUid[0]&&at<U>(slot,0x18)==testUid[1]&&at<U>(slot,0x1c)==testUid[2])return slot;
 }
 return nullptr;
}
static void profileWeakRelease(U b,U* weak){
 // The native setter takes one 64-bit handle in the aligned r2/r3 pair.
 call<void>(b,0x1d9bb4,weak,U64{0});
}
static void disposePlayer(U b,P player){call<void>(b,at<U>(at<P>(player,0),0x14)-b,player);}
static void registerTestPlayer(U b,P db,P player,U* weak){
 call<void>(b,0x11dd120,weak,db,player,0U,1U,testUid);
}
static U freshPlayerId(U b,P pm){
 auto got=[&](U o){return at<U>(reinterpret_cast<P>(b),o)-b;};
 I fd=call<I>(b,got(0x1822ebc),"/dev/urandom",0,0);
 if(fd<0)return 0;
 U chosen=0;
 for(U n=0;n<8&&!chosen;++n){
  U value=0,weak[2]={};
  if(call<I>(b,got(0x1822ec4),fd,&value,4U)!=4)break;
  value=(value&0x3fffffffu)|0x40000000u;
  call<void>(b,0x7aab68,weak,pm,value);
  if(!(weak[0]|weak[1]))chosen=value;
  profileWeakRelease(b,weak);
 }
 call<I>(b,got(0x1822bd4),fd);
 return chosen;
}
static bool persistPlayers(U b,P pm){return call<bool>(b,0x4a10a0,at<P>(pm,4)+4);}
static ProfileError addTestPlayer(U b,P db,P pm){
 if(at<U>(db,0x50)>=5)return ProfileError::full; // stock add row, 0x461708
 U id=freshPlayerId(b,pm);
 if(!id)return ProfileError::create;
 P type=call<P>(b,0x72c500);
 P player=call<P>(b,at<U>(type,0xc)-b);
 if(!player)return ProfileError::create;
 // Only deserialize objdata into this newly allocated instance. The full
 // package loader's first pass resets the registry and cannot be used here.
 U reader[6]={};
 call<void>(b,0x11f2c88,reader,allOneRton,sizeof(allOneRton));
 struct {U* reader;P writer;U reading;} archive={reader,nullptr,1};
 P players[]={player};
 struct {P* begin;P* end;P* capacity;} targets={players,players+1,players+1};
 bool loaded=call<bool>(b,0x11dad94,db,&archive,&targets);
 call<void>(b,0x11ed448,reader);
 if(!loaded||at<U>(player,0x1ec)!=1722523140u){disposePlayer(b,player);return ProfileError::create;}
 // Assign an independent gameplay ID for wallet/formation data. The object
 // UID above is the identity used by this setting, including across saves.
 at<U>(player,0x1ec)=id;
 char32_t label[]=U"全一 TEST 2";
 for(U n=1;n<=5;++n){
  label[7]=n==1?0:U' ';label[8]=U'0'+n;
  P name=nullptr;char allocator=0;U existing[2]={};
  call<void>(b,0x14eb451,&name,label,&allocator);
  call<void>(b,0x7aa7c8,existing,pm,&name);
  bool free=!(existing[0]|existing[1]);profileWeakRelease(b,existing);
  if(free)call<void>(b,0x14eae75,player+0x58,&name);
  release(b,name,true);
  if(free)break;
 }
 U weak[2]={};
 registerTestPlayer(b,db,player,weak);
 bool saved=persistPlayers(b,pm);
 if(!saved)call<void>(b,0x11d6450,db,weak);
 profileWeakRelease(b,weak);
 return saved?ProfileError::none:ProfileError::save;
}
static ProfileError removeTestPlayer(U b,P db,P pm,P slot){
 P player=at<P>(slot,8);U weak[2]={};
 if(!player)return ProfileError::save;
 U id=at<U>(player,0x1ec);
 call<void>(b,0x7aab68,weak,pm,id);
 if(call<P>(b,0x11d62c8,db,weak,0U)!=slot||(at<U>(slot,0x10)&0x03ffffffu)!=1){
  profileWeakRelease(b,weak);return ProfileError::save;
 }
 // Ownership mode 2 detaches the object without destruction. A failed
 // native write can reattach the same player, including all of its progress.
 call<void>(b,0x11d635c,db,slot,2U);
 bool detached=call<bool>(b,0x11d6450,db,weak);
 profileWeakRelease(b,weak);
 if(!detached){call<void>(b,0x11d635c,db,slot,0U);return ProfileError::save;}
 if(!persistPlayers(b,pm)){
  registerTestPlayer(b,db,player,weak);profileWeakRelease(b,weak);return ProfileError::save;
 }
 if(at<U>(pm,0x74)==id){
  at<U>(pm,0x74)=0;
  if(at<U>(db,0x50))call<void>(b,0x7aaa74,pm);
 }
 disposePlayer(b,player);
 return ProfileError::none;
}
static ProfileError setTestProfile(U b,bool enabled){
 P pm=call<P>(b,0x1df738),db=testStore(b);
 if(!pm||!at<P>(pm,4)||!db)return ProfileError::save;
 P slot=managedSlot(db);
 if(enabled==bool(slot))return ProfileError::none;
 return enabled?addTestPlayer(b,db,pm):removeTestPlayer(b,db,pm,slot);
}
static const char32_t* testPageTitle(){
 static constexpr char32_t labels[][18]={U"测试存档",U"玩家槽位已满（最多5个）",
                                        U"存档保存失败，请重试",U"测试存档创建失败"};
 return labels[static_cast<U>(profileError)];
}

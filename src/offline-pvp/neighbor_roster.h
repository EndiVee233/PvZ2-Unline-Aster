// Rich neighbors have their own bounded, per-player atomic file. The full
// roster lives on the heap rather than overflowing the reserved native BSS.
static constexpr U NEIGHBOR_SLOT_COUNT=NPC_COUNT-1;
struct NeighborRoster {U magic,version,user,sequence,rng,checksum;NeighborEncounter entries[NEIGHBOR_SLOT_COUNT];};
static NeighborRoster* neighborRoster;
static U neighborRosterUser;
static bool neighborRosterBlocked;
static P neighborPanel;
static U neighborPanelUser;
static U activeEncounterId,activeEncounterSeed,activeEncounterKind;
extern "C" U offlineRandomNeighborsMode(){return 1;}
#ifdef PVP_UNIQUE_NEIGHBORS
extern "C" U offlineUniqueNeighborsMode(){return 1;}
static const NeighborPlantSpec* legacyNeighborPlant(U id){
 for(U i=0;i<NEIGHBOR_LEGACY_PLANT_COUNT;++i)if(NEIGHBOR_LEGACY_PLANTS[i].id==id)return NEIGHBOR_LEGACY_PLANTS+i;
 return nullptr;
}
#endif
static U neighborChecksumBytes(const unsigned char*p,U size){
 U hash=2166136261;
 for(U i=0;i<size;++i)if(i<20||i>=24)hash=(hash^p[i])*16777619u;
 return hash;
}
static U neighborChecksum(const NeighborRoster&r){return neighborChecksumBytes(reinterpret_cast<const unsigned char*>(&r),sizeof(r));}
static bool validEncounter(const NeighborEncounter&e,U expected,bool legacy=false,bool allowUnnamed=false,bool allowDisabled=false){
 if(e.id!=expected)return false;
 if(!e.seed){if(e.kind||e.cups||e.count)return false;return true;}
 bool shared=false;
#ifdef PVP_GITHUB_PRESETS
 shared=e.kind==SHARED_NEIGHBOR;
 if(shared){
  if(legacy||(!allowUnnamed&&!e.title[0])||e.title[39])return false;
  for(U ch:e.title)if((ch&&ch<32)||(ch>=127&&ch<=159)||(ch>=0xd800&&ch<=0xdfff)||ch>0x10ffff)return false;
 }
#endif
 if((!shared&&e.kind>7)||e.count<(shared?1u:5u)||e.count>45||e.kind==1&&e.cups!=999||e.kind!=1&&e.cups>(shared?99999u:550u)||e.kind==2&&e.cups<60||e.kind==3&&e.cups<40)return false;
 U spent=0;bool varied=false;
 for(U i=0;i<e.count;++i){const auto&q=e.plants[i];const auto*p=neighborPlant(q.type);
#ifdef PVP_UNIQUE_NEIGHBORS
  if(legacy||(!p&&allowDisabled))p=legacyNeighborPlant(q.type);
#endif
  if(!p||!q.level||q.level>p->maxLevel||q.row>=5||q.col>=9)return false;
  spent+=p->cost;varied|=q.level!=e.plants[0].level;U copies=1;
  for(U j=0;j<i;++j){const auto&other=e.plants[j];
   if(other.row==q.row&&other.col==q.col)return false;
   if(other.type==q.type){if(!shared&&other.level!=q.level)return false;++copies;}
  }
  if(e.kind!=1&&copies>10)return false;
  if(e.kind==1&&(q.type!=e.plants[0].type||q.level!=p->maxLevel))return false;
 }
 return e.kind==1?e.count==45:spent<=NEIGHBOR_MAX_SUN&&(varied||shared);
}
static bool validRoster(const NeighborRoster&r,U user){
 bool version=r.version==1;
#ifdef PVP_UNIQUE_NEIGHBORS
 version=version||r.version==2;U seen=0;
#ifdef PVP_GITHUB_PRESETS
 version=version||r.version==3;
#endif
 if(r.version>=2)for(U i=0;i<NEIGHBOR_SLOT_COUNT;++i){U kind=r.entries[i].kind;if(kind<2||kind>7)continue;
  if(seen&(1u<<kind))return false;seen|=1u<<kind;
 }
#endif
 if(r.magic!=0x4e425650||!version||r.user!=user||!r.rng||r.checksum!=neighborChecksum(r))return false;
 U slot=0;for(U i=0;i<NPC_COUNT;++i)if(!NPCS[i].evil){if(slot>=NEIGHBOR_SLOT_COUNT||!validEncounter(r.entries[slot++],NPCS[i].id,r.version==1,false,true))return false;}
 return slot==NEIGHBOR_SLOT_COUNT;
}
static void neighborPath(U user,char*out,bool tmp){
 economyPath(user,out,false);U length=0;while(out[length])++length;
 const char*suffix=tmp?".neighbors.tmp":".neighbors";length-=4;
 while(*suffix)out[length++]=*suffix++;out[length]=0;
}
static bool saveRoster(U b,NeighborRoster&r){
#ifdef PVP_GITHUB_PRESETS
 r.version=3;
#endif
 r.checksum=neighborChecksum(r);if(!validRoster(r,r.user))return false;
 char file[160],tmp[160];neighborPath(r.user,file,false);neighborPath(r.user,tmp,true);
 I fd=call<I>(b,0x148448,tmp,0x241,0600);if(fd<0)return false;U done=0;
 while(done<sizeof(r)){I n=call<I>(b,0x1485d4,fd,reinterpret_cast<P>(&r)+done,sizeof(r)-done);if(n<=0)break;done+=U(n);}
 bool ok=done==sizeof(r)&&call<I>(b,0x1485e0,fd)==0;if(call<I>(b,0x147b90,fd))ok=false;
 if(ok)ok=call<I>(b,0x147e6c,tmp,file)==0;if(!ok)call<I>(b,0x148424,tmp);return ok;
}
static I readRoster(U b,NeighborRoster&r,U user){
 char file[160];neighborPath(user,file,false);I fd=call<I>(b,0x148448,file,0,0);if(fd<0)return 0;
 U done=0;while(done<sizeof(r)){I n=call<I>(b,0x148460,fd,reinterpret_cast<P>(&r)+done,sizeof(r)-done);if(n<=0)break;done+=U(n);}
 char tail;I extra=call<I>(b,0x148460,fd,&tail,1);call<I>(b,0x147b90,fd);
#ifdef PVP_GITHUB_PRESETS
 constexpr U oldSize=24+NEIGHBOR_SLOT_COUNT*LEGACY_ENCOUNTER_BYTES;
 if(done==oldSize&&!extra&&(r.version==1||r.version==2)){
  P raw=reinterpret_cast<P>(&r);
  if(r.checksum!=neighborChecksumBytes(raw,oldSize))return -1;
  // Expand from the end so the input records can be read in place.
  for(U i=NEIGHBOR_SLOT_COUNT;i>0;--i){
   NeighborEncounter entry{};
   bytes(reinterpret_cast<P>(&entry),raw+24+(i-1)*LEGACY_ENCOUNTER_BYTES,LEGACY_ENCOUNTER_BYTES);
   r.entries[i-1]=entry;
  }
  r.checksum=neighborChecksum(r);
  return validRoster(r,user)?1:-1;
 }
#endif
 return done==sizeof(r)&&!extra&&validRoster(r,user)?1:-1;
}
static NeighborEncounter* findEncounter(NeighborRoster&r,U id){
 for(U i=0;i<NEIGHBOR_SLOT_COUNT;++i)if(r.entries[i].id==id)return r.entries+i;return nullptr;
}
#ifdef PVP_UNIQUE_NEIGHBORS
static void migrateNeighborRoster(NeighborRoster&r){
 U seen=0;
 for(U i=0;i<NEIGHBOR_SLOT_COUNT;++i){auto&e=r.entries[i];if(!e.seed)continue;
  U retained=0;
  for(U k=0;k<e.count;++k)if(neighborPlant(e.plants[k].type))e.plants[retained++]=e.plants[k];
  bool banned=retained!=e.count;e.count=retained;
  bool duplicate=e.kind>=2&&e.kind<=7&&(seen&(1u<<e.kind));
  bool legacySpecial=false;
#ifdef PVP_GITHUB_PRESETS
  legacySpecial=e.kind>=1&&e.kind<=7&&!e.title[0];
#endif
  if((banned&&!validEncounter(e,e.id))||duplicate||legacySpecial){
   U id=e.id,cups=e.cups;generateNeighbor(e,id,neighborRandom(r.rng),0,cups>550?550:cups);
  }
  if(e.kind>=2&&e.kind<=7)seen|=1u<<e.kind;
 }
 r.version=2;
}
#endif
#ifdef PVP_CUP_MATCHING
static U matchedNeighborCups(U playerCups,U seed){
 const U center=playerCups<500?playerCups:500;
 U rng=neighborMix(seed^0xb27159afu);
 const U roll=neighborRandom(rng)%100;
 const U radius=roll<75?10:roll<95?25:50;
 const U low=center>radius?center-radius:0;
 return low+neighborRemainder(neighborRandom(rng),center+radius-low+1);
}
#endif
#ifdef PVP_GITHUB_PRESETS
#include "shared_neighbors.h"
#endif
static void generateRosterNeighbor(NeighborRoster&r,NeighborEncounter&e,U id,U seed,U excludeShared=0,bool allowSpecial=true){
 U cups=0xffffffffu;
#ifdef PVP_CUP_MATCHING
 cups=matchedNeighborCups(economyRuntime.state.cups,seed);
#endif
 generateNeighbor(e,id,seed,0,cups);
#ifdef PVP_GITHUB_PRESETS
 pickSharedNeighbor(r,e,id,seed,cups,excludeShared,allowSpecial);
#endif
}
static bool ensureNeighborRoster(U b,P m){
 if(!regular(b)||!ensureEconomy(b,m))return false;U user=owner(b);
 if(!neighborRoster||neighborRosterUser!=user){
  if(neighborRoster)call<void>(b,0x147950,neighborRoster);
  neighborRoster=reinterpret_cast<NeighborRoster*>(call<P>(b,0x147938,sizeof(NeighborRoster)));
  neighborRosterUser=user;neighborRosterBlocked=false;if(!neighborRoster)return false;
  *neighborRoster=NeighborRoster{};I found=readRoster(b,*neighborRoster,user);
  if(found<0){neighborRosterBlocked=true;economyNotice(b,"[V38_PVP_SAVE_ERROR]");return false;}
  if(!found){auto&r=*neighborRoster;r.magic=0x4e425650;r.version=1;r.user=user;r.rng=neighborMix(user^realNow(b)^0x952a1837);
   U slot=0;for(U i=0;i<NPC_COUNT;++i)if(!NPCS[i].evil)r.entries[slot++].id=NPCS[i].id;
  }
 }
 if(neighborRosterBlocked)return false;
 bool needed=false;
#ifdef PVP_UNIQUE_NEIGHBORS
 needed=neighborRoster->version<2;
#endif
 for(U i=0;i<NEIGHBOR_SLOT_COUNT;++i){const auto&e=neighborRoster->entries[i];const NpcPreset*n=npc(e.id);if(n&&regionOpen(n->zone)&&!e.seed)needed=true;
#ifdef PVP_GITHUB_PRESETS
  if(e.kind>=1&&e.kind<=7&&!e.title[0])needed=true;
#endif
  for(U k=0;k<e.count;++k)if(!neighborPlant(e.plants[k].type))needed=true;}
 if(!needed)return true;
 auto*next=reinterpret_cast<NeighborRoster*>(call<P>(b,0x147938,sizeof(NeighborRoster)));if(!next)return false;*next=*neighborRoster;
#ifdef PVP_UNIQUE_NEIGHBORS
 migrateNeighborRoster(*next);
#endif
 for(auto& e:next->entries){
  const NpcPreset*n=npc(e.id);
  if(n&&regionOpen(n->zone)&&!e.seed)generateRosterNeighbor(*next,e,e.id,neighborRandom(next->rng));
 }
 ++next->sequence;bool ok=saveRoster(b,*next);
 if(ok){*neighborRoster=*next;log(b,"neighbors-generated",next->sequence,NEIGHBOR_SLOT_COUNT);}else economyNotice(b,"[V38_PVP_SAVE_ERROR]");
 call<void>(b,0x147950,next);return ok;
}
#ifdef PVP_VISITOR_MAP_FIX
#include "vacant_neighbor.h"
#endif
static const NeighborEncounter* encounter(U b,U id){
 if(!ensureNeighborRoster(b,manager(b)))return nullptr;
#ifdef PVP_VISITOR_MAP_FIX
 if(id==VACANT_HOME.id)return vacantNeighbor(b);
#endif
 return findEncounter(*neighborRoster,id);
}
static void projectDynamicNeighbor(U b,P m,const NpcPreset&n){
#ifdef PVP_DISTRICT_SHOPS
 if(const auto* shop=businessPlot(n.zone,n.position))if(activeBusiness(*shop))return;
#endif
 const auto*e=encounter(b,n.id);if(!e||!e->seed)return;
 U title[40]{};neighborName(e->seed,e->kind,title);
 const U*displayName=title;
#ifdef PVP_GITHUB_PRESETS
 if(e->kind==SHARED_NEIGHBOR)displayName=e->title;
#endif
 alignas(8) U record[16]={n.id,0,0,n.level,e->cups,0,THREE_STAR_RAID_COINS,n.zone,n.position,1,0,0,0,0,NEIGHBOR_ATTACK_FEE,0};
#ifdef PVP_NEIGHBOR_PROTECTION
 record[5]=starCups(3);
 if(U until=neighborProtectionUntil(b,n)){
  record[9]=2;
  record[10]=until;
 }
#endif
 char alloc=0;call<void>(b,0x14eb451,reinterpret_cast<P>(record)+8,displayName,&alloc);
 call<void>(b,0x104678c,m,record);release(b,reinterpret_cast<P>(record[2]),true);
}
extern "C" void offlinePvpPanelReady(U b,P panel){
 offlineRegionPanelReady(b,panel);neighborPanel=nullptr;
#ifdef PVP_BUSINESS_REPLACE
 businessReplacePanel=nullptr;
 if(panel&&at<U>(panel,0xa4)==3&&localBusinessPanel(b,panel)){
  businessReplacePanel=panel;businessReplaceUser=owner(b);
 }
#endif
 if(panel&&regular(b)&&at<U>(panel,0xa4)==5){neighborPanel=panel;neighborPanelUser=owner(b);}
}
static U neighborAction(U b,P panel,U button){
 if(button!=204||!panel||!regular(b)||at<U>(panel,0xa4)!=5)return 0;
 if(panel!=neighborPanel||neighborPanelUser!=owner(b))return 1;
 const NpcPreset*n=nullptr;
 for(U i=0;i<NPC_COUNT;++i)if(!NPCS[i].evil&&NPCS[i].zone==at<U>(panel,0xac)&&NPCS[i].position==at<U>(panel,0xa8)){n=NPCS+i;break;}
#ifdef PVP_VISITOR_MAP_FIX
 if(!n&&at<U>(panel,0xac)==1&&at<U>(panel,0xa8)==1)n=&VACANT_HOME;
#endif
 if(!n||!ensureNeighborRoster(b,manager(b))||!regionOpen(n->zone))return 1;
#ifdef PVP_NEIGHBOR_PROTECTION
 if(rejectProtectedNeighbor(b,*n))return 1;
#endif
 P map=at<P>(panel,0xc0);if(!map)return 1;
#ifdef PVP_VISITOR_MAP_FIX
 if(n==&VACANT_HOME){
  if(replaceVacantNeighbor(b)){
   projectDynamicNeighbor(b,manager(b),*n);neighborPanel=nullptr;
   call<void>(b,0x100a864,map);call<void>(b,0x1019668,map,5,1,1);
  }else economyNotice(b,"[V38_PVP_SAVE_ERROR]");
  return 1;
 }
#endif
 auto*next=reinterpret_cast<NeighborRoster*>(call<P>(b,0x147938,sizeof(NeighborRoster)));if(!next)return 1;*next=*neighborRoster;
 auto*entry=findEncounter(*next,n->id);const auto*old=findEncounter(*neighborRoster,n->id);
 U excludeShared=0;
#ifdef PVP_GITHUB_PRESETS
 if(old->kind==SHARED_NEIGHBOR||old->kind==1)excludeShared=old->seed;
#endif
 generateRosterNeighbor(*next,*entry,n->id,neighborRandom(next->rng),excludeShared);
 U kind=entry->kind;
 for(U attempt=0;attempt<16;++attempt){
#ifdef PVP_GITHUB_PRESETS
  if(entry->kind==SHARED_NEIGHBOR||entry->kind==1)break;
#endif
  bool sameName=false;if(kind==old->kind&&(kind==0||kind==4)){U a[40]{},c[40]{};neighborName(entry->seed,kind,a);neighborName(old->seed,kind,c);sameName=true;for(U i=0;i<40;++i)if(a[i]!=c[i])sameName=false;}
  if(!sameName&&(kind==1||entry->cups!=old->cups))break;
  generateRosterNeighbor(*next,*entry,n->id,neighborRandom(next->rng),excludeShared,false);
 }

 ++next->sequence;bool ok=saveRoster(b,*next);
 if(ok){*neighborRoster=*next;projectDynamicNeighbor(b,manager(b),*n);log(b,"neighbor-replaced",n->id,entry->cups);
  U zone=n->zone,pos=n->position;neighborPanel=nullptr;call<void>(b,0x100a864,map);call<void>(b,0x1019668,map,5,zone,pos);
 }else economyNotice(b,"[V38_PVP_SAVE_ERROR]");
 call<void>(b,0x147950,next);return 1;
}

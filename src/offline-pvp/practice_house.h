// The street has a fixed set of native building plots. Prefer an unused
// residential plot, then temporarily display the practice house over a local
// neighbor. The neighbor's saved data stays in the roster.
static bool localMapVector(P first,P end){
 return end>=first&&U(end-first)<=64*256&&U(end-first)%64==0;
}
static void removePracticeHouse(U b,P m){
 P first=at<P>(m,0x128),end=at<P>(m,0x12c);
 if(!first||!localMapVector(first,end))return;
 P out=first;
 for(P row=first;row<end;row+=64){
  if(at<U>(row,0)==PRACTICE_HOUSE){release(b,at<P>(row,8),true);continue;}
  if(out!=row)bytes(out,row,64);
  out+=64;
 }
 at<P>(m,0x12c)=out;
}
static U practiceDistrict(){
 for(U zone=6;zone>=1;--zone)if(regionOpen(zone))return zone;
 return 0;
}
static P practiceHouseRecord(U b,P m){
 const auto& r=economyRuntime;
 if(!regular(b)||!r.loaded||r.blocked||r.user!=owner(b))return nullptr;
 P first=at<P>(m,0x128),end=at<P>(m,0x12c);
 if(!first||!localMapVector(first,end))return nullptr;
 U zone=practiceDistrict();
 for(P row=first;row<end;row+=64)
  if(at<U>(row,0)==PRACTICE_HOUSE&&at<U>(row,28)==zone)return row;
 return nullptr;
}
static void projectPracticeHouse(U b,P m){
 if(!regular(b)||!ensureEconomy(b,m))return;
 U zone=practiceDistrict();if(!zone)return;
 P first=at<P>(m,0x128),end=at<P>(m,0x12c),shops=at<P>(m,0x110),shopEnd=at<P>(m,0x114);
 if(!localMapVector(first,end)||!localMapVector(shops,shopEnd))return;
 U open[3]{},neighbors[3]{},openCount=0,neighborCount=0;
 U start=zone==1?3:1;
 // Keep the visitor's plot available to its new neighbor after his final
 // result, even when the visit has already been acknowledged.
 U cycle=economyRuntime.state.daveRefreshDay;
 const NpcPreset* visitor=zone==1&&cycle?npc(daveTargetForCycle(owner(b),cycle)):nullptr;
 for(U pos=start;pos<start+3;++pos){
  if(visitor&&visitor->position==pos)continue;
  bool shop=false;
  for(P row=shops;row<shopEnd;row+=64)if(at<U>(row,48)==zone&&at<U>(row,52)==pos){shop=true;break;}
  if(shop)continue;
  P resident=nullptr;
  for(P row=first;row<end;row+=64)if(at<U>(row,28)==zone&&at<U>(row,32)==pos){resident=row;break;}
  if(!resident)open[openCount++]=pos;
  else if(const auto* n=npc(at<U>(resident,0));n&&!n->evil)neighbors[neighborCount++]=pos;
 }
 U count=openCount?openCount:neighborCount;if(!count)return;
 U seed=neighborMix(owner(b)^0x129f7e5bu^(zone*0x9e3779b9u));
 U pos=(openCount?open:neighbors)[neighborRemainder(seed,count)];
 alignas(8) U record[16]={PRACTICE_HOUSE,0,0,economyRuntime.state.baseLevel,0,0,0,zone,pos,1,0,0,0,0,0,0};
 char allocator=0;
 call<void>(b,0x14eb451,reinterpret_cast<P>(record)+8,U"镜像练习屋",&allocator);
 call<void>(b,0x104678c,m,record);
 release(b,reinterpret_cast<P>(record[2]),true);
 log(b,"practice-house-placed",zone,pos);
}
static bool practiceHousePanel(U b,P panel){
 if(!panel||at<U>(panel,0xa4)!=5)return false;
 P record=practiceHouseRecord(b,manager(b));
 return record&&at<U>(record,28)==at<U>(panel,0xac)&&at<U>(record,32)==at<U>(panel,0xa8);
}
static bool practiceHouseRequest(U b,P m,U id,U reason){
 if(id!=PRACTICE_HOUSE&&(id||at<U>(m,0x104)!=PRACTICE_HOUSE))return false;
 P record=practiceHouseRecord(b,m);
 if(!record||at<U>(record,28)!=at<U>(m,0xfc)||at<U>(record,32)!=at<U>(m,0xf8))return true;
 bool scouting=reason==3||reason==4;
 if(!scouting&&reason!=1&&reason!=2)return true;
 if(economyRuntime.state.battleOpen)return true;
 if(!scouting){
  bool army=false;
  for(const auto& train:economyRuntime.state.trains)if(train.held){army=true;break;}
  if(!army){
   if(practiceArena(b))at<unsigned char>(m,0x100)=1;
   economyNotice(b,"[V80_ARMY_REQUIRED]");return true;
  }
 }
 P live=practiceArena(b)?arenaModule(b):nullptr;
 if(live&&armyBankBoard&&at<U>(armyBankBoard,0xc0)!=9){
  if(at<U>(live,0xb0)==3)return true;
  if(at<U>(live,0xb0)==2){
   if(!scouting){
    at<unsigned char>(m,0x100)=0;
    at<unsigned char>(m,0x102)=at<unsigned char>(m,0x103)=0;
    requestedArenaView=0;
    call<void>(b,0x1090990,live);
    log(b,"practice-battle-started",PRACTICE_HOUSE);
   }
   return true;
  }
 }
 if(arenaPending(b,"arena_battle_test",0))return true;
 clearRevenge();
 continueProtectedNeighbor=0;
#ifdef PVP_GITHUB_PRESETS
 sharedBattle=nullptr;
#endif
 Store formation{};
 // readStore can encounter a partial or invalid save. Only valid, complete
 // home data is copied into the native formation vectors.
 if(!readStore(b,formation))formation=Store{};
 finishArenaBoard(b);
 apply(b,m+0x80,formation);
 arenaNpc=PRACTICE_HOUSE;arenaUser=owner(b);
 at<U>(m,0xa8)=2;at<U>(m,0xf4)=at<U>(m,0x104)=PRACTICE_HOUSE;
 at<U64>(m,0x108)=0;
 at<unsigned char>(m,0x100)=scouting;
 at<unsigned char>(m,0x101)=at<unsigned char>(m,0x102)=at<unsigned char>(m,0x103)=0;
 loadArena(b,m,"arena_battle_test",0);
 log(b,"practice-board-loaded",scouting,formation.positions);
 return true;
}

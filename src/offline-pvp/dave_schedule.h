// Persist a single visitor slot. The ordinary roster remains underneath it,
// so refresh/restart cannot create two houses at the same map position.
static bool replaceDaveNeighbor(U b,U id,U cycle){
 auto*old=findEncounter(*neighborRoster,id);if(!old)return false;
 U seed=neighborMix(owner(b)^id^cycle^0xd32ac765u);if(!seed)seed=1;
 // The roster can reach disk before the economy clears the replacement bit.
 if(old->kind==0&&old->seed==seed)return true;
 auto*next=call<NeighborRoster*>(b,0x147938,sizeof(NeighborRoster));if(!next)return false;
 *next=*neighborRoster;auto*entry=findEncounter(*next,id);
 generateNeighbor(*entry,id,seed,8,matchedNeighborCups(economyRuntime.state.cups,seed));
 ++next->sequence;bool ok=saveRoster(b,*next);
 if(ok)*neighborRoster=*next;
 call<void>(b,0x147950,next);return ok;
}
static bool daveCandidate(const NpcPreset&n){
 return !n.evil&&regionOpen(n.zone)
#ifdef PVP_VISITOR_MAP_FIX
 &&n.zone==1
#endif
 ;
}
static U daveTargetForCycle(U user,U cycle){
 U count=0;for(const auto&n:NPCS)if(daveCandidate(n))++count;
 if(!count)return 0;
 U pick=neighborRemainder(neighborMix(user^cycle^0x85c41d29u),count);
 for(const auto&n:NPCS)if(daveCandidate(n)){
  if(!pick)return n.id;
  --pick;
 }
 return 0;
}
static bool daveDialoguePending(const Economy& state){
 return state.daveDialogueSerial!=state.daveDialogueSeen;
}
static bool daveHouseVisible(const Economy& state){
 return state.daveActive||(state.daveReplacement&&daveDialoguePending(state));
}
static I daveVisitSeconds(U b,U cycle){
 if(!cycle)return 0;
 const U now=realNow(b);if(now<86400||now>0x7fffffff)return -1;
 P local=call<P>(b,0x147854,&now);if(!local)return -1;
 const I offset=at<I>(local,0x24);if(offset< -86400||offset>86400)return -1;
 const U day=(now+offset)/86400;if(cycle>day)return -1;if(day-cycle>1)return 0;
 I midnight[11];for(U i=0;i<11;++i)midnight[i]=at<I>(local,i*4);
 midnight[0]=midnight[1]=midnight[2]=0;
 midnight[3]-=I(day-cycle);midnight[8]=-1;
 // The visit starts at the scheduled civil midnight, but lasts 24 elapsed hours.
 const U mktime=at<U>(reinterpret_cast<P>(b),0x1822b1c);
 if(!mktime)return -1;
 const I start=call<I>(0,mktime,midnight);
 if(start<0||now<U(start))return -1;
 if(now-U(start)>=86400)return 0;
 return 86400-(now-U(start));
}
extern "C" I offlineDaveRemaining(U b,P record){
 const auto& runtime=economyRuntime;
 if(!record||at<U>(record,0x24)!=4||!regular(b)||!runtime.loaded||runtime.blocked||runtime.user!=owner(b))return -1;
 const NpcPreset* where=npc(runtime.state.daveTarget);
 if(!where||at<U>(record,0x1c)!=where->zone||at<U>(record,0x20)!=where->position)return -1;
 const I remaining=runtime.state.daveActive?daveVisitSeconds(b,runtime.state.daveRefreshDay):0;
 return remaining>0?remaining:0;
}
static bool ensureDaveSchedule(U b,P m){
 if(!ensureNeighborRoster(b,m))return false;
 U day;if(!pvpCivilDay(b,day))return false;
 Economy next=economyRuntime.state;
 const NpcPreset* paid=next.battleOpen?npc(next.battleNpc):nullptr;
 if(paid&&paid->evil){at<U>(m,0x15c)=next.daveWins;return true;}
 // Complete the current visit's dialogue before moving or replacing its house.
 if(daveDialoguePending(next)){at<U>(m,0x15c)=next.daveWins;return true;}
 // Older saves retired Dave after every win. Resume a partial cycle, even
 // when the original slot has already been restored to an ordinary neighbor.
 const bool unfinished=next.daveWins>0&&next.daveWins<DAVE_ROUND_COUNT;
 if(next.daveReplacement&&unfinished){next.daveActive=1;next.daveReplacement=0;}
 // A completed visitor becomes an ordinary (not special/shared) new neighbor.
 if(next.daveReplacement){
  if(!replaceDaveNeighbor(b,next.daveTarget,next.daveRefreshDay))return false;
  next.neighborProtectedUntil[neighborProtectionIndex(npc(next.daveTarget))]=0;
  next.daveTarget=next.daveReplacement=0;
 }
 U cycle=lastDaveRefreshDay(day);
 const bool inWindow=daveVisitSeconds(b,cycle)>0;
 if(next.daveActive&&daveVisitSeconds(b,next.daveRefreshDay)==0){
  if(!replaceDaveNeighbor(b,next.daveTarget,next.daveRefreshDay))return false;
  next.neighborProtectedUntil[neighborProtectionIndex(npc(next.daveTarget))]=0;
  next.daveTarget=next.daveActive=0;
 }
 bool moveHome=false;
#ifdef PVP_VISITOR_MAP_FIX
 const NpcPreset*prior=npc(next.daveTarget);moveHome=next.daveActive&&prior&&prior->zone!=1;
 if(moveHome&&cycle<next.daveRefreshDay)cycle=next.daveRefreshDay;
#endif
 if(inWindow&&(cycle>next.daveRefreshDay||moveHome)){
  U target=daveTargetForCycle(owner(b),cycle);if(!target)return false;
  if(next.daveActive){
   if(!replaceDaveNeighbor(b,next.daveTarget,next.daveRefreshDay))return false;
   next.neighborProtectedUntil[neighborProtectionIndex(npc(next.daveTarget))]=0;
  }
  if(cycle!=next.daveRefreshDay)next.daveWins=0;
  next.daveTarget=target;next.daveRefreshDay=cycle;next.daveActive=1;
 }else if(inWindow&&cycle==next.daveRefreshDay&&unfinished&&!next.daveActive&&next.daveTarget){
  U target=daveTargetForCycle(owner(b),next.daveRefreshDay);if(!target)return false;
  next.daveTarget=target;next.daveActive=1;
 }
 // The next scheduled visit after six wins starts a new challenge. An old
 // active save at six wins is already in a later visit and can restart here.
 if(next.daveActive&&next.daveWins==DAVE_ROUND_COUNT)next.daveWins=0;
 const Economy&old=economyRuntime.state;
 if(next.daveRefreshDay!=old.daveRefreshDay||next.daveTarget!=old.daveTarget||next.daveActive!=old.daveActive||
    next.daveReplacement!=old.daveReplacement||next.daveWins!=old.daveWins){
  ++next.sequence;if(!saveEconomy(b,next)){economyNotice(b,"[V38_PVP_SAVE_ERROR]");return false;}
  economyRuntime.state=next;log(b,"dave-schedule",next.daveRefreshDay,next.daveTarget);
 }
 at<U>(m,0x15c)=next.daveWins;
 return true;
}
static void removeScheduledDaveRecords(U b,P m){
 P first=at<P>(m,0x128),last=at<P>(m,0x12c);
 if(!first||last<first||U(last-first)>64*256||U(last-first)%64)return;
 P out=first;
 for(P p=first;p<last;p+=64){
  const NpcPreset*n=npc(at<U>(p,0));
  bool hidden=n&&(n->evil||daveHouseVisible(economyRuntime.state)&&n->id==economyRuntime.state.daveTarget);
  if(hidden){release(b,at<P>(p,8),true);continue;}
  if(out!=p)bytes(out,p,64);out+=64;
 }
 at<P>(m,0x12c)=out;
}
static bool scheduledHouseSelected(const NpcPreset&n,P m){
 const NpcPreset*where=&n;
 if(n.evil){
  if(!economyRuntime.state.daveActive)return false;
  where=npc(economyRuntime.state.daveTarget);if(!where)return false;
 }
 return where->zone==at<U>(m,0xfc)&&where->position==at<U>(m,0xf8);
}

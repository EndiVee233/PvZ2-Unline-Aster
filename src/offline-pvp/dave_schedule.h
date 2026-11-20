// Persist a single visitor slot. The ordinary roster remains underneath it,
// so refresh/restart cannot create two houses at the same map position.
static bool replaceDaveNeighbor(U b,U id,U cycle){
 auto*old=findEncounter(*neighborRoster,id);if(!old)return false;
 auto*next=call<NeighborRoster*>(b,0x147938,sizeof(NeighborRoster));if(!next)return false;
 *next=*neighborRoster;auto*entry=findEncounter(*next,id);
 U seed=neighborMix(owner(b)^id^cycle^0xd32ac765u);
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
static bool ensureDaveSchedule(U b,P m){
 if(!ensureNeighborRoster(b,m))return false;
 U day;if(!pvpCivilDay(b,day))return false;
 Economy next=economyRuntime.state;
 const NpcPreset* paid=next.battleOpen?npc(next.battleNpc):nullptr;
 if(paid&&paid->evil){at<U>(m,0x15c)=next.daveWins;return true;}
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
 bool moveHome=false;
#ifdef PVP_VISITOR_MAP_FIX
 const NpcPreset*prior=npc(next.daveTarget);moveHome=next.daveActive&&prior&&prior->zone!=1;
 if(moveHome&&cycle<next.daveRefreshDay)cycle=next.daveRefreshDay;
#endif
 if(cycle>next.daveRefreshDay||moveHome){
  U target=daveTargetForCycle(owner(b),cycle);if(!target)return false;
  if(next.daveActive){
   if(!replaceDaveNeighbor(b,next.daveTarget,next.daveRefreshDay))return false;
   next.neighborProtectedUntil[neighborProtectionIndex(npc(next.daveTarget))]=0;
  }
  next.daveTarget=target;next.daveRefreshDay=cycle;next.daveActive=1;
 }else if(unfinished&&!next.daveActive&&next.daveRefreshDay){
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
  bool hidden=n&&(n->evil||economyRuntime.state.daveActive&&n->id==economyRuntime.state.daveTarget);
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

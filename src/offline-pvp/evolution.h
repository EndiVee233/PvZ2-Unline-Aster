// The original engine still applies per-level attack/health/skills. Persist
// its per-alias grade and shared lab queue locally, alongside the wallet.
#include "evolution_presets.h"
static U evolutionTimer[0x218/4],evolutionPromptUser,evolutionPromptIndex,evolutionPromptDue;
struct EvolutionView {P ui;U index,level,mode,second;};
static EvolutionView evolutionView;
static U evolutionIndex(P name){
 if(!name||!at<P>(name,0))return TRAIN_COUNT;
 for(U i=0;i<TRAIN_COUNT;++i)if(same(reinterpret_cast<const char*>(at<P>(name,0)),TRAIN_SPECS[i].name))return i;
 return TRAIN_COUNT;
}
static bool ensureEvolution(U b,P m){
 if(!regular(b)||!ensureEconomy(b,m))return false;
 if(economyRuntime.state.evolutionInitialized)return true;
 Economy next=economyRuntime.state;next.evolutionInitialized=1;
 for(auto& level:next.evolutionLevels)level=1;
 ++next.sequence;if(!saveEconomy(b,next)){economyNotice(b,"[V38_PVP_SAVE_ERROR]");return false;}
 economyRuntime.state=next;applyEvolution(b,m);log(b,"evolution-initialized");return true;
}
static void applyEvolution(U b,P m){
 const Economy&s=economyRuntime.state;if(!s.evolutionInitialized||!regular(b))return;
 for(U i=0;i<TRAIN_COUNT;++i){
  P key=nullptr;narrow(b,reinterpret_cast<P>(&key),TRAIN_SPECS[i].name);P info=call<P>(b,0x104673c,m,&key);
  if(info||TRAIN_SPECS[i].level<=s.home){
   U entry[5]={reinterpret_cast<U>(key),s.evolutionLevels[i],1,info?at<U>(info,12):0,1};
   // Assignment uses the real native tree key and structure rather than
   // overwriting a pointer that another module may have cached.
   call<P>(b,0x1048f44,m,entry);
  }
  release(b,key);
 }

}
static void settleEvolution(U b,P m){
 if(!regular(b)||!economyRuntime.loaded||economyRuntime.user!=owner(b)||economyRuntime.blocked)return;
 const Economy&s=economyRuntime.state;if(!s.evolutionInitialized||!s.evolutionIndex||realNow(b)<s.evolutionDue)return;
 Economy next=s;U index=next.evolutionIndex-1;++next.evolutionLevels[index];next.evolutionIndex=next.evolutionDue=0;
 if(commitProgression(b,m,next))log(b,"evolution-completed",index,next.evolutionLevels[index]);
}
static U evolutionMinutes(U b){const Economy&s=economyRuntime.state;U now=realNow(b);return s.evolutionIndex&&s.evolutionDue>now?(s.evolutionDue-now+59)/60:0;}
static U evolutionPrice(U b,U minutes){return call<U>(b,0x1086e0c,reinterpret_cast<P>(evolutionTimer),minutes);}
// The cash overlay is intentionally not constructed for this local queue.
// Keep the regular native button and original layout/next-level descriptions.
extern "C" void offlineEvolutionBuild(U b,P ui){
 if(!regular(b)||evolutionIndex(ui+0xa8)==TRAIN_COUNT)return;
 if(ensureEvolution(b,manager(b)))settleEvolution(b,manager(b));
 at<unsigned char>(ui,0xbc)=0;evolutionView.ui=nullptr;
}
extern "C" void offlineEvolutionTick(U b,P ui){
 if(!regular(b))return;U index=evolutionIndex(ui+0xa8);if(index==TRAIN_COUNT||!ensureEvolution(b,manager(b)))return;
 settleEvolution(b,manager(b));const Economy&s=economyRuntime.state;
 U mode=s.evolutionIndex==index+1?1:s.evolutionIndex?2:0,level=s.evolutionLevels[index];
 bool rebuild=evolutionView.ui==ui&&evolutionView.index==index&&evolutionView.level!=level;
 evolutionView.index=index;evolutionView.level=level;evolutionView.mode=mode;
 if(rebuild){evolutionView.ui=nullptr;call<void>(b,0x107eb28,ui);}
 P button=at<P>(ui,0xc0);if(!button)return;
 if(level>=4){call<void>(0,at<U>(at<P>(button,0),0xa4),button,1);call<void>(0,at<U>(at<P>(button,0),0x8c),button,0);return;}
 // A regular button is available for 1->2, 2->3 and 3->4. Its original
 // construction preserves the star-coin icon/price whenever no queue runs.
 U now=realNow(b);bool refresh=evolutionView.ui!=ui||evolutionView.second!=now;
 evolutionView.ui=ui;evolutionView.second=now;
 call<void>(0,at<U>(at<P>(button,0),0xa4),button,mode==2||(mode==0&&s.coins<EVOLUTION_SPECS[index].cost[level-1]));
 if(mode==1&&refresh){call<void>(b,0x7e96a4,button);setInstantGemLabel(b,button,evolutionPrice(b,evolutionMinutes(b)));}
}
extern "C" U offlineEvolutionClick(U b,P ui,U button){
 if(!regular(b)||(button!=0x1e8d&&button!=0x1938))return 0;
 U index=evolutionIndex(ui+0xa8);if(index==TRAIN_COUNT)return 0;
 P m=manager(b);if(!ensureEvolution(b,m))return 1;settleEvolution(b,m);Economy next=economyRuntime.state;
 if(next.evolutionIndex==index+1){
  U minutes=evolutionMinutes(b);if(!minutes)return 1;
  evolutionPromptUser=owner(b);evolutionPromptIndex=next.evolutionIndex;evolutionPromptDue=next.evolutionDue;
  P timer=reinterpret_cast<P>(evolutionTimer);at<U>(timer,0x1f4)=minutes;
  U callback[6]={0,b+0x1080e28,0,0,1,0};evolutionFinishPrompt=true;offlineTrainingFinishPrompt(b,timer,reinterpret_cast<P>(callback));evolutionFinishPrompt=false;
  log(b,"evolution-gem-prompt",index,evolutionPrice(b,minutes));return 1;
 }
 if(next.evolutionIndex){economyNotice(b,"[V54_UPGRADE_BUSY]");return 1;}
 if(TRAIN_SPECS[index].level>next.home){economyNotice(b,"[V38_PVP_LOCKED]");return 1;}
 U level=next.evolutionLevels[index];if(level>=4)return 1;
 U cost=EVOLUTION_SPECS[index].cost[level-1];if(next.coins<cost){economyNotice(b,"[PVP_ERROR_PVPCOIN_NOT_ENOUCH]");return 1;}
 next.coins-=cost;next.evolutionIndex=index+1;next.evolutionDue=realNow(b)+EVOLUTION_SPECS[index].seconds[level-1];
 if(commitProgression(b,m,next)){log(b,"evolution-started",index,cost);call<void>(b,0x107eb28,ui);}
 return 1;
}
static U finishEvolutionWithGems(U b,P timer){
 P m=manager(b);if(!ensureEvolution(b,m))return 1;settleEvolution(b,m);Economy next=economyRuntime.state;
 if(evolutionPromptUser!=owner(b)||!next.evolutionIndex||next.evolutionIndex!=evolutionPromptIndex||next.evolutionDue!=evolutionPromptDue)return 1;
 U price=evolutionPrice(b,at<U>(timer,0x1f4));if(!price||price>15)return 1;
 if(call<I>(b,0x747d00,profile(b),price)<0){economyNotice(b,"[V41_GEMS_REQUIRED]");return 1;}
 U index=next.evolutionIndex-1;++next.evolutionLevels[index];next.evolutionIndex=next.evolutionDue=0;
 if(!commitProgression(b,m,next)){call<void>(b,0x745220,profile(b),price,1);return 1;}
 evolutionPromptUser=0;log(b,"evolution-finished-with-gems",index,price);return 1;
}

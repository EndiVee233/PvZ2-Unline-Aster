// Explicit user-approved temporary offline rates, not recovered server values.
extern "C" U offlineBusinessProductionMode(){return 1;}
static bool produceBusinesses(Economy& next,U now){
 bool changed=false;
 for(U i=0;i<BUSINESS_COUNT;++i){
  if(!(next.businessOwnedMask&(1u<<i)))continue;
  auto& stock=businessStock(next,i);
  // Old v10 ownership has no acquisition time: begin empty now, never award
  // guessed rent for the period before this feature was installed.
  if(!stock.producedAt){stock.producedAt=now;changed=true;continue;}
  if(now<stock.producedAt)continue;
  U elapsed=now-stock.producedAt,coins=stock.coins,medals=stock.medals;
  const auto& rules=BUSINESSES[i].rules;
  produce(stock.coins,stock.coinFraction,rules.coinRate,rules.coinCapacity,elapsed);
  produce(stock.medals,stock.medalFraction,rules.medalRate,rules.medalCapacity,elapsed);
  stock.producedAt=now;
  changed=changed||coins!=stock.coins||medals!=stock.medals;
 }
 return changed;
}
static void projectBusinessStocks(U b,P m){
 const EconomyRuntime&r=economyRuntime;
 if(!r.loaded||r.blocked||r.user!=owner(b))return;
 P begin=at<P>(m,0x110),end=at<P>(m,0x114);U identity=offlineBusinessIdentity(b);
 if(!begin||end<begin||U(end-begin)>64*256||U(end-begin)%64)return;
 for(P p=begin;p<end;p+=64){const BusinessPlot* plot=businessId(at<U>(p,0));
  if(!plot||at<U>(p,48)!=plot->zone||at<U>(p,52)!=plot->position)continue;
  U index=businessIndex(plot->id);bool owned=r.state.businessOwnedMask&(1u<<index);
  U64 expected=owned?U64(identity):0;
#ifdef PVP_SILENT_RAIDS
  if(!owned)expected=businessEnemy(r.state,index);
#endif
  if(at<U64>(p,8)!=expected)continue;
  const auto& stock=businessStock(r.state,index);
  const auto& rules=plot->rules;
  // An occupier retains any stock left in a captured shop. Offline rent only
  // accrues while the current player owns it.
  at<U>(p,24)=expected?stock.medals:0;at<U>(p,28)=rules.medalCapacity;
  at<U>(p,32)=expected?stock.coins:0;at<U>(p,36)=rules.coinCapacity;
  at<U>(p,40)=owned?rules.medalRate:0;at<U>(p,44)=owned?rules.coinRate:0;
 }
}

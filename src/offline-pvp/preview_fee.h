// ARENA_PVP_OCCUPY_BTN formats CURRENCY_COST both when constructed and when
// the live scout module updates its label. ARENA_PVP_BTN is a different button.
static U attackPreviewFee(U b,U original){
 const NpcPreset*n=npc(arenaNpc);
 if(arenaUser!=owner(b)||!regular(b))return original;
 if(n)return n->evil?DAVE_ATTACK_FEE:NEIGHBOR_ATTACK_FEE;
#ifdef PVP_BUSINESS_BATTLE
 if(const auto* plot=businessId(arenaNpc))return plot->rules.attackFee;
#endif
 return original;
}
extern "C" P offlineAttackPreviewFormat(U b,P out,P text,P key,U original){
 return call<P>(b,0xd06a04,out,text,key,attackPreviewFee(b,original));
}
extern "C" U offlineAttackPreviewCost(U b,P m){
 return attackPreviewFee(b,call<U>(b,0x10449b8,m));
}

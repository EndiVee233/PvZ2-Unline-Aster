// The paged bank draws arrow sprites and tests their bounds in the same local
// coordinates. Plant packets are children of that same widget.
static bool plantBankEditorBoard(P board){
 if(!board)return false;
 P name=at<P>(board,0xc4);
 return sameText(name,"arena_plant_test")||sameText(name,"arena_plant_tutorial");
}
static P resolvePlantBank(U b,P module){
 if(!at<U>(module,0x48)&&!at<U>(module,0x4c))return nullptr;
 return call<P>(b,0x1da034,call<P>(b,0x11d74b4),module+0x48);
}
static P plantBankPacket(U b,P bank,U index){
 U handle[2]{};
 call<void>(b,0x895f0c,handle,bank,index);
 P packet=handle[0]||handle[1]?call<P>(b,0x1da034,call<P>(b,0x11d74b4),handle):nullptr;
 call<void>(b,0x1d9bb4,handle,0,0,0);
 return packet;
}
static void centerPlantBank(U b,P app,P bank){
 if(!bank||at<unsigned char>(bank,0x13e))return;
 U count=at<unsigned char>(bank,0x11d),perPage=at<U>(bank,0x14c),page=at<U>(bank,0x148);
 if(!count||!perPage||perPage>128||page>=count)return;
 U first=page*perPage,end=first+perPage;
 if(first>=count)return;
 if(end>count)end=count;
 P left=plantBankPacket(b,bank,first);
 P right=end-first>1?plantBankPacket(b,bank,end-1):left;
 if(!left||!right)return;
 I leftX=at<I>(left,0x28),rightX=at<I>(right,0x28),lastWidth=at<I>(right,0x30);
 I width=at<I>(app,0x524);
 if(width<1||width>32768||leftX<0||rightX<leftX||rightX>width||lastWidth<1||lastWidth>width)return;
 I cardWidth=rightX-leftX+lastWidth;
 if(cardWidth>width)return;
 I box[4]{};
 call<void>(b,0x97636c,box,bank);
 I offset=(width-cardWidth)/2-(box[0]+leftX);
 if(offset)call<void>(b,0x9766cc,bank,at<float>(bank,0x5c)+float(offset),at<float>(bank,0x60));
}
extern "C" void offlineCenterPvpPlantBank(U b,P bank){
 P holder=at<P>(reinterpret_cast<P>(b),0x1821674);
 P app=holder?at<P>(holder,0):nullptr;
 P board=app?at<P>(app,0x6bc):nullptr;
 if(!bank||!plantBankEditorBoard(board))return;
 P modules=at<P>(board,0x938);
 P module=modules?call<P>(b,0x43af38,modules,call<P>(b,0x10290ac)):nullptr;
 if(module&&resolvePlantBank(b,module)==bank)centerPlantBank(b,app,bank);
}

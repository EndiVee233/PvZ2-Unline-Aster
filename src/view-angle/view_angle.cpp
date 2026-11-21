// Aster start-menu setting. Use the game's settings rows and transition.
// Shared ARM32 guest code, including the ARM64 bridge build.
using U=unsigned; using I=int; using P=unsigned char*;
template<class T> static T& at(P p,U o){return *reinterpret_cast<T*>(p+o);}
template<class R,class... A> static R call(U b,U o,A... a){return reinterpret_cast<R(*)(A...)>(b+o)(a...);}
template<class R,class... A> static R imported(U b,U o,A... a){return reinterpret_cast<R(*)(A...)>(at<U>(reinterpret_cast<P>(b),o))(a...);}
static bool loaded,normal;
static P settings;
static const char path[]="/data/data/com.pvz2unline.aster/files/userdataNo_Backup/view-angle.bin";
static const char temporary[]="/data/data/com.pvz2unline.aster/files/userdataNo_Backup/view-angle.tmp";
static constexpr U magic=0x31564155; // UAV1: magic, selection, complement.

static void load(U b){
 if(loaded)return;
 loaded=true;
 I fd=imported<I>(b,0x1822ebc,path,0,0);
 if(fd<0)return;
 U data[3]={};char extra;
 I n=imported<I>(b,0x1822ec4,fd,data,12U);
 I tail=n==12?imported<I>(b,0x1822ec4,fd,&extra,1U):-1;
 imported<I>(b,0x1822bd4,fd);
 if(n==12&&tail==0&&data[0]==magic&&data[1]<=1&&data[2]==~data[1])normal=data[1];
}
static bool save(U b,bool value){
 U data[3]={magic,U(value),~U(value)};
 I fd=imported<I>(b,0x1822ebc,temporary,0x241,0600);
 if(fd<0)return false;
 bool ok=imported<I>(b,0x1822f40,fd,data,12U)==12;
 if(ok)ok=imported<I>(b,0x1822f44,fd)==0;
 if(imported<I>(b,0x1822bd4,fd)!=0)ok=false;
 if(ok)ok=imported<I>(b,0x1822cc8,temporary,path)==0;
 if(!ok)imported<I>(b,0x1822ccc,temporary);
 return ok;
}
static P app(U b){P holder=at<P>(reinterpret_cast<P>(b),0x1821674);return holder?at<P>(holder,0):nullptr;}
static void wide(U b,P* result,const U* text){char allocator=0;call<void>(b,0x14eb451,result,text,&allocator);}
static void release(U b,P text){if(text){char allocator=0;call<void>(b,0x14ea239,text-12,&allocator);}}
extern "C" void asterViewSettingsReady(U b,P ui){
 load(b);
 P scroll=at<P>(ui,0xbc);if(!scroll)return;
 P arrow=call<P>(b,0x1dd8f0,reinterpret_cast<P>(b+0x1848a98));if(!arrow)return;
 static const U label[]={0x89c6,0x89d2,0};
 P title=nullptr;wide(b,&title,label);
 P row=call<P>(b,0x8e4898,ui,1005U,&title,arrow);
 call<void>(b,0x8e5924,scroll,row);release(b,title);
}
extern "C" U asterViewClick(U b,P ui,U id){
 if(id<=1){if(settings==ui)settings=nullptr;return 0;}
 if(id==1005){
  if(at<P>(ui,0xc0)||at<U>(ui,0xd4))return 1;
  load(b);settings=ui;return 2;
 }
 if(settings!=ui||!settings||(id!=1041&&id!=1042))return 0;
 bool value=id==1042;
 if(value!=normal&&save(b,value))normal=value;
 call<void>(b,0x8e7820,ui); // Stock rebuild updates both check marks.
 return 1;
}
extern "C" U asterViewTitle(U b,P holder){
 if(!settings)return 0;
 static const U text[]={0x89c6,0x89d2,0};
 P title=nullptr;wide(b,&title,text);
 call<void>(b,0x14e9b0d,holder+0xa0,&title);release(b,title);return 1;
}
extern "C" U asterViewRows(U b,P scroll,P description){
 if(!settings)return 0;
 call<void>(b,at<U>(at<P>(description,0),4)-b,description);
 static const U labels[2][3]={{0x9ad8,0,0},{0x6b63,0x5e38,0}};
 for(U i=0;i<2;++i){
  P title=nullptr;wide(b,&title,labels[i]);
  P row=call<P>(b,0x8e4edc,settings,1041+i,&title,U(normal==(i==1)));
  call<void>(b,0x8e5924,scroll,row);release(b,title);
 }
 return 1;
}
// Iris 1.6.2 scopes a native RenderDevice matrix around world draw entries
// (0x197198 / 0x7d91cc) and inverts it for Board touches (0x1841fc).
// Aster's equivalent native push/pop are 0x116c9ac / 0x116c9f0.
// Do not alter application scale, resource dimensions or Board coordinates:
// those fields are also used by baked backgrounds, UI layout and save data.
static constexpr float zoom=1.2f;
struct ViewDrawContext {U base;P graphics,device;float matrix[9];bool ui;ViewDrawContext* prior;};
static ViewDrawContext* drawing;
static P lastDrawBoard;
static I lastDrawX,lastDrawY;
static bool active(U b,P board){
 load(b);P a=app(b);
 return normal&&a&&board&&at<P>(a,0x6bc)==board&&at<P>(board,0x938);
}
static bool arena(P board){
 const char* level=board?at<const char*>(board,0xc4):nullptr;
 return level&&level[0]=='a'&&level[1]=='r'&&level[2]=='e'&&level[3]=='n'&&level[4]=='a'&&level[5]=='_';
}
extern "C" void asterViewDraw(U b,P board,P graphics){
 constexpr U camera=0x1a2b1c4;
 if(!active(b,board)||!graphics){call<void>(b,camera,board,graphics);return;}
 P device=call<P>(b,0x1166bc4,graphics);
 if(!device){call<void>(b,camera,board,graphics);return;}
 P a=app(b);
 float right=float(at<I>(a,0x524));
 float bottom=at<float>(graphics,12)+540.0f*at<float>(a,0x690);
 lastDrawBoard=board;lastDrawX=I(at<float>(graphics,8));lastDrawY=I(at<float>(graphics,12));
 static U geometryTraces;
 if(arena(board)&&geometryTraces++<8)call<void>(b,0x147adc,4,"AsterPvpView","draw board=%d,%d graphics=%d,%d scale1000=%d width=%d",at<I>(board,0x2c),at<I>(board,0x30),I(at<float>(graphics,8)),I(at<float>(graphics,12)),I(at<float>(a,0x690)*1000),at<I>(a,0x524));
 // Row-major native SexyTransform2D: T(anchor) * S(zoom) * T(-anchor).
 ViewDrawContext context={b,graphics,device,{zoom,0,right*(1-zoom),0,zoom,bottom*(1-zoom),0,0,1},false,drawing};
 drawing=&context;
 call<void>(b,0x116c9ac,device,context.matrix,1U);
 call<void>(b,camera,board,graphics);
 call<void>(b,0x116c9f0,device);
 drawing=context.prior;
}
extern "C" __attribute__((visibility("hidden"))) void asterViewUiEntry(P data,P graphics){
 // data points at the embedded delegate object. Its first word is a vptr,
 // which native record sorting deliberately does not copy.
 P node=at<P>(data,4);U b=at<U>(data,8);
 if(!node)return;
 ViewDrawContext* context=drawing;
 bool suspend=context&&context->graphics==graphics&&!context->ui;
 if(suspend){context->ui=true;call<void>(b,0x116c9f0,context->device);}
 // Kind 12 also saves/restores Graphics state around the node's draw.
 call<void>(b,0x116d800,graphics);
 reinterpret_cast<void(*)(P,P)>(at<U>(at<P>(node,0),0))(node,graphics);
 call<void>(b,0x116d764,graphics);
 if(suspend){call<void>(b,0x116c9ac,context->device,context->matrix,1U);context->ui=false;}
}
extern "C" void asterViewScreenDraw(U b,P object,P graphics,U original){
 // Native screen messages already use viewport dimensions and UI scale.
 // Remove only our extra lawn matrix; native Graphics state, text bounds,
 // timers and any effect-owned identity matrix remain the original code's.
 ViewDrawContext* context=drawing;
 bool suspend=context&&context->base==b&&context->graphics==graphics&&!context->ui;
 if(suspend){context->ui=true;call<void>(b,0x116c9f0,context->device);}
 call<void>(b,original,object,graphics);
 if(suspend){call<void>(b,0x116c9ac,context->device,context->matrix,1U);context->ui=false;}
}
extern "C" void asterViewCollectUi(U b,P records,U* count){
 U first=count?*count:4096;
 call<void>(b,0x9779a0,records,count);
 if(!drawing||!records||!count||first>*count||*count>4096)return;
 // Native UIWidget collection appends kind 12 entries (embedded draw node).
 // Keep the z-order and use the existing kind 15 delegate ABI. The payload
 // travels with its record through the native sort; it has no self pointers.
 for(U i=first;i<*count;++i){
  U* record=reinterpret_cast<U*>(records+i*36);
  if(record[0]!=12)continue;
  U node=record[8];
  record[0]=15;record[3]=node;record[4]=b;
  record[7]=reinterpret_cast<U>(&asterViewUiEntry);
 }
}
static I floorPoint(float value){I n=I(value);return float(n)>value?n-1:n;}
static I inverseAxis(I point,I offset,float origin){
 // Preserve Iris's float operation order and floor-before-translation rule.
 float delta=(float(offset)+(float(point)-origin))/zoom;
 return I(double(origin-float(offset))+double(floorPoint(delta)));
}
extern "C" void asterViewPoint(U b,P board,I* point){
 if(!point||!active(b,board))return;
 P a=app(b);
 // WidgetManager has already subtracted Board's absolute origin.
 float right=float(at<I>(a,0x524));
 float bottom=float(at<I>(board,0x30))+540.0f*at<float>(a,0x690);
 point[0]=inverseAxis(point[0],at<I>(board,0x2c),right);
 point[1]=inverseAxis(point[1],at<I>(board,0x30),bottom);
}
extern "C" P asterViewSkillBoard(U b){
 P a=app(b);return a?at<P>(a,0x6bc):nullptr;
}
extern "C" void asterViewGridPoint(U b,P out,P board,I* point){
 I local[2]={point[0],point[1]};asterViewPoint(b,board,local);
 call<void>(b,0x204930,out,board,local);
}
extern "C" void asterViewPickupRect(U b,P cursor,I* rectangle){
 // These two callers obtain the rectangle from SeedPacket / PlantfoodUI,
 // subtract Board's origin, and pass physical UI pixels to the base setter.
 call<void>(b,0x1eff40,cursor,rectangle);
 P a=app(b);P board=a?at<P>(a,0x6bc):nullptr;
 if(!cursor||!rectangle||!active(b,board)||rectangle[2]<=0||rectangle[3]<=0)return;
 I first[2]={rectangle[0],rectangle[1]};
 I last[2]={rectangle[0]+rectangle[2]-1,rectangle[1]+rectangle[3]-1};
 asterViewPoint(b,board,first);asterViewPoint(b,board,last);
 float inverse=1.0f/at<float>(a,0x690);
 I left=I(float(first[0])*inverse),top=I(float(first[1])*inverse);
 I right=I(float(last[0])*inverse),bottom=I(float(last[1])*inverse);
 // Include the last representable cursor position in this pixel rectangle.
 at<I>(cursor,0xc)=left;at<I>(cursor,0x10)=top;
 at<I>(cursor,0x14)=right-left+1;at<I>(cursor,0x18)=bottom-top+1;
 static U traces;
 if(traces++<24)call<void>(b,0x147adc,4,"AsterViewInput","pickup cursor=%p type=%x ui=%d,%d,%d,%d world=%d,%d,%d,%d",cursor,at<U>(cursor,0)-b,rectangle[0],rectangle[1],rectangle[2],rectangle[3],left,top,right-left+1,bottom-top+1);
}
struct ViewTouch {U id,pad;I x,y,px,py,taps,pad2;U time[2],phase;};
extern "C" void asterViewCopyTouch(U b,P board,const ViewTouch* event,ViewTouch* out){
 *out=*event;asterViewPoint(b,board,&out->x);
 if(out->px!=-1||out->py!=-1)asterViewPoint(b,board,&out->px);
}
struct ViewInputContext {U base;const ViewTouch* ui;ViewInputContext* prior;};
static ViewInputContext* input;
extern "C" void asterViewPvpTrace(U b,U site,U* saved){
 P a=app(b);P board=a?at<P>(a,0x6bc):nullptr;
 if(!saved||!arena(board))return;
 static U traceCounts[5];
 bool cursorEvent=site==0x1ef560;
 if(cursorEvent||site==0x108c474){
  ViewTouch* event=reinterpret_cast<ViewTouch*>(saved[1]);
  if(!event||(event->phase!=0&&event->phase!=3&&event->phase!=4))return;
 }
 U index=cursorEvent?0:site==0x108c474?1:site==0x109133c?2:site==0x10a1afc?3:4;
 if(traceCounts[index]++>=64)return;
 P object=reinterpret_cast<P>(saved[0]);
 U type=object?at<U>(object,0)-b:0;
 if(!cursorEvent)call<void>(b,0x147adc,4,"AsterPvpView","geometry site=%x board=%d,%d draw=%d,%d scale1000=%d width=%d state=%u",site,at<I>(board,0x2c),at<I>(board,0x30),lastDrawBoard==board?lastDrawX:-1,lastDrawBoard==board?lastDrawY:-1,I(at<float>(a,0x690)*1000),at<I>(a,0x524),at<U>(board,0xc0));
 if(cursorEvent||site==0x108c474){
  ViewTouch* event=reinterpret_cast<ViewTouch*>(saved[1]);if(!event)return;
  call<void>(b,0x147adc,4,"AsterPvpView","input site=%x normal=%u type=%x phase=%u event=%d,%d ui=%d,%d cursor=%d,%d origin=%d,%d scale1000=%d",site,U(normal),type,event->phase,event->x,event->y,input?input->ui->x:-1,input?input->ui->y:-1,cursorEvent?at<I>(object,4):0,cursorEvent?at<I>(object,8):0,at<I>(board,0x2c),at<I>(board,0x30),I(at<float>(a,0x690)*1000));
 }else if(site==0x109133c){
  I point[2]={I(saved[1]),I(saved[2])},cell[2]={};
  call<void>(b,0x108c578,cell,object,point);
  call<void>(b,0x147adc,4,"AsterPvpView","zombie-drop normal=%u point=%d,%d cell=%d,%d",U(normal),point[0],point[1],cell[0],cell[1]);
 }else{
  P cursor=site==0x1030ae8?reinterpret_cast<P>(saved[1]):object;
  if(!cursor)return;
  I cell[2]={};call<void>(b,0x4e5954,cell,cursor);
  call<void>(b,0x147adc,4,"AsterPvpView","action site=%x normal=%u type=%x pos=%d,%d cell=%d,%d",site,U(normal),at<U>(cursor,0)-b,at<I>(cursor,4),at<I>(cursor,8),cell[0],cell[1]);
 }
}
extern "C" void asterViewPvpQueryTrace(U b,U site,U* saved){
 P a=app(b);P board=a?at<P>(a,0x6bc):nullptr;
 if(!saved||!arena(board))return;
 static U previewTraces,effectTraces;
 if(site==0x105a220){if(previewTraces++>=24)return;}
 else if(effectTraces++>=32)return;
 P out=reinterpret_cast<P>(saved[0]),point=reinterpret_cast<P>(saved[2]);
 if(!out||!point)return;
 U first=at<U>(out,0),end=at<U>(out,4);
 U count=end>=first&&(end-first)%4==0&&(end-first)<=4096*4?(end-first)/4:0xffffffff;
 call<void>(b,0x147adc,4,"AsterPvpView","query site=%x normal=%u point1000=%d,%d targets=%u",site,U(normal),I(at<float>(point,0)*1000),I(at<float>(point,4)*1000),count);
}
extern "C" U asterViewPlantfoodPurchase(U b,P ui,ViewTouch* event,U original){
 ViewInputContext* context=input;
 if(!context||context->base!=b||!event)return call<U>(b,original,ui,event);
 // This purchase listener is registered in Board's world dispatcher, but
 // its + button and offer rectangles are computed/drawn in UI coordinates.
 ViewTouch local=*event;
 local.x=context->ui->x;local.y=context->ui->y;
 local.px=context->ui->px;local.py=context->ui->py;
 U result=call<U>(b,original,ui,&local);
 static U traces;
 if(traces++<32)call<void>(b,0x147adc,4,"AsterViewInput","plantfood-buy phase=%u world=%d,%d ui=%d,%d result=%u capture=%u offer=%u",event->phase,event->x,event->y,local.x,local.y,result,at<U>(ui,0x108),U(at<unsigned char>(ui,0x105)));
 return result;
}
extern "C" U asterViewFixedButton(U b,P ui,ViewTouch* event,U original){
 ViewInputContext* context=input;
 if(!context||context->base!=b||!event)return call<U>(b,original,ui,event);
 ViewTouch local=*event;
 local.x=context->ui->x;local.y=context->ui->y;
 local.px=context->ui->px;local.py=context->ui->py;
 U type=at<U>(ui,0)-b;
 U result=call<U>(b,original,ui,&local);
 static U traces;
 if((event->phase==0||event->phase==3||event->phase==4)&&traces++<32)call<void>(b,0x147adc,4,"AsterViewInput","fixed-button type=%x phase=%u world=%d,%d ui=%d,%d result=%u",type,event->phase,event->x,event->y,local.x,local.y,result);
 return result;
}
extern "C" U asterViewTouch(U b,P board,P handler,ViewTouch* event){
 if(!event||!active(b,board))return call<U>(b,0x3476ac,handler,event);
 ViewTouch transformed=*event;
 asterViewPoint(b,board,&transformed.x);
 if(transformed.px!=-1||transformed.py!=-1)asterViewPoint(b,board,&transformed.px);
 ViewInputContext context={b,event,input};input=&context;
 U result=call<U>(b,0x3476ac,handler,&transformed);
 input=context.prior;return result;
}
extern "C" void asterViewDesktopCursor(U b,P board,P cursor,I* point){
 if(point&&active(b,board)&&at<P>(board,0x94c)==cursor){
  I copy[2]={point[0],point[1]};asterViewPoint(b,board,copy);
  call<void>(b,0x1efccc,cursor,copy);return;
 }
 call<void>(b,0x1efccc,cursor,point);
}
extern "C" void asterViewTraceShortcut(U b,P board,U stage,P target){
 static U count;if(count++>=32)return;
 P pending=board?at<P>(board,0x94c):nullptr;P cursor=pending;
 if(!cursor&&board){P first=at<P>(board,0x940),last=at<P>(board,0x944);if(first&&last>first&&U(last-first)<=128)cursor=at<P>(last-4,0);}
 call<void>(b,0x147adc,4,"AsterViewInput","key stage=%u target=%p pending=%p cursor=%p type=%x finished=%u pos=%d,%d",stage,target,pending,cursor,cursor?at<U>(cursor,0)-b:0,cursor?U(at<unsigned char>(cursor,0x1d)):0,cursor?at<I>(cursor,4):0,cursor?at<I>(cursor,8):0);
}
extern "C" void asterViewTraceFinish(U b,P cursor,U caller){
 if(!cursor)return;U type=at<U>(cursor,0)-b;
 if(type!=0x179b940&&type!=0x179b990)return;
 static U count;if(count++>=32)return;
 call<void>(b,0x147adc,4,"AsterViewInput","finish caller=%x cursor=%p type=%x finished=%u dragged=%u kept=%u pos=%d,%d pickup=%d,%d,%d,%d",caller-b,cursor,type,U(at<unsigned char>(cursor,0x1d)),U(at<unsigned char>(cursor,0x1f)),U(at<unsigned char>(cursor,0x1e)),at<I>(cursor,4),at<I>(cursor,8),at<I>(cursor,0xc),at<I>(cursor,0x10),at<I>(cursor,0x14),at<I>(cursor,0x18));
}

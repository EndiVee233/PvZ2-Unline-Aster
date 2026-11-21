// CPU-only checks using production cache and queue code; isolated test root.
#include <assert.h>
#include <chrono>
#include "glshim.cpp"
using namespace std::chrono_literals;
static std::vector<uint8_t> uploaded;
static int upload_width, sub_uploads;
static void texture(GLenum,GLint,GLint,GLsizei w,GLsizei h,GLint,GLenum,GLenum,const void *p){
    upload_width=w;uploaded.assign((size_t)w*h*4,0);
    if(p)memcpy(uploaded.data(),p,uploaded.size());
}
static void subtexture(GLenum,GLint,GLint x,GLint y,GLsizei w,GLsizei h,GLenum,GLenum,const void *p){
    assert(x==0 && w==upload_width);++sub_uploads;
    memcpy(uploaded.data()+(size_t)y*w*4,p,(size_t)w*h*4);
}
static void demand_test(const char *fixture,bool warm){
    FILE *f=fopen(fixture,"rb");assert(f);uint8_t header[16];assert(fread(header,1,16,f)==16);
    int w=header[7]|header[8]<<8|header[9]<<16,h=header[10]|header[11]<<8|header[12]<<16;
    assert(header[4]==5 && header[5]==5 && w>0 && h>0);
    size_t bytes=(size_t)((w+4)/5)*((h+4)/5)*16;
    std::vector<uint8_t> astc(bytes),serial((size_t)w*h*4);
    assert(fread(astc.data(),1,bytes,f)==bytes);fclose(f);
    uint64_t hash=astc_hash(astc.data(),bytes,w,h,0x93b2,bytes);
    char path[256];snprintf(path,sizeof(path),PVZ2_GL_CACHE_ROOT "/glcache/%016llx.rgba",(unsigned long long)hash);
    if(!warm)unlink(path);
    use_wsa_decoder=true;real_tex=texture;real_sub=subtexture;
    glCompressedTexImage2D(GL_TEXTURE_2D,0,0x93b2,w,h,0,bytes,astc.data());
    assert(warm ? sub_uploads==0 : sub_uploads>0);
    assert(astc_codec::ASTCDecompressToRGBA(astc.data(),bytes,w,h,astc_codec::FootprintType::k5x5,serial.data(),serial.size(),(size_t)w*4));
    assert(uploaded==serial);
    struct stat st;assert(stat(path,&st)==0 && st.st_size==8+(off_t)serial.size());
    puts(warm?"PASS production upload cache hit across process restart; exact pixels, no strip decode/upload":"PASS production cold decode -> cache publication; exact pixels");
    if(warm){unlink(path);rmdir(PVZ2_GL_CACHE_ROOT "/glcache");rmdir(PVZ2_GL_CACHE_ROOT);}
}

static void packed_slice_test() {
    std::vector<uint8_t> raw(180000);
    uint32_t value = 834;
    for (auto &byte : raw) {
        value ^= value << 13;
        value ^= value >> 17;
        value ^= value << 5;
        byte = (uint8_t)value;
    }
    std::vector<uint8_t> packed(compressBound(raw.size()));
    uLongf size = packed.size();
    assert(compress2(packed.data(), &size, raw.data(), raw.size(), 6) == Z_OK);
    FILE *file = tmpfile();
    assert(file);
    uint8_t prefix[19]{};
    assert(fwrite(prefix, 1, sizeof(prefix), file) == sizeof(prefix));
    assert(fwrite(packed.data(), 1, size, file) == size);
    PrefetchTexture texture{};
    texture.partOffset = sizeof(prefix);
    texture.packed = size;
    texture.raw = raw.size();
    std::vector<uint8_t> output(41751);
    texture.bytes = output.size();
    for (unsigned offset : {0U, 70845U, (unsigned)(raw.size() - output.size())}) {
        texture.offset = offset;
        assert(read_packed_texture(file, texture, output.data()));
        assert(memcmp(output.data(), raw.data() + offset, output.size()) == 0);
    }
    texture.packed = 20;
    assert(!read_packed_texture(file, texture, output.data()));
    fclose(file);
    puts("PASS streamed atlas slices at start, middle and end; truncated input rejected");
}

int main(int argc,char **argv) {
    if(argc==2 && strcmp(argv[1],"packed-slice")==0){packed_slice_test();return 0;}
    if(argc==3){demand_test(argv[1],strcmp(argv[2],"warm")==0);return 0;}
    packed_slice_test();
    DecodePool *pool = new DecodePool;
    std::mutex mutex;
    std::condition_variable changed;
    bool entered=false, release=false, urgent=false;
    int running=0, peak=0, completed=0;
    assert(pool->submit(false,1,[&]{
        std::unique_lock<std::mutex> lock(mutex);
        entered=true; changed.notify_all();
        changed.wait(lock,[&]{return release;});
    }));
    {
        std::unique_lock<std::mutex> lock(mutex);
        assert(changed.wait_for(lock,5s,[&]{return entered;}));
    }
    for(int i=0;i<12;++i)assert(pool->submit(false,2,[&]{
        {std::lock_guard<std::mutex> lock(mutex);peak=std::max(peak,++running);}
        usleep(1000);
        {std::lock_guard<std::mutex> lock(mutex);--running;++completed;changed.notify_all();}
    }));
    assert(pool->submit(true,3,[&]{std::lock_guard<std::mutex> lock(mutex);urgent=true;changed.notify_all();}));
    {
        std::unique_lock<std::mutex> lock(mutex);
        assert(changed.wait_for(lock,5s,[&]{return urgent;}));
        assert(completed==0);release=true;changed.notify_all();
        assert(changed.wait_for(lock,5s,[&]{return completed==12;}));
        assert(peak==1);
    }
    puts("PASS urgent work runs while background is blocked; background concurrency = 1");
    const char *path=PVZ2_GL_CACHE_ROOT "/glcache/cache-test.rgba";
    uint8_t pixels[64];for(int i=0;i<64;++i)pixels[i]=(uint8_t)(i*13);
    AstcStrip a,b;a.y=0;a.h=2;a.out=pixels;b.y=2;b.h=2;b.out=pixels+32;
    std::vector<AstcStrip> strips{a,b};
    auto roundtrip=[&]{
        cache_write_rgba(path,4,4,strips);int w=0,h=0;
        uint8_t *read=cache_read_rgba(path,&w,&h);
        assert(read && w==4 && h==4 && memcmp(read,pixels,64)==0);free(read);
        struct stat st;assert(stat(path,&st)==0 && st.st_size==72);
    };
    roundtrip();unlink(path);
    assert(rmdir(PVZ2_GL_CACHE_ROOT "/glcache")==0);
    roundtrip();
    FILE *f=fopen(path,"wb");assert(f);uint32_t header[2]={4,4};
    assert(fwrite(header,4,2,f)==2);fclose(f);
    int w=0,h=0;assert(cache_read_rgba(path,&w,&h)==nullptr);
    f=fopen(path,"wb");assert(f);header[0]=0xffffffff;
    assert(fwrite(header,4,2,f)==2);fclose(f);
    assert(cache_read_rgba(path,&w,&h)==nullptr);
    roundtrip();unlink(path);rmdir(PVZ2_GL_CACHE_ROOT "/glcache");rmdir(PVZ2_GL_CACHE_ROOT);
    puts("PASS cache write/read exact pixels, atomic replacement, deleted-directory recreation, truncated/invalid rejection");
}

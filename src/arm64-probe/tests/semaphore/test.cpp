#include <atomic>
#include <cerrno>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <future>
#include <memory>
#include <mutex>
#include <semaphore.h>
#include <thread>
#include <string>
#include <unordered_map>

static constexpr uint32_t guestAddress = 0x7440;
static uint32_t guestWord;
static void require(bool condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "%s\n", message);
        std::abort();
    }
}
static void Invalid(const char* message) { require(false, message); }

struct Jit {
    uint32_t registers[16]{};
    auto& Regs() { return registers; }
};
struct Host {
    int error = 0;
    void MemoryWrite32(uint32_t p, uint32_t value) {
        require(p == guestAddress, "unexpected guest write");
        guestWord = value;
    }
};
static void Span(Host&, uint32_t address, size_t size) {
    require(address == guestAddress && size == 4, "unexpected guest span");
}
static void Failure(Jit& j, Host& h, int error) { h.error = error; j.Regs()[0] = UINT32_MAX; }
static void Result(Jit& j, Host& h, int result) {
    j.Regs()[0] = result;
    if (result == -1) h.error = errno;
}

#include "registry.inc"

using Thunk = void(*)(Jit&, Host&);
static std::unordered_map<std::string, Thunk> thunks;
static void RegisterThunk(const char* name, Thunk fn) { thunks.emplace(name, fn); }

static std::promise<void> posted;
static std::promise<void> releasePost;
static thread_local bool intercept = false;
static int gatedPost(sem_t* target) {
    const int rc = ::sem_post(target);
    if (!intercept) return rc;
    require(rc == 0, "first native post failed");
    posted.set_value();
    releasePost.get_future().wait();
    // A second signal through the same still-borrowed object exposes aliasing.
    // A correct bridge retires this generation only when the thunk returns.
    require(::sem_post(target) == 0, "old generation no longer owns its native semaphore");
    return rc;
}

static void registerTestThunks() {
#define sem_post(pointer) gatedPost(pointer)
#include "thunks.inc"
#undef sem_post
}

static int call(const char* name, unsigned count = 0) {
    Jit j;
    Host h;
    j.Regs()[0] = guestAddress;
    j.Regs()[2] = count;
    thunks.at(name)(j, h);
    return j.Regs()[0] == 0 ? 0 : h.error;
}

int main(int argc, char** argv) {
    require(argc == 2, "pass baseline or fixed");
    const bool baseline = strcmp(argv[1], "baseline") == 0;
    require(baseline || strcmp(argv[1], "fixed") == 0, "invalid mode");
    registerTestThunks();
    require(call("sem_init") == 0, "first init failed");
    std::weak_ptr<Semaphore> old = GetSemaphore(guestAddress);
    std::thread worker([] {
        intercept = true;
        require(call("sem_post") == 0, "guest post failed");
    });

    posted.get_future().wait();
    require(call("sem_wait") == 0, "wait did not consume the completed post");
    const int destroy = call("sem_destroy");
    const int init = call("sem_init");
    printf("%s: destroy=%d reinit=%d\n", argv[1], destroy, init);
    require(destroy == (baseline ? EBUSY : 0), "unexpected destroy result");
    require(init == (baseline ? EBUSY : 0), "unexpected same-address init result");
    require(!old.expired(), "post lost its borrowed generation");
    require(call("sem_trywait") == EAGAIN, "semaphore unexpectedly held a permit");
    releasePost.set_value();
    worker.join();
    if (baseline) {
        require(!old.expired() && call("sem_trywait") == 0, "baseline no longer exhibits the stuck old generation");
    } else {
        require(old.expired(), "retired semaphore outlived its last borrow");
        require(call("sem_trywait") == EAGAIN, "delayed old signal leaked into new generation");
        require(call("sem_post") == 0 && call("sem_wait") == 0, "new generation cannot deliver its own signal");
    }
    require(call("sem_destroy") == 0, "cleanup failed");
    require(call("sem_destroy") == EINVAL, "double destroy accepted");
    puts(baseline ? "PASS reproduced old EBUSY" : "PASS new generation isolated");
}

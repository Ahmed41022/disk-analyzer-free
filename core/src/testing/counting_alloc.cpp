#include "counting_alloc.hpp"

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <new>

namespace {

std::atomic<std::size_t> live{0}, peak{0};
struct Header {
    void *base;
    std::size_t size;
};

void *allocate(std::size_t size, std::size_t alignment) {
    alignment = alignment < alignof(Header) ? alignof(Header) : alignment;
    constexpr auto maximum = std::numeric_limits<std::size_t>::max();
    if (alignment > maximum - sizeof(Header) || size > maximum - alignment - sizeof(Header))
        throw std::bad_alloc();
    void *base = std::malloc(size + alignment + sizeof(Header));
    if (!base)
        throw std::bad_alloc();
    const auto address = reinterpret_cast<std::uintptr_t>(base) + sizeof(Header);
    const auto aligned = (address + alignment - 1) & ~(alignment - 1);
    auto *header = reinterpret_cast<Header *>(aligned) - 1;
    header->base = base;
    header->size = size;
    const auto now = live.fetch_add(size, std::memory_order_relaxed) + size;
    auto previous = peak.load(std::memory_order_relaxed);
    while (previous < now &&
           !peak.compare_exchange_weak(previous, now, std::memory_order_relaxed)) {
    }
    return reinterpret_cast<void *>(aligned);
}

void release(void *pointer) noexcept {
    if (!pointer)
        return;
    auto *header = static_cast<Header *>(pointer) - 1;
    live.fetch_sub(header->size, std::memory_order_relaxed);
    std::free(header->base);
}

} // namespace

namespace dafree::testing {
void reset_allocation_peak() noexcept {
    peak.store(live.load(std::memory_order_relaxed), std::memory_order_relaxed);
}
AllocationSnapshot allocations() noexcept {
    return {live.load(std::memory_order_relaxed), peak.load(std::memory_order_relaxed)};
}
} // namespace dafree::testing

// All standard replacement forms share one accounting path, including aligned allocations.
void *operator new(std::size_t size) { return allocate(size, alignof(std::max_align_t)); }
void *operator new[](std::size_t size) { return ::operator new(size); }
void *operator new(std::size_t size, std::align_val_t alignment) {
    return allocate(size, static_cast<std::size_t>(alignment));
}
void *operator new[](std::size_t size, std::align_val_t alignment) {
    return ::operator new(size, alignment);
}
void *operator new(std::size_t size, const std::nothrow_t &) noexcept {
    try {
        return ::operator new(size);
    } catch (...) {
        return nullptr;
    }
}
void *operator new[](std::size_t size, const std::nothrow_t &) noexcept {
    try {
        return ::operator new[](size);
    } catch (...) {
        return nullptr;
    }
}
void *operator new(std::size_t size, std::align_val_t alignment, const std::nothrow_t &) noexcept {
    try {
        return ::operator new(size, alignment);
    } catch (...) {
        return nullptr;
    }
}
void *operator new[](std::size_t size, std::align_val_t alignment,
                     const std::nothrow_t &) noexcept {
    try {
        return ::operator new[](size, alignment);
    } catch (...) {
        return nullptr;
    }
}
void operator delete(void *pointer) noexcept { release(pointer); }
void operator delete[](void *pointer) noexcept { release(pointer); }
void operator delete(void *pointer, std::size_t) noexcept { release(pointer); }
void operator delete[](void *pointer, std::size_t) noexcept { release(pointer); }
void operator delete(void *pointer, std::align_val_t) noexcept { release(pointer); }
void operator delete[](void *pointer, std::align_val_t) noexcept { release(pointer); }
void operator delete(void *pointer, std::size_t, std::align_val_t) noexcept { release(pointer); }
void operator delete[](void *pointer, std::size_t, std::align_val_t) noexcept { release(pointer); }
void operator delete(void *pointer, const std::nothrow_t &) noexcept { release(pointer); }
void operator delete[](void *pointer, const std::nothrow_t &) noexcept { release(pointer); }
void operator delete(void *pointer, std::align_val_t, const std::nothrow_t &) noexcept {
    release(pointer);
}
void operator delete[](void *pointer, std::align_val_t, const std::nothrow_t &) noexcept {
    release(pointer);
}

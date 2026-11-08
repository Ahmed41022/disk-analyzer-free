#include "counting_alloc.hpp"

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <new>

namespace {

// Replacement allocation operators share process-wide atomic accounting.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-non-const-global-variables)
std::atomic<std::size_t> live{0}, peak{0}, calls{0};
struct Header {
    void *base;
    std::size_t size;
};

// Replacement-new accounting cannot allocate through new; checked alignment owns a malloc block.
// NOLINTBEGIN(cppcoreguidelines-no-malloc,cppcoreguidelines-owning-memory,cppcoreguidelines-pro-type-reinterpret-cast,cppcoreguidelines-pro-bounds-pointer-arithmetic,performance-no-int-to-ptr)
auto allocate(std::size_t size, std::size_t alignment) -> void * {
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
    calls.fetch_add(1, std::memory_order_relaxed);
    const auto now = live.fetch_add(size, std::memory_order_relaxed) + size;
    auto previous = peak.load(std::memory_order_relaxed);
    while (previous < now &&
           !peak.compare_exchange_weak(previous, now, std::memory_order_relaxed)) {
    }
    return reinterpret_cast<void *>(aligned);
}
// NOLINTEND(cppcoreguidelines-no-malloc,cppcoreguidelines-owning-memory,cppcoreguidelines-pro-type-reinterpret-cast,cppcoreguidelines-pro-bounds-pointer-arithmetic,performance-no-int-to-ptr)

// Replacement-delete releases only the malloc block recorded in the aligned header.
// NOLINTBEGIN(cppcoreguidelines-no-malloc,cppcoreguidelines-owning-memory,cppcoreguidelines-pro-bounds-pointer-arithmetic)
void release(void *pointer) noexcept {
    if (!pointer)
        return;
    auto *header = static_cast<Header *>(pointer) - 1;
    live.fetch_sub(header->size, std::memory_order_relaxed);
    std::free(header->base);
}
// NOLINTEND(cppcoreguidelines-no-malloc,cppcoreguidelines-owning-memory,cppcoreguidelines-pro-bounds-pointer-arithmetic)

} // namespace

namespace dafree::testing {
void reset_allocation_peak() noexcept {
    peak.store(live.load(std::memory_order_relaxed), std::memory_order_relaxed);
}
auto allocations() noexcept -> AllocationSnapshot {
    return {live.load(std::memory_order_relaxed), peak.load(std::memory_order_relaxed),
            calls.load(std::memory_order_relaxed)};
}
} // namespace dafree::testing

// All standard replacement forms share one accounting path, including aligned allocations.
auto operator new(std::size_t size) -> void * { return allocate(size, alignof(std::max_align_t)); }
auto operator new[](std::size_t size) -> void * { return ::operator new(size); }
auto operator new(std::size_t size, std::align_val_t alignment) -> void * {
    return allocate(size, static_cast<std::size_t>(alignment));
}
auto operator new[](std::size_t size, std::align_val_t alignment) -> void * {
    return ::operator new(size, alignment);
}
auto operator new(std::size_t size, const std::nothrow_t &) noexcept -> void * {
    try {
        return ::operator new(size);
    } catch (...) {
        return nullptr;
    }
}
auto operator new[](std::size_t size, const std::nothrow_t &) noexcept -> void * {
    try {
        return ::operator new[](size);
    } catch (...) {
        return nullptr;
    }
}
auto operator new(std::size_t size, std::align_val_t alignment, const std::nothrow_t &) noexcept
    -> void * {
    try {
        return ::operator new(size, alignment);
    } catch (...) {
        return nullptr;
    }
}
auto operator new[](std::size_t size, std::align_val_t alignment, const std::nothrow_t &) noexcept
    -> void * {
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

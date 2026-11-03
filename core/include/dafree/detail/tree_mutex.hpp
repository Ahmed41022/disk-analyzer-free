#pragma once

#include <shared_mutex>

#ifdef DAFREE_MINGW_SRWLOCK
#include <memory>
#endif

namespace dafree::detail {

#ifdef DAFREE_MINGW_SRWLOCK
// MinGW GCC 15.1 winpthreads can fail concurrent shared locking (MSYS2 #25193).
class TreeMutex {
  public:
    TreeMutex();
    ~TreeMutex();
    TreeMutex(const TreeMutex &) = delete;
    TreeMutex &operator=(const TreeMutex &) = delete;

    void lock() noexcept;
    void unlock() noexcept;
    void lock_shared() noexcept;
    void unlock_shared() noexcept;

  private:
    struct Native;
    std::unique_ptr<Native> native_;
};
#else
using TreeMutex = std::shared_mutex;
#endif

} // namespace dafree::detail

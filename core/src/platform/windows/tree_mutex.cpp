#include "dafree/detail/tree_mutex.hpp"
#include "internal.hpp"

namespace dafree::detail {

struct TreeMutex::Native {
    SRWLOCK lock = SRWLOCK_INIT;
};

TreeMutex::TreeMutex() : native_(std::make_unique<Native>()) {}
TreeMutex::~TreeMutex() = default;

void TreeMutex::lock() noexcept { ::AcquireSRWLockExclusive(&native_->lock); }
void TreeMutex::unlock() noexcept { ::ReleaseSRWLockExclusive(&native_->lock); }
void TreeMutex::lock_shared() noexcept { ::AcquireSRWLockShared(&native_->lock); }
void TreeMutex::unlock_shared() noexcept { ::ReleaseSRWLockShared(&native_->lock); }

} // namespace dafree::detail

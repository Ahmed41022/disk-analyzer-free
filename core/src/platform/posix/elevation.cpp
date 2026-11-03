#include "dafree/platform.hpp"

#include <unistd.h>

namespace dafree::platform {

bool is_elevated() { return ::geteuid() == 0; }

void relaunch_elevated(std::span<const std::string>) {
    throw Unsupported("elevated relaunch is unsupported on POSIX");
}

} // namespace dafree::platform

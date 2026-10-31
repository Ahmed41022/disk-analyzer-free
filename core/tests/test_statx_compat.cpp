#include "../src/platform/linux/statx_compat.hpp"

#include <doctest/doctest.h>

TEST_CASE("statx_mount_root_without_new_kernel_headers") {
    // This translation unit deliberately needs no Linux headers, on any OS.
    constexpr auto mount_root = dafree::platform::detail::kStatxMountRoot;
    static_assert(mount_root == 0x00002000);
    CHECK(dafree::platform::detail::statx_is_mount_root(mount_root, mount_root));
    CHECK(dafree::platform::detail::statx_is_mount_root(mount_root | 4, mount_root | 4));
    CHECK_FALSE(dafree::platform::detail::statx_is_mount_root(4, mount_root));
    CHECK_FALSE(dafree::platform::detail::statx_is_mount_root(mount_root, 0));
    CHECK_FALSE(dafree::platform::detail::statx_is_mount_root(0, mount_root));
}

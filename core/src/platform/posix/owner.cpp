#include "dafree/platform.hpp"

#include <cerrno>
#include <cstdint>
#include <pwd.h>
#include <string>
#include <sys/types.h>
#include <sys/utsname.h>
#include <unistd.h>
#include <vector>

namespace dafree::platform {
namespace {

constexpr std::size_t kBytesPerKiB = 1024;
constexpr std::size_t kInitialPasswdBufferKiB = 16;
constexpr std::size_t kMaximumPasswdBufferKiB = kBytesPerKiB;
constexpr std::size_t kInitialPasswdBufferBytes = kInitialPasswdBufferKiB * kBytesPerKiB;
constexpr std::size_t kMaximumPasswdBufferBytes = kMaximumPasswdBufferKiB * kBytesPerKiB;

} // namespace

auto system_identity() -> std::pair<std::string, std::string> {
    struct utsname identity{};
    if (::uname(&identity) != 0)
        return {"unknown", "POSIX"};
    return {identity.nodename, identity.sysname};
}

auto name_for_uid(std::uint32_t uid) -> std::optional<std::string> {
    const long recommended = ::sysconf(_SC_GETPW_R_SIZE_MAX);
    std::size_t capacity =
        recommended > 0 ? static_cast<std::size_t>(recommended) : kInitialPasswdBufferBytes;
    for (; capacity <= kMaximumPasswdBufferBytes; capacity *= 2u) {
        std::vector<char> buffer(capacity);
        struct passwd record{};
        struct passwd *result = nullptr;
        const int code =
            ::getpwuid_r(static_cast<uid_t>(uid), &record, buffer.data(), buffer.size(), &result);
        if (code == ERANGE)
            continue;
        if (code != 0 || result == nullptr || record.pw_name == nullptr)
            return std::nullopt;
        return std::string(record.pw_name);
    }
    return std::nullopt;
}

auto owner_of(std::string_view path) -> std::optional<std::pair<OwnerKey, std::string>> {
    const RawEntry entry = stat_nofollow(path);
    if (!entry.owner.has_value())
        return std::nullopt;
    const std::uint32_t uid = entry.owner->uid;
    return std::pair{*entry.owner, name_for_uid(uid).value_or(std::to_string(uid))};
}

auto show_properties(std::string_view) -> bool { return false; }

} // namespace dafree::platform

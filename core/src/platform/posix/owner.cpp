#include "dafree/platform.hpp"

#include <cerrno>
#include <cstdint>
#include <pwd.h>
#include <string>
#include <sys/types.h>
#include <unistd.h>
#include <vector>

namespace dafree::platform {

std::optional<std::string> name_for_uid(std::uint32_t uid) {
    const long recommended = ::sysconf(_SC_GETPW_R_SIZE_MAX);
    std::size_t capacity = recommended > 0 ? static_cast<std::size_t>(recommended) : 16 * 1024u;
    for (; capacity <= 1024u * 1024u; capacity *= 2u) {
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

std::optional<std::pair<OwnerKey, std::string>> owner_of(std::string_view path) {
    const RawEntry entry = stat_nofollow(path);
    if (!entry.owner.has_value())
        return std::nullopt;
    const std::uint32_t uid = entry.owner->uid;
    return std::pair{*entry.owner, name_for_uid(uid).value_or(std::to_string(uid))};
}

bool is_elevated() { return ::geteuid() == 0; }

void relaunch_elevated(std::span<const std::string>) {
    throw Error("elevated relaunch is unsupported on POSIX");
}

} // namespace dafree::platform

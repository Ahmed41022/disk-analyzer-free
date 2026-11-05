#include "internal.hpp"

#include <aclapi.h>
#include <mutex>
#include <unordered_map>

namespace dafree::platform {
namespace {

struct FreeDescriptor {
    void operator()(void *descriptor) const noexcept { ::LocalFree(descriptor); }
};

struct SidCache {
    std::mutex mutex;
    std::unordered_map<std::string, std::string> names;
    std::uint64_t hits = 0;
};

SidCache &sid_cache() {
    static SidCache cache;
    return cache;
}

std::optional<std::string> lookup_name(PSID sid) {
    DWORD name_size = 0, domain_size = 0;
    SID_NAME_USE use{};
    if (::LookupAccountSidW(nullptr, sid, nullptr, &name_size, nullptr, &domain_size, &use) ||
        ::GetLastError() != ERROR_INSUFFICIENT_BUFFER || name_size == 0)
        return std::nullopt;

    std::wstring name(name_size, L'\0'), domain(domain_size, L'\0');
    if (!::LookupAccountSidW(nullptr, sid, name.data(), &name_size, domain.data(), &domain_size,
                             &use))
        return std::nullopt;

    name.resize(std::char_traits<wchar_t>::length(name.c_str()));
    domain.resize(std::char_traits<wchar_t>::length(domain.c_str()));
    if (name.empty())
        return std::nullopt;
    return detail::to_wtf8(domain.empty() ? name : domain + L'\\' + name);
}

} // namespace

std::optional<std::pair<OwnerKey, std::string>> owner_of(std::string_view path) {
    if (path.empty())
        return std::nullopt;
    std::wstring native;
    try {
        native = detail::native_path(path);
    } catch (const IoError &) {
        return std::nullopt;
    } catch (const std::invalid_argument &) {
        return std::nullopt;
    }
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    PSID sid = nullptr;
    const DWORD result =
        ::GetNamedSecurityInfoW(native.c_str(), SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION, &sid,
                                nullptr, nullptr, nullptr, &descriptor);
    const std::unique_ptr<void, FreeDescriptor> storage(descriptor);
    if (result != ERROR_SUCCESS || !sid || !::IsValidSid(sid))
        return std::nullopt;

    auto key = OwnerKey::windows_sid(
        {static_cast<const char *>(sid), static_cast<std::size_t>(::GetLengthSid(sid))});
    auto &cache = sid_cache();
    {
        std::lock_guard lock(cache.mutex);
        const auto found = cache.names.find(key.value);
        if (found != cache.names.end()) {
            ++cache.hits;
            return std::pair{std::move(key), found->second};
        }
    }
    auto name = lookup_name(sid);
    if (!name)
        return std::nullopt;
    {
        std::lock_guard lock(cache.mutex);
        // Never hold the cache lock while Windows performs account or domain I/O.
        if (cache.names.size() < 4096)
            cache.names.try_emplace(key.value, *name);
    }
    return std::pair{std::move(key), std::move(*name)};
}

std::uint64_t sid_cache_hits() {
    auto &cache = sid_cache();
    std::lock_guard lock(cache.mutex);
    return cache.hits;
}

} // namespace dafree::platform

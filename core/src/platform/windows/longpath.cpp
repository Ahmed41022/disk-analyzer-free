#include "dafree/platform.hpp"

#include <algorithm>
#include <stdexcept>

namespace dafree::platform {

auto to_verbatim(std::string_view path) -> std::string {
    if (path.find('\0') != std::string_view::npos)
        throw std::invalid_argument("path contains NUL");
    if (path.starts_with(R"(\\?\)"))
        return std::string(path);
    std::string normalized(path);
    std::replace(normalized.begin(), normalized.end(), '/', '\\');
    if (normalized.size() >= 3 &&
        ((normalized[0] >= 'A' && normalized[0] <= 'Z') ||
         (normalized[0] >= 'a' && normalized[0] <= 'z')) &&
        normalized[1] == ':' && normalized[2] == '\\')
        return R"(\\?\)" + normalized;
    if (normalized.starts_with(R"(\\)") && !normalized.starts_with(R"(\\.\)")) {
        const auto share = normalized.find('\\', 2);
        if (share != std::string::npos && share > 2 && share + 1 < normalized.size() &&
            normalized[share + 1] != '\\')
            return R"(\\?\UNC\)" + normalized.substr(2);
    }
    throw std::invalid_argument("Windows path must be absolute");
}

} // namespace dafree::platform

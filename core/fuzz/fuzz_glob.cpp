#include "../src/scan/glob.hpp"
#include "dafree/scan.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string_view>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    if (size < 2 || size > 8192)
        return 0;
    const std::size_t selected = (static_cast<std::size_t>(data[0]) * 256u + data[1]) % (size - 1);
    const std::size_t length = std::min<std::size_t>(selected, 512);
    const std::string_view pattern(reinterpret_cast<const char *>(data + 2), length);
    const std::string_view subject(reinterpret_cast<const char *>(data + 2 + length),
                                   size - 2 - length);
    try {
        const auto glob = dafree::detail::CompiledGlob::compile(pattern, (data[0] & 1u) != 0);
        (void)glob.matches(subject, (data[1] & 1u) != 0);
    } catch (const dafree::ExcludeError &) {
        // Syntax errors are an expected parser result.
    }
    return 0;
}

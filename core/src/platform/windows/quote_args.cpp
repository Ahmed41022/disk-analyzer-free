#include "dafree/platform.hpp"

#include <stdexcept>

namespace dafree::platform {

auto quote_windows_args(std::span<const std::wstring> args) -> std::wstring {
    std::wstring command;
    for (const auto &arg : args) {
        if (arg.find(L'\0') != std::wstring::npos)
            throw std::invalid_argument("Windows argument contains NUL");
        if (!command.empty())
            command.push_back(L' ');
        command.push_back(L'"');
        std::size_t slashes = 0;
        for (const auto ch : arg) {
            if (ch == L'\\') {
                ++slashes;
                continue;
            }
            command.append(slashes, L'\\');
            if (ch == L'"') {
                // Double preceding backslashes and escape the literal quote.
                command.append(slashes, L'\\');
                command.push_back(L'\\');
            }
            command.push_back(ch);
            slashes = 0;
        }
        // Trailing backslashes precede the closing delimiter.
        command.append(slashes, L'\\');
        command.append(slashes, L'\\');
        command.push_back(L'"');
    }
    return command;
}

} // namespace dafree::platform

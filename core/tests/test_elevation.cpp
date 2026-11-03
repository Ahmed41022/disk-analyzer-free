#include "dafree/platform.hpp"

#include <doctest/doctest.h>

#include <array>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>

#include <shellapi.h>
#endif

TEST_CASE("quote_windows_args_table") {
    struct Case {
        std::vector<std::wstring> args;
        std::wstring expected;
    };
    const std::array cases = {
        Case{{}, L""},
        Case{{L""}, L"\"\""},
        Case{{L"plain", L"two words"}, LR"("plain" "two words")"},
        Case{{L"a\tb"}, L"\"a\tb\""},
        Case{{LR"(C:\folder\file)"}, LR"("C:\folder\file")"},
        Case{{LR"(C:\folder with spaces\)"}, LR"("C:\folder with spaces\\")"},
        Case{{LR"(a"b)"}, LR"("a\"b")"},
        Case{{LR"(a\"b)"}, LR"("a\\\"b")"},
        Case{{L"\u03a9"}, L"\"\u03a9\""},
        Case{{std::wstring(1, static_cast<wchar_t>(0xd800))},
             {L'"', static_cast<wchar_t>(0xd800), L'"'}},
    };
    for (std::size_t index = 0; index < cases.size(); ++index) {
        CAPTURE(index);
        const auto &entry = cases[index];
        const auto command = dafree::platform::quote_windows_args(entry.args);
        CHECK(command == entry.expected);
#ifdef _WIN32
        struct Arguments {
            wchar_t **values;
            ~Arguments() { ::LocalFree(values); }
        };
        int count = 0;
        const Arguments parsed{::CommandLineToArgvW((L"dafree.exe " + command).c_str(), &count)};
        REQUIRE(parsed.values != nullptr);
        REQUIRE(count == static_cast<int>(entry.args.size()) + 1);
        for (std::size_t i = 0; i < entry.args.size(); ++i)
            CHECK(std::wstring_view(parsed.values[i + 1]) == entry.args[i]);
#endif
    }
    const std::array invalid{std::wstring{L'a', L'\0', L'b'}};
    CHECK_THROWS_AS(dafree::platform::quote_windows_args(invalid), std::invalid_argument);
}

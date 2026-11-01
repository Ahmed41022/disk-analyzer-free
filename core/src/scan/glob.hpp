#pragma once

#include <cstddef>
#include <cstdint>
#include <string_view>
#include <utility>
#include <vector>

namespace dafree::detail {

char32_t next_codepoint(std::string_view input, std::size_t &offset) noexcept;
char32_t fold_codepoint(char32_t value) noexcept;

class CompiledGlob {
  public:
    struct Workspace {
        std::vector<std::uint8_t> current, next;
    };
    static CompiledGlob compile(std::string_view pattern, bool ignore_case);
    [[nodiscard]] bool matches(std::string_view input, bool windows_path = false) const;
    [[nodiscard]] bool matches(std::string_view input, bool windows_path,
                               Workspace &workspace) const;

  private:
    enum class Kind { Literal, Any, Star, GlobStar, DirStar, Class };
    struct Token {
        Kind kind;
        char32_t value = 0;
        bool negated = false;
        std::vector<std::pair<char32_t, char32_t>> ranges;
    };
    std::vector<Token> tokens_;
    bool ignore_case_ = false;
};

} // namespace dafree::detail

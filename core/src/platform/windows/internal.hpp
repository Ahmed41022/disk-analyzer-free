#pragma once

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include "dafree/platform.hpp"

#include <utility>

namespace dafree::platform::detail {

class UniqueHandle {
  public:
    explicit UniqueHandle(HANDLE handle) noexcept : handle_(handle) {}
    ~UniqueHandle() {
        if (handle_ != INVALID_HANDLE_VALUE && handle_ != nullptr)
            ::CloseHandle(handle_);
    }
    UniqueHandle(const UniqueHandle &) = delete;
    UniqueHandle &operator=(const UniqueHandle &) = delete;
    [[nodiscard]] HANDLE get() const noexcept { return handle_; }

  private:
    HANDLE handle_;
};

std::wstring from_wtf8(std::string_view input);
std::string to_wtf8(std::wstring_view input);
std::wstring native_path(std::string_view input);
[[noreturn]] void fail(std::string_view path, DWORD code);
std::uint64_t volume_serial(HANDLE handle, std::string_view path);
std::optional<std::int64_t> unix_time(LONGLONG ticks);
void set_attributes(RawEntry &entry, DWORD attributes, DWORD tag, std::wstring_view path);

} // namespace dafree::platform::detail

#include "internal.hpp"

#include <objbase.h>
#include <shellapi.h>

namespace dafree::platform {
namespace {

std::string diagnostic(std::string_view operation, DWORD code) {
    return std::string(operation) + " failed (Windows error " + std::to_string(code) + ")";
}

class ShellApartment {
  public:
    ShellApartment() {
        const HRESULT result =
            ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
        if (SUCCEEDED(result))
            initialized_ = true;
        else if (result != RPC_E_CHANGED_MODE)
            throw Error("could not initialize COM for elevated relaunch");
    }
    ~ShellApartment() {
        if (initialized_)
            ::CoUninitialize();
    }
    ShellApartment(const ShellApartment &) = delete;
    ShellApartment &operator=(const ShellApartment &) = delete;

  private:
    bool initialized_ = false;
};

} // namespace

bool is_elevated() {
    HANDLE token = nullptr;
    if (!::OpenProcessToken(::GetCurrentProcess(), TOKEN_QUERY, &token))
        throw Unsupported(diagnostic("OpenProcessToken", ::GetLastError()));
    const detail::UniqueHandle handle(token);
    TOKEN_ELEVATION elevation{};
    DWORD returned = 0;
    if (!::GetTokenInformation(handle.get(), TokenElevation, &elevation,
                               static_cast<DWORD>(sizeof(elevation)), &returned))
        throw Unsupported(diagnostic("GetTokenInformation", ::GetLastError()));
    return elevation.TokenIsElevated != 0;
}

void relaunch_elevated(std::span<const std::string> args) {
    std::vector<std::wstring> wide;
    wide.reserve(args.size());
    for (const auto &arg : args)
        wide.push_back(detail::from_wtf8(arg));
    const auto command = quote_windows_args(wide);

    std::wstring executable(32768, L'\0');
    const auto capacity = static_cast<DWORD>(executable.size());
    const DWORD length = ::GetModuleFileNameW(nullptr, executable.data(), capacity);
    if (length == 0)
        throw Error(diagnostic("GetModuleFileNameW", ::GetLastError()));
    if (length >= capacity)
        throw Error("current executable path exceeds the Windows limit");
    executable.resize(length);

    const ShellApartment apartment;
    SHELLEXECUTEINFOW launch{};
    launch.cbSize = static_cast<DWORD>(sizeof(launch));
    launch.fMask = SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
    launch.lpVerb = L"runas";
    launch.lpFile = executable.c_str();
    launch.lpParameters = command.empty() ? nullptr : command.c_str();
    launch.nShow = SW_SHOWNORMAL;
    if (!::ShellExecuteExW(&launch)) {
        const DWORD code = ::GetLastError();
        if (code == ERROR_CANCELLED)
            throw Cancelled("elevated relaunch cancelled");
        throw Error(diagnostic("ShellExecuteExW", code));
    }
}

} // namespace dafree::platform

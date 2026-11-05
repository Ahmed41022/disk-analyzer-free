#include "internal.hpp"

#include <objbase.h>
#include <shlobj.h>

namespace dafree::platform {

bool show_properties(std::string_view path) {
    if (path.empty())
        return false;
    std::wstring filename;
    try {
        filename = detail::from_wtf8(path);
    } catch (const std::invalid_argument &) {
        return false;
    }

    const auto apartment =
        ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    if (FAILED(apartment))
        return false;
    const bool invoked =
        ::SHObjectProperties(nullptr, SHOP_FILEPATH, filename.c_str(), nullptr) != FALSE;
    ::CoUninitialize();
    return invoked;
}

} // namespace dafree::platform

#include "bindings.hpp"

#include <limits>
#include <stdexcept>

namespace dafree::bindings {

auto decode_native(std::string_view input) -> nb::str {
    if (input.size() > static_cast<std::size_t>(PY_SSIZE_T_MAX))
        throw std::length_error("native string is too large for Python");
    const auto length = static_cast<Py_ssize_t>(input.size());
#ifdef _WIN32
    PyObject *value = PyUnicode_DecodeUTF8(input.data(), length, "surrogatepass");
#else
    PyObject *value = PyUnicode_DecodeFSDefaultAndSize(input.data(), length);
#endif
    if (value == nullptr)
        throw nb::python_error();
    return nb::steal<nb::str>(value);
}

auto encode_native(nb::handle input) -> std::string {
    if (!PyUnicode_Check(input.ptr()))
        throw nb::type_error("native paths and names must be str");
#ifdef _WIN32
    PyObject *encoded = PyUnicode_AsEncodedString(input.ptr(), "utf-8", "surrogatepass");
#else
    PyObject *encoded = PyUnicode_EncodeFSDefault(input.ptr());
#endif
    if (encoded == nullptr)
        throw nb::python_error();
    auto owner = nb::steal<nb::object>(encoded);
    char *data = nullptr;
    Py_ssize_t length = 0;
    if (PyBytes_AsStringAndSize(owner.ptr(), &data, &length) != 0)
        throw nb::python_error();
    return {data, static_cast<std::size_t>(length)};
}

auto decode_strings(const std::vector<std::string> &input) -> std::vector<nb::str> {
    std::vector<nb::str> output;
    output.reserve(input.size());
    for (const auto &value : input)
        output.push_back(decode_native(value));
    return output;
}

auto encode_strings(const std::vector<nb::str> &input) -> std::vector<std::string> {
    std::vector<std::string> output;
    output.reserve(input.size());
    for (const auto &value : input)
        output.push_back(encode_native(value));
    return output;
}

} // namespace dafree::bindings

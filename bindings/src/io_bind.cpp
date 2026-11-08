#include "bindings.hpp"
#include "dafree/export.hpp"

#include <array>
#include <ostream>
#include <streambuf>

#include <nanobind/stl/optional.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {
namespace {

// Bridge native output to a Python binary stream without retaining a whole report.
class PythonOutput : public std::streambuf {
  public:
    explicit PythonOutput(nb::object write) : write_(std::move(write)) { reset(); }

  private:
    auto sync() -> int override {
        if (pbase() == pptr())
            return 0;
        nb::gil_scoped_acquire acquire;
        const char *next = pbase();
        while (next < pptr()) {
            const auto size = static_cast<std::size_t>(pptr() - next);
            const auto written = nb::cast<std::size_t>(write_(nb::bytes(next, size)));
            if (written == 0 || written > size)
                throw Error("invalid byte count from report stream");
            // The callback count was checked against the remaining owned buffer.
            // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic)
            next += written;
        }
        reset();
        return 0;
    }

    auto overflow(int_type value) -> int_type override {
        sync();
        if (!traits_type::eq_int_type(value, traits_type::eof())) {
            *pptr() = traits_type::to_char_type(value);
            pbump(1);
        }
        return traits_type::not_eof(value);
    }

    void reset() {
        // streambuf borrows the half-open range of this owned, fixed-size array.
        // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-pointer-arithmetic)
        setp(buffer_.data(), buffer_.data() + buffer_.size());
    }

    nb::object write_;
    static constexpr std::size_t buffer_bytes = std::size_t{64} * 1024;
    std::array<char, buffer_bytes> buffer_{};
};

} // namespace

void bind_io(nb::module_ &module) {
    module.def(
        "write_json",
        [](const BoundTree &tree, const std::vector<NodeId> &scopes,
           nb::typed<nb::callable, std::size_t(nb::bytes)> write,
           std::optional<std::uint16_t> depth, bool include_files, bool ndjson, bool include_owner,
           bool pretty) {
            PythonOutput buffer(std::move(write));
            std::ostream stream(&buffer);
            stream.exceptions(std::ios::badbit | std::ios::failbit);
            nb::gil_scoped_release release;
            write_json(*tree.handle, *tree.backend, scopes, stream,
                       {depth, include_files, ndjson, include_owner, pretty});
            stream.flush();
        },
        nb::arg("tree"), nb::arg("scopes"), nb::arg("write"), nb::arg("depth"),
        nb::arg("include_files"), nb::arg("ndjson"), nb::arg("include_owner"), nb::arg("pretty"),
        "Write JSON as bounded UTF-8 chunks to a binary write callback.");
    module.def(
        "write_csv",
        [](const BoundTree &tree, const std::vector<NodeId> &scopes,
           nb::typed<nb::callable, std::size_t(nb::bytes)> write,
           std::optional<std::uint16_t> depth, bool include_files, bool excel, bool include_owner,
           char delimiter) {
            PythonOutput buffer(std::move(write));
            std::ostream stream(&buffer);
            stream.exceptions(std::ios::badbit | std::ios::failbit);
            nb::gil_scoped_release release;
            write_csv(*tree.handle, *tree.backend, scopes, stream,
                      {depth, include_files, excel, include_owner, delimiter});
            stream.flush();
        },
        nb::arg("tree"), nb::arg("scopes"), nb::arg("write"), nb::arg("depth"),
        nb::arg("include_files"), nb::arg("excel"), nb::arg("include_owner"), nb::arg("delimiter"),
        "Write CSV as bounded UTF-8 chunks to a binary write callback.");
}

} // namespace dafree::bindings

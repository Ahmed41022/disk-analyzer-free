#include "../src/testing/counting_alloc.hpp"
#include "dafree/export.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <ostream>
#include <span>
#include <sstream>
#include <streambuf>
#include <string>
#include <string_view>
#include <utility>

namespace {

using namespace std::string_view_literals;
using dafree::JsonOptions;
using dafree::NodeId;
using dafree::Tree;
using dafree::TreeBuilder;

std::string serialize(const Tree &tree, const JsonOptions &options = {},
                      std::span<const NodeId> scopes = {}) {
    std::ostringstream output;
    dafree::write_json(tree, scopes, output, options);
    return output.str();
}

// Match the requested member with its exact scalar token, independently of key order or spacing.
bool has_member(std::string_view document, std::string_view key, std::string_view token) {
    const auto quoted_key = '"' + std::string(key) + '"';
    for (auto pos = document.find(quoted_key); pos != std::string_view::npos;
         pos = document.find(quoted_key, pos + quoted_key.size())) {
        const auto colon = document.find_first_not_of(" \t\r\n", pos + quoted_key.size());
        if (colon == std::string_view::npos || document[colon] != ':')
            continue;
        const auto value = document.find_first_not_of(" \t\r\n", colon + 1);
        if (value == std::string_view::npos || !document.substr(value).starts_with(token))
            continue;
        const auto next = document.find_first_not_of(" \t\r\n", value + token.size());
        if (next != std::string_view::npos && (document[next] == ',' || document[next] == '}'))
            return true;
    }
    return false;
}

Tree with_file(std::string_view name) {
    TreeBuilder builder({"/scan"});
    const std::array entries{TreeBuilder::NewNode{name, 0, 1, 4096, 0, 0, 0, {}}};
    builder.add_children(1, entries);
    return std::move(builder).finish({});
}

class DiscardBuffer final : public std::streambuf {
  public:
    std::uint64_t bytes = 0;
    std::uint64_t names = 0;

  protected:
    std::streamsize xsputn(const char *data, std::streamsize count) override {
        bytes += static_cast<std::uint64_t>(count);
        for (std::streamsize i = 0; i < count; ++i)
            consume(data[i]);
        return count;
    }

    int_type overflow(int_type value) override {
        if (traits_type::eq_int_type(value, traits_type::eof()))
            return traits_type::not_eof(value);
        ++bytes;
        consume(traits_type::to_char_type(value));
        return value;
    }

  private:
    std::size_t matched_ = 0;

    void consume(char value) {
        constexpr auto key = R"("name")"sv;
        if (value == key[matched_]) {
            if (++matched_ == key.size()) {
                ++names;
                matched_ = 0;
            }
        } else {
            matched_ = value == '"' ? 1u : 0u;
        }
    }
};

Tree mock_tree(NodeId nodes) {
    constexpr NodeId fanout = 10;
    TreeBuilder builder({"/million"});
    std::array<TreeBuilder::NewNode, fanout> entries{};
    for (NodeId parent = 1, next = 2; next < nodes; ++parent) {
        const auto children = std::min(fanout, nodes - next);
        for (NodeId i = 0; i < children; ++i) {
            const auto id = next + i;
            const bool has_children = (id - 1) * fanout + 2 < nodes;
            entries[i] = {has_children ? "folder"sv : "item.dat"sv,
                          has_children ? static_cast<std::uint16_t>(dafree::kDir)
                                       : std::uint16_t{0},
                          13,
                          4096,
                          0,
                          0,
                          0,
                          {}};
        }
        builder.add_children(parent, std::span(entries).first(children));
        next += children;
    }
    return std::move(builder).finish({});
}

} // namespace

TEST_CASE("json_escaping_table") {
    struct Entry {
        std::string_view input, token;
    };
    const std::array entries{
        Entry{"plain.txt", R"("plain.txt")"},
        Entry{"quote\"and\\slash/", R"("quote\"and\\slash/")"},
        Entry{"\x00\x01\b\f\n\r\t\x1f"sv, R"("\u0000\u0001\b\f\n\r\t\u001f")"},
        Entry{"\xc3\xa9/\xf0\x9f\x93\x81", "\"\xc3\xa9/\xf0\x9f\x93\x81\""},
    };
    for (std::size_t i = 0; i < entries.size(); ++i) {
        CAPTURE(i);
        const auto &entry = entries[i];
        const auto document = serialize(with_file(entry.input));
        CHECK(has_member(document, "name", entry.token));
        CHECK(document.find(R"("name_raw_hex")") == std::string::npos);
    }
}

TEST_CASE("json_non_utf8_name_hex") {
    for (const auto &[bytes, hex] :
         std::array{std::pair{"x\xff.dat"sv, R"("78ff2e646174")"sv},
                    std::pair{"x\xed\xa0\x80.dat"sv, R"("78eda0802e646174")"sv}}) {
        const auto document = serialize(with_file(bytes));
        CHECK(has_member(document, "name", "\"x\xef\xbf\xbd.dat\""));
        CHECK(has_member(document, "name_raw_hex", hex));
        CHECK(document.find(bytes) == std::string::npos);
    }
}

TEST_CASE("json_scope_depth_and_flat_paths") {
    TreeBuilder builder({"/scan"});
    const std::array root_children{TreeBuilder::NewNode{"scope", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                   TreeBuilder::NewNode{"unselected", 0, 1, 1, 0, 0, 0, {}}};
    const auto scope = builder.add_children(1, root_children).first;
    const std::array scope_children{
        TreeBuilder::NewNode{"entry.dat",
                             dafree::kHidden,
                             std::numeric_limits<std::uint64_t>::max(),
                             4096,
                             1,
                             0,
                             2'147'483'648u,
                             {}},
        TreeBuilder::NewNode{"deleted", dafree::kExcluded, 1, 1, 0, 0, 0, {}}};
    const auto entry = builder.add_children(scope, scope_children).first;
    auto tree = std::move(builder).finish({});
    tree.set_owner(entry, dafree::OwnerKey::posix_uid(42), "a\"b");
    const std::array scopes{scope};
    JsonOptions options;
    options.depth = std::uint16_t{0};
    const auto scope_only = serialize(tree, options, scopes);
    CHECK(has_member(scope_only, "name", R"("scope")"));
    CHECK(has_member(scope_only, "files", "1"));
    CHECK_FALSE(has_member(scope_only, "name", R"("entry.dat")"));
    CHECK_FALSE(has_member(scope_only, "name", R"("/scan")"));

    options.depth = std::uint16_t{1};
    options.include_files = false;
    CHECK_FALSE(has_member(serialize(tree, options, scopes), "name", R"("entry.dat")"));

    options.include_files = true;
    options.ndjson = true;
    options.pretty = true;
    options.include_owner = true;
    const auto flat = serialize(tree, options, scopes);
    CHECK(std::count(flat.begin(), flat.end(), '\n') == 2);
    CHECK(flat.starts_with('{'));
    CHECK(flat.ends_with('\n'));
    const auto separator = flat.find('\n');
    REQUIRE(separator != std::string::npos);
    const auto first = std::string_view(flat).substr(0, separator);
    const auto second = std::string_view(flat).substr(separator + 1);
    CHECK(has_member(first, "name", R"("scope")"));
    CHECK(has_member(second, "name", R"("entry.dat")"));
#ifdef _WIN32
    CHECK(has_member(first, "path", R"("/scan\\scope")"));
    CHECK(has_member(second, "path", R"("/scan\\scope\\entry.dat")"));
#else
    CHECK(has_member(first, "path", R"("/scan/scope")"));
    CHECK(has_member(second, "path", R"("/scan/scope/entry.dat")"));
#endif
    CHECK(has_member(second, "size", "18446744073709551615"));
    CHECK(has_member(second, "mtime", R"("1970-01-01T00:00:01Z")"));
    CHECK(has_member(second, "btime", "null"));
    CHECK(has_member(second, "atime", R"("2038-01-19T03:14:08Z")"));
    CHECK(has_member(second, "owner", R"("a\"b")"));
    CHECK(flat.find(R"("children")") == std::string::npos);
    CHECK(flat.find(R"("unselected")") == std::string::npos);
    CHECK(flat.find(R"("deleted")") == std::string::npos);
}

TEST_CASE("test_json_streaming_constant_memory") {
    constexpr NodeId nodes = 1'000'000;
    constexpr std::size_t budget = 8u * 1024u * 1024u;
    const auto tree = mock_tree(nodes);
    REQUIRE(tree.size() == nodes);
    DiscardBuffer discard;
    std::ostream output(&discard);
    const auto baseline = dafree::testing::allocations().live;
    dafree::testing::reset_allocation_peak();
    dafree::write_json(tree, {}, output, {});
    const auto peak = dafree::testing::allocations().peak;
    REQUIRE(peak >= baseline);
    const auto delta = peak - baseline;
    MESSAGE("JSON writer peak bytes: ", delta, ", streamed bytes: ", discard.bytes,
            ", streamed nodes: ", discard.names);
    CHECK(output.good());
    CHECK(discard.names == nodes - 1);
    CHECK(discard.bytes > budget);
    CHECK(delta < budget);
}

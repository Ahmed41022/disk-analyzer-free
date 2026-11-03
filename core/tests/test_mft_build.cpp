#include "dafree/mft.hpp"
#include "dafree/model.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using Bytes = std::vector<std::byte>;
using RawRecord = std::pair<std::uint64_t, Bytes>;
constexpr std::uint64_t epoch_ticks = UINT64_C(116444736000000000);
constexpr std::uint64_t record_mask = UINT64_C(0x0000ffffffffffff);
constexpr std::size_t attribute_start = 0x50;

std::string volume_root() {
#ifdef _WIN32
    return "C:\\ntfs";
#else
    return "/ntfs";
#endif
}

void put(std::span<std::byte> bytes, std::size_t offset, std::uint64_t value, std::size_t width) {
    REQUIRE(offset <= bytes.size());
    REQUIRE(width <= bytes.size() - offset);
    REQUIRE(width <= sizeof(value));
    for (std::size_t index = 0; index < width; ++index)
        bytes[offset + index] = static_cast<std::byte>((value >> (index * 8)) & 0xffu);
}

std::size_t round8(std::size_t value) { return (value + 7) & ~std::size_t{7}; }

std::uint64_t reference(std::uint64_t number, std::uint16_t sequence = 1) {
    return (number & record_mask) | (static_cast<std::uint64_t>(sequence) << 48);
}

std::u16string ascii_name(std::string_view name) {
    std::u16string result;
    for (const auto value : name)
        result.push_back(static_cast<char16_t>(static_cast<unsigned char>(value)));
    return result;
}

void put_name(std::span<std::byte> bytes, std::size_t offset, std::u16string_view name) {
    for (std::size_t index = 0; index < name.size(); ++index)
        put(bytes, offset + index * 2, name[index], 2);
}

Bytes resident(std::uint32_t type, const Bytes &value = {}, std::u16string_view name = {}) {
    REQUIRE(name.size() <= 255);
    const auto payload = round8(24 + name.size() * 2);
    Bytes bytes(round8(payload + value.size()));
    put(bytes, 0, type, 4);
    put(bytes, 4, bytes.size(), 4);
    put(bytes, 9, name.size(), 1);
    put(bytes, 10, name.empty() ? 0 : 24, 2);
    put(bytes, 16, value.size(), 4);
    put(bytes, 20, payload, 2);
    put_name(bytes, 24, name);
    std::copy(value.begin(), value.end(), bytes.begin() + static_cast<std::ptrdiff_t>(payload));
    return bytes;
}

Bytes file_name(std::uint64_t parent, std::u16string_view name, std::uint8_t space = 1,
                std::uint16_t parent_sequence = 1) {
    Bytes value(66 + name.size() * 2);
    put(value, 0, reference(parent, parent_sequence), 8);
    put(value, 64, name.size(), 1);
    put(value, 65, space, 1);
    put_name(value, 66, name);
    return resident(0x30, value);
}

Bytes standard(std::uint32_t attributes = 0, std::uint64_t created = epoch_ticks + 10000000,
               std::uint64_t modified = epoch_ticks + 20000000,
               std::uint64_t accessed = epoch_ticks + 30000000) {
    Bytes value(48);
    put(value, 0, created, 8);
    put(value, 8, modified, 8);
    put(value, 24, accessed, 8);
    put(value, 32, attributes, 4);
    return resident(0x10, value);
}

Bytes nonresident(std::uint64_t size, std::uint64_t alloc, std::u16string_view name = {},
                  std::uint64_t lowest_vcn = 0) {
    const auto maps = round8(64 + name.size() * 2);
    Bytes bytes(round8(maps + 4));
    put(bytes, 0, 0x80, 4);
    put(bytes, 4, bytes.size(), 4);
    put(bytes, 8, 1, 1);
    put(bytes, 9, name.size(), 1);
    put(bytes, 10, name.empty() ? 0 : 64, 2);
    put(bytes, 16, lowest_vcn, 8);
    put(bytes, 24, lowest_vcn, 8);
    put(bytes, 32, maps, 2);
    put(bytes, 40, alloc, 8);
    put(bytes, 48, size, 8);
    put(bytes, 56, size, 8);
    put_name(bytes, 64, name);
    put(bytes, maps, 0x11, 1);
    put(bytes, maps + 1, 1, 1);
    put(bytes, maps + 2, 1, 1);
    return bytes;
}

Bytes raw_record(const std::vector<Bytes> &attributes = {}, bool directory = false,
                 std::uint16_t sequence = 1, std::uint64_t base = 0, bool in_use = true) {
    Bytes bytes(4096);
    bytes[0] = std::byte{0x46};
    bytes[1] = std::byte{0x49};
    bytes[2] = std::byte{0x4c};
    bytes[3] = std::byte{0x45};
    put(bytes, 4, 0x30, 2);
    put(bytes, 6, 9, 2);
    put(bytes, 0x10, sequence, 2);
    put(bytes, 0x12, 1, 2);
    put(bytes, 0x14, attribute_start, 2);
    put(bytes, 0x16, (in_use ? 1u : 0u) | (directory ? 2u : 0u), 2);
    put(bytes, 0x1c, bytes.size(), 4);
    put(bytes, 0x20, base, 8);
    std::size_t used = attribute_start;
    for (const auto &attribute : attributes) {
        REQUIRE(attribute.size() <= bytes.size() - used);
        std::copy(attribute.begin(), attribute.end(),
                  bytes.begin() + static_cast<std::ptrdiff_t>(used));
        used += attribute.size();
    }
    put(bytes, used, 0xffffffffu, 4);
    put(bytes, 0x18, used + 4, 4);
    put(bytes, 0x30, 0xa55a, 2);
    for (std::size_t sector = 0; sector < 8; ++sector) {
        const auto trailer = (sector + 1) * 512 - 2;
        const auto low = std::to_integer<std::uint16_t>(bytes[trailer]);
        const auto high = std::to_integer<std::uint16_t>(bytes[trailer + 1]);
        put(bytes, 0x32 + sector * 2, low | (static_cast<std::uint64_t>(high) << 8), 2);
        put(bytes, trailer, 0xa55a, 2);
    }
    return bytes;
}

RawRecord root_record() { return {5, raw_record({}, true)}; }

RawRecord directory(std::uint64_t number, std::uint64_t parent, std::u16string_view name,
                    std::uint16_t sequence = 1) {
    return {number, raw_record({file_name(parent, name)}, true, sequence)};
}

RawRecord file(std::uint64_t number, std::uint64_t parent, std::u16string_view name,
               std::uint64_t size, std::uint64_t alloc = 0) {
    return {number, raw_record({file_name(parent, name), nonresident(size, alloc)})};
}

void ingest(dafree::MftIndex &index, const RawRecord &record) {
    auto bytes = record.second; // ingest restores fixups; every call receives original bytes.
    index.ingest(record.first, bytes, 512);
}

dafree::Tree build(const std::vector<RawRecord> &records, const dafree::ScanOptions &options = {},
                   std::optional<std::string_view> subtree = std::nullopt) {
    dafree::MftIndex index;
    for (const auto &record : records)
        ingest(index, record);
    dafree::IssueSink sink;
    return dafree::build_tree_from_mft(index, volume_root(), subtree, options, sink);
}

dafree::NodeId selected_root(const dafree::Tree &tree) {
    REQUIRE(tree.roots().size() == 1);
    return tree.roots()[0];
}

std::optional<dafree::NodeId> lookup(const dafree::Tree &tree, std::string_view relative) {
    auto path = tree.path_bytes(selected_root(tree));
    if (!relative.empty()) {
        path += '/';
        path += relative;
    }
    return tree.find_path(path);
}

dafree::NodeId require_node(const dafree::Tree &tree, std::string_view relative) {
    const auto found = lookup(tree, relative);
    REQUIRE(found.has_value());
    return *found;
}

std::uint64_t issues(const dafree::Tree &tree, dafree::IssueKind kind) {
    return tree.meta().issues.counts[static_cast<std::size_t>(kind)];
}

void check_invariants(const dafree::Tree &tree) {
    REQUIRE(tree.size() >= 2);
    CHECK(tree.node(0).parent == dafree::kNone);
    CHECK((tree.node(0).flags & dafree::kSynthetic) != 0);
    CHECK(tree.node(selected_root(tree)).parent == 0);
    std::vector<unsigned> referenced(tree.size());
    std::uint16_t previous_depth = 0;
    for (dafree::NodeId id = 0; id < tree.size(); ++id) {
        const auto &node = tree.node(id);
        const auto [first, last] = tree.children(id);
        if (id != 0) {
            CHECK(node.parent < id);
            CHECK((tree.node(node.parent).flags & dafree::kDir) != 0);
            const auto depth = tree.depth(id);
            CHECK(depth >= previous_depth);
            previous_depth = depth;
        }
        if (node.child_count == 0) {
            CHECK(first == dafree::kNone);
            CHECK(last == dafree::kNone);
            continue;
        }
        CHECK((node.flags & dafree::kDir) != 0);
        REQUIRE(first > id);
        REQUIRE(last <= tree.size());
        CHECK(last - first == node.child_count);
        for (auto child = first; child < last; ++child) {
            CHECK(tree.node(child).parent == id);
            ++referenced[child];
        }
    }
    for (dafree::NodeId id = 1; id < tree.size(); ++id)
        CHECK(referenced[id] == 1);
}

std::uint64_t random_word(std::uint64_t &state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

std::string parent_path(std::string_view path) {
    const auto slash = path.rfind('/');
    return slash == std::string_view::npos ? std::string{} : std::string(path.substr(0, slash));
}

template <typename Operation>
void scan_error_is(Operation operation, dafree::ScanError::Code code) {
    try {
        (void)operation();
        FAIL("expected a classified scan error");
    } catch (const dafree::ScanError &error) {
        CHECK(error.code() == code);
    }
}

} // namespace

TEST_CASE("parent_before_child") {
    const auto tree = build({file(32, 30, u"leaf.bin", 17, 4096), directory(30, 40, u"inner"),
                             directory(40, 5, u"outer"), root_record()});
    const auto outer = require_node(tree, "outer");
    const auto inner = require_node(tree, "outer/inner");
    const auto leaf = require_node(tree, "outer/inner/leaf.bin");
    CHECK(outer < inner);
    CHECK(inner < leaf);
    CHECK(tree.node(selected_root(tree)).size == 17);
    CHECK(tree.node(selected_root(tree)).alloc == 4096);
    CHECK(tree.counts(selected_root(tree)).files == 1);
    CHECK(tree.counts(selected_root(tree)).dirs == 2);
    CHECK(tree.meta().mode == dafree::ScanModeUsed::Mft);
    CHECK(tree.meta().issues.total == 0);
    check_invariants(tree);
}

TEST_CASE("hardlink_multiple_parents_counted_once") {
    const std::vector<RawRecord> records = {
        root_record(),
        directory(20, 5, u"a"),
        directory(21, 5, u"b"),
        {32, raw_record({file_name(20, u"first.bin"), file_name(21, u"second.bin"),
                         nonresident(17, 4096)})}};
    const auto tree = build(records);
    const auto a = require_node(tree, "a/first.bin");
    const auto b = require_node(tree, "b/second.bin");
    CHECK(tree.node(a).size == 17);
    CHECK(tree.node(b).size == 17);
    CHECK(((tree.node(a).flags & dafree::kHardlinkDup) != 0) !=
          ((tree.node(b).flags & dafree::kHardlinkDup) != 0));
    CHECK(tree.node(selected_root(tree)).size == 17);
    CHECK(tree.node(selected_root(tree)).alloc == 4096);
    CHECK(tree.counts(selected_root(tree)).files == 2);
    dafree::ScanOptions options;
    options.hardlinks = dafree::HardlinkMode::CountAll;
    const auto all = build(records, options);
    CHECK(all.node(selected_root(all)).size == 34);
    CHECK(all.node(selected_root(all)).alloc == 8192);
    CHECK((all.node(require_node(all, "a/first.bin")).flags & dafree::kHardlinkDup) == 0);
    CHECK((all.node(require_node(all, "b/second.bin")).flags & dafree::kHardlinkDup) == 0);
    check_invariants(all);
}

TEST_CASE("orphans_skipped_with_issue") {
    const auto tree =
        build({root_record(), file(32, 9999, u"lost.bin", 17), file(33, 5, u"kept.bin", 3)});
    CHECK_FALSE(lookup(tree, "lost.bin"));
    CHECK(tree.node(require_node(tree, "kept.bin")).size == 3);
    CHECK(tree.counts(selected_root(tree)).files == 1);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 1);
    CHECK(tree.meta().issues.first.size() == 1);
}

TEST_CASE("sequence_mismatch_is_orphan") {
    const auto tree =
        build({root_record(),
               directory(20, 5, u"parent", 7),
               {32, raw_record({file_name(20, u"stale.bin", 1, 6), nonresident(7, 0)})},
               {33, raw_record({file_name(20, u"live.bin", 1, 7), nonresident(3, 0)})}});
    CHECK_FALSE(lookup(tree, "parent/stale.bin"));
    CHECK(tree.node(require_node(tree, "parent/live.bin")).size == 3);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 1);
}

TEST_CASE("subtree_extraction") {
    const std::vector<RawRecord> records = {
        root_record(),
        directory(20, 5, u"scope"),
        directory(21, 20, u"nested"),
        file(33, 21, u"leaf.bin", 5, 512),
        {32, raw_record({file_name(5, u"external.bin"), file_name(20, u"inside.bin"),
                         nonresident(7, 1024)})}};
    const auto full = build(records);
    CHECK((full.node(require_node(full, "scope/inside.bin")).flags & dafree::kHardlinkDup) != 0);
    for (const auto &subtree : {std::string("scope"), volume_root() + "/ScOpE"}) {
        const auto tree = build(records, {}, subtree);
        CHECK_FALSE(lookup(tree, "external.bin"));
        CHECK(tree.node(require_node(tree, "inside.bin")).size == 7);
        CHECK((tree.node(require_node(tree, "inside.bin")).flags & dafree::kHardlinkDup) == 0);
        CHECK(tree.node(selected_root(tree)).size == 12);
        CHECK(tree.node(selected_root(tree)).alloc == 1536);
        CHECK(tree.counts(selected_root(tree)).files == 2);
        CHECK(tree.counts(selected_root(tree)).dirs == 1);
        check_invariants(tree);
    }
}

TEST_CASE("random_index_invariants") {
    struct Expected {
        bool directory;
        std::uint64_t size = 0, alloc = 0;
        dafree::Counts counts{};
    };
    for (std::uint64_t seed = 1; seed <= 500; ++seed) {
        CAPTURE(seed);
        std::uint64_t state = seed * UINT64_C(0x9e3779b97f4a7c15);
        std::vector<RawRecord> records{root_record()};
        std::vector<std::pair<std::uint64_t, std::string>> directories{{5, ""}};
        std::map<std::string, Expected> expected{{"", {true}}};
        const auto count = 8 + random_word(state) % 25;
        for (std::uint64_t index = 0; index < count; ++index) {
            const auto &parent = directories[random_word(state) % directories.size()];
            const auto name = "node" + std::to_string(index);
            const auto path = parent.second.empty() ? name : parent.second + '/' + name;
            const auto number = index + 32;
            const bool is_directory = random_word(state) % 3 == 0;
            if (is_directory) {
                records.push_back(directory(number, parent.first, ascii_name(name)));
                directories.emplace_back(number, path);
                expected.emplace(path, Expected{true});
            } else {
                const auto size = random_word(state) % 10001;
                const auto alloc = (random_word(state) % 8) * 512;
                records.push_back(file(number, parent.first, ascii_name(name), size, alloc));
                expected.emplace(path, Expected{false, size, alloc});
            }
        }
        // Count each independently generated entry in every ancestor, without tree traversal.
        const auto individual = expected;
        for (const auto &[path, value] : individual) {
            if (path.empty())
                continue;
            auto ancestor = parent_path(path);
            while (true) {
                auto &totals = expected.at(ancestor);
                if (value.directory)
                    ++totals.counts.dirs;
                else {
                    ++totals.counts.files;
                    totals.size += value.size;
                    totals.alloc += value.alloc;
                }
                if (ancestor.empty())
                    break;
                ancestor = parent_path(ancestor);
            }
        }
        for (std::size_t index = records.size(); index > 1; --index)
            std::swap(records[index - 1], records[random_word(state) % index]);
        const auto tree = build(records);
        CHECK(tree.size() == expected.size() + 1);
        CHECK(tree.meta().issues.total == 0);
        check_invariants(tree);
        for (const auto &[path, value] : expected) {
            CAPTURE(path);
            const auto id = require_node(tree, path);
            const auto &node = tree.node(id);
            CHECK(((node.flags & dafree::kDir) != 0) == value.directory);
            CHECK(node.size == value.size);
            CHECK(node.alloc == value.alloc);
            CHECK(tree.counts(id).files == value.counts.files);
            CHECK(tree.counts(id).dirs == value.counts.dirs);
        }
    }
}

TEST_CASE("utf16_to_wtf8_lone_surrogates") {
    struct Example {
        std::u16string input;
        std::string expected;
    };
    const std::array examples = {
        Example{u"", ""},
        Example{u"ASCII", "ASCII"},
        Example{u"\u00e9", "\xc3\xa9"},
        Example{u"\u07ff", "\xdf\xbf"},
        Example{u"\u0800", "\xe0\xa0\x80"},
        Example{u"\u0627", "\xd8\xa7"},
        Example{u"\uffff", "\xef\xbf\xbf"},
        Example{{char16_t{0xd83d}, char16_t{0xde00}}, "\xf0\x9f\x98\x80"},
        Example{{char16_t{0xdbff}, char16_t{0xdfff}}, "\xf4\x8f\xbf\xbf"},
        Example{{char16_t{0xd800}}, "\xed\xa0\x80"},
        Example{{char16_t{0xdfff}}, "\xed\xbf\xbf"},
        Example{{char16_t{0xd800}, u'A', char16_t{0xdc00}},
                "\xed\xa0\x80"
                "A"
                "\xed\xb0\x80"},
        Example{{u'A', u'\0', u'B'}, std::string("A\0B", 3)},
        Example{{char16_t{0xd800}, char16_t{0xd800}, char16_t{0xdc00}},
                "\xed\xa0\x80\xf0\x90\x80\x80"},
    };
    for (std::size_t index = 0; index < examples.size(); ++index) {
        CAPTURE(index);
        CHECK(dafree::utf16_to_wtf8(examples[index].input) == examples[index].expected);
    }
}

TEST_CASE("mft_dos_aliases_are_skipped_only_when_a_windows_name_exists_for_that_parent") {
    const auto tree =
        build({root_record(),
               {32, raw_record({file_name(5, u"LONGNA~1.TXT", 2), file_name(5, u"long name.txt", 1),
                                file_name(5, u"posix-name", 0), nonresident(7, 0)})},
               {33, raw_record({file_name(5, u"combined.txt", 3), nonresident(3, 0)})},
               {34, raw_record({file_name(5, u"DOSONLY.TXT", 2), nonresident(5, 0)})}});
    CHECK_FALSE(lookup(tree, "LONGNA~1.TXT"));
    require_node(tree, "long name.txt");
    require_node(tree, "posix-name");
    require_node(tree, "combined.txt");
    require_node(tree, "DOSONLY.TXT");
    CHECK(tree.counts(selected_root(tree)).files == 4);
    CHECK(tree.node(selected_root(tree)).size == 15);
}

TEST_CASE("mft_dos_alias_in_another_parent_is_retained") {
    const auto tree =
        build({root_record(),
               directory(20, 5, u"a"),
               directory(21, 5, u"b"),
               {32, raw_record({file_name(20, u"long name.txt", 1),
                                file_name(21, u"LONGNA~1.TXT", 2), nonresident(7, 512)})}});
    require_node(tree, "a/long name.txt");
    require_node(tree, "b/LONGNA~1.TXT");
    CHECK(tree.counts(selected_root(tree)).files == 2);
    CHECK(tree.node(selected_root(tree)).size == 7);
    CHECK(tree.node(selected_root(tree)).alloc == 512);
    CHECK(tree.meta().issues.total == 0);
}

TEST_CASE("mft_tree_preserves_surrogate_names_after_source_release") {
    const std::u16string name = {u'x', char16_t{0xd800}, u'y', char16_t{0xdc00}};
    const std::string encoded = "x\xed\xa0\x80"
                                "y\xed\xb0\x80";
    const auto tree = build({root_record(), file(32, 5, name, 7, 512)});
    const auto id = require_node(tree, encoded);
    CHECK(tree.name_bytes(id) == encoded);
    CHECK(tree.node(id).size == 7);
    CHECK(tree.meta().issues.total == 0);
}

TEST_CASE("mft_extension_records_merge_before_or_after_their_bases_including_record_zero") {
    const auto base = RawRecord{0, raw_record({file_name(5, u"$MFT")}, false, 9)};
    const auto extension =
        RawRecord{50, raw_record({resident(0x80, Bytes(6))}, false, 3, reference(0, 9))};
    for (const auto reverse : {false, true}) {
        dafree::MftIndex first, second;
        ingest(first, root_record());
        ingest(first, reverse ? base : extension);
        ingest(second, reverse ? extension : base);
        first.merge(std::move(second));
        dafree::IssueSink sink;
        const auto tree = dafree::build_tree_from_mft(first, volume_root(), std::nullopt, {}, sink);
        const auto id = require_node(tree, "$MFT");
        CHECK(tree.node(id).size == 6);
        CHECK(tree.node(id).alloc == 0);
        CHECK(tree.meta().issues.total == 0);
    }
    const auto stale =
        RawRecord{50, raw_record({resident(0x80, Bytes(6))}, false, 3, reference(0, 8))};
    const auto tree = build({root_record(), base, stale});
    CHECK(tree.node(require_node(tree, "$MFT")).size == 0);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 1);
}

TEST_CASE("mft_ads_and_continuation_extents_follow_scan_options") {
    const auto record = RawRecord{
        32, raw_record({file_name(5, u"streams.bin"), nonresident(10, 4096),
                        nonresident(99999, 99999, {}, 1), resident(0x80, Bytes(3), u"notes"),
                        nonresident(5, 512, u"other"), nonresident(99999, 99999, u"other", 1)})};
    const auto plain = build({root_record(), record});
    CHECK(plain.node(require_node(plain, "streams.bin")).size == 10);
    CHECK(plain.node(require_node(plain, "streams.bin")).alloc == 4096);
    dafree::ScanOptions options;
    options.include_ads = true;
    const auto all = build({root_record(), record}, options);
    CHECK(all.node(require_node(all, "streams.bin")).size == 18);
    CHECK(all.node(require_node(all, "streams.bin")).alloc == 4608);
}

TEST_CASE("mft_resident_sizes_and_aggregates_saturate_without_wrapping") {
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    const auto tree =
        build({root_record(),
               file(32, 5, u"large", maximum, maximum),
               file(33, 5, u"one", 1, 1),
               {34, raw_record({file_name(5, u"resident"), resident(0x80, Bytes(3))})}});
    CHECK(tree.node(require_node(tree, "resident")).size == 3);
    CHECK(tree.node(require_node(tree, "resident")).alloc == 0);
    CHECK(tree.node(selected_root(tree)).size == maximum);
    CHECK(tree.node(selected_root(tree)).alloc == maximum);
    CHECK(tree.counts(selected_root(tree)).files == 3);
}

TEST_CASE("mft_metafiles_and_extend_descendants_obey_visibility_policy") {
    const std::vector<RawRecord> records = {root_record(),
                                            file(0, 5, u"$MFT", 100, 4096),
                                            directory(11, 5, u"$Extend"),
                                            directory(32, 11, u"index"),
                                            file(33, 32, u"data", 17),
                                            file(34, 5, u"user", 3)};
    const auto all = build(records);
    for (const auto name : {"$MFT", "$Extend", "$Extend/index", "$Extend/index/data"}) {
        const auto flags = all.node(require_node(all, name)).flags;
        CHECK((flags & dafree::kHidden) != 0);
        CHECK((flags & dafree::kSystem) != 0);
    }
    dafree::ScanOptions options;
    options.show_ntfs_metafiles = false;
    const auto plain = build(records, options);
    CHECK_FALSE(lookup(plain, "$MFT"));
    CHECK_FALSE(lookup(plain, "$Extend"));
    CHECK(plain.node(require_node(plain, "user")).size == 3);
    CHECK(plain.counts(selected_root(plain)).files == 1);
    CHECK(plain.counts(selected_root(plain)).dirs == 0);
    CHECK(plain.meta().issues.total == 0);
}

TEST_CASE("mft_exclusions_apply_before_hardlink_deduplication") {
    const std::vector<RawRecord> records = {
        root_record(),
        directory(20, 5, u"skipdir"),
        file(33, 20, u"child", 20),
        file(34, 5, u"scratch.tmp", 30),
        {35, raw_record({standard(2), file_name(5, u"hidden"), nonresident(40, 0)})},
        {32,
         raw_record({file_name(5, u"skip.log"), file_name(5, u"keep.log"), nonresident(7, 0)})}};
    dafree::ScanOptions options;
    options.exclude.paths = {volume_root() + "/skipdir"};
    options.exclude.globs = {"*.tmp", "skip.log"};
    options.exclude.hidden = true;
    const auto tree = build(records, options);
    CHECK_FALSE(lookup(tree, "skipdir"));
    CHECK_FALSE(lookup(tree, "scratch.tmp"));
    CHECK_FALSE(lookup(tree, "hidden"));
    CHECK_FALSE(lookup(tree, "skip.log"));
    const auto kept = require_node(tree, "keep.log");
    CHECK((tree.node(kept).flags & dafree::kHardlinkDup) == 0);
    CHECK(tree.node(selected_root(tree)).size == 7);
    CHECK(tree.counts(selected_root(tree)).files == 1);
}

TEST_CASE("mft_reparse_directories_never_descend") {
    for (const auto marker : {false, true}) {
        std::vector<Bytes> attributes{file_name(5, u"junction")};
        attributes.push_back(marker ? resident(0xc0) : standard(0x400));
        const auto tree = build({root_record(),
                                 {20, raw_record(attributes, true)},
                                 file(32, 20, u"must-not-follow", 99)});
        const auto id = require_node(tree, "junction");
        CHECK((tree.node(id).flags & dafree::kReparse) != 0);
        CHECK(tree.node(id).child_count == 0);
        CHECK_FALSE(lookup(tree, "junction/must-not-follow"));
        CHECK(tree.node(selected_root(tree)).size == 0);
        CHECK(issues(tree, dafree::IssueKind::Orphaned) == 0);
        CHECK(tree.meta().issues.total == 0);
        check_invariants(tree);
    }
}

TEST_CASE("mft_directory_cycles_are_finite_and_reported") {
    const auto tree = build({root_record(),
                             {20, raw_record({file_name(5, u"a"), file_name(21, u"back")}, true)},
                             directory(21, 20, u"b"),
                             file(32, 21, u"leaf", 3)});
    CHECK(tree.size() < 10);
    CHECK(tree.node(selected_root(tree)).size == 3);
    CHECK(issues(tree, dafree::IssueKind::SymlinkLoop) >= 1);
    check_invariants(tree);
}

TEST_CASE("mft_ordinary_directory_alias_survives_another_parent_under_reparse") {
    for (const auto reverse : {false, true}) {
        std::vector<Bytes> names{file_name(20, u"hidden-alias"), file_name(5, u"ordinary")};
        if (reverse)
            std::reverse(names.begin(), names.end());
        const auto tree =
            build({root_record(),
                   file(32, 30, u"leaf", 7, 512),
                   {30, raw_record(names, true)},
                   {20, raw_record({file_name(5, u"junction"), resident(0xc0)}, true)}});
        const auto junction = require_node(tree, "junction");
        CHECK(tree.node(junction).child_count == 0);
        CHECK_FALSE(lookup(tree, "junction/hidden-alias"));
        require_node(tree, "ordinary");
        CHECK(tree.node(require_node(tree, "ordinary/leaf")).size == 7);
        CHECK(tree.node(selected_root(tree)).size == 7);
        CHECK(tree.node(selected_root(tree)).alloc == 512);
        CHECK(tree.counts(selected_root(tree)).files == 1);
        CHECK(tree.counts(selected_root(tree)).dirs == 2);
        CHECK(tree.meta().issues.total == 0);
        check_invariants(tree);
    }
}

TEST_CASE("mft_unreachable_cycles_and_their_children_are_orphans") {
    const auto tree = build({root_record(), directory(20, 21, u"a"), directory(21, 20, u"b"),
                             file(32, 20, u"lost", 7)});
    CHECK(tree.size() == 2);
    CHECK(tree.counts(selected_root(tree)).files == 0);
    CHECK(tree.node(selected_root(tree)).size == 0);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 3);
    CHECK(issues(tree, dafree::IssueKind::SymlinkLoop) == 0);
}

TEST_CASE("mft_invalid_components_are_skipped_while_converter_preserves_raw_nul") {
    const std::vector<std::u16string> names = {u"",    u".",    u"..",
                                               u"a/b", u"a\\b", std::u16string{u'a', u'\0', u'b'}};
    std::vector<RawRecord> records{root_record()};
    for (std::size_t index = 0; index < names.size(); ++index)
        records.push_back(file(index + 32, 5, names[index], 1));
    const auto tree = build(records);
    CHECK(tree.size() == 2);
    CHECK(issues(tree, dafree::IssueKind::InvalidName) == names.size());
}

TEST_CASE("mft_unknown_and_known_time_sentinels_remain_distinct") {
    const auto tree = build(
        {root_record(),
         file(32, 5, u"unknown", 0),
         {33, raw_record({standard(0, 0, epoch_ticks, std::numeric_limits<std::uint64_t>::max()),
                          file_name(5, u"known")})}});
    const auto &unknown = tree.node(require_node(tree, "unknown"));
    CHECK(unknown.btime == 0);
    CHECK(unknown.mtime == 0);
    CHECK(unknown.atime == 0);
    const auto &known = tree.node(require_node(tree, "known"));
    CHECK(known.btime == 1);
    CHECK(known.mtime == 1);
    CHECK(known.atime == std::numeric_limits<std::uint32_t>::max());
}

TEST_CASE("mft_standard_information_flags_and_times_are_retained") {
    const auto tree = build({root_record(),
                             {32, raw_record({standard(0x2 | 0x4 | 0x200 | 0x800),
                                              file_name(5, u"attributes"), nonresident(3, 1)})}});
    const auto &node = tree.node(require_node(tree, "attributes"));
    CHECK((node.flags & dafree::kHidden) != 0);
    CHECK((node.flags & dafree::kSystem) != 0);
    CHECK((node.flags & dafree::kSparse) != 0);
    CHECK((node.flags & dafree::kCompressed) != 0);
    CHECK(node.btime == 1);
    CHECK(node.mtime == 2);
    CHECK(node.atime == 3);
}

TEST_CASE("mft_unused_deleted_and_bad_record_slots_have_explicit_policies") {
    auto bad = file(32, 5, u"bad", 7);
    bad.second[0] = std::byte{0x42};
    bad.second[1] = std::byte{0x41};
    bad.second[2] = std::byte{0x41};
    bad.second[3] = std::byte{0x44};
    auto corrupt = file(33, 5, u"corrupt", 7);
    corrupt.second[510] = std::byte{0};
    auto other = file(34, 5, u"not-file", 7);
    other.second[0] = std::byte{0};
    const RawRecord deleted{35, raw_record({file_name(5, u"deleted")}, false, 1, 0, false)};
    const auto tree = build(
        {root_record(), bad, corrupt, other, deleted, {36, Bytes(4096)}, file(37, 5, u"live", 3)});
    CHECK(tree.size() == 3);
    CHECK(tree.node(require_node(tree, "live")).size == 3);
    CHECK(issues(tree, dafree::IssueKind::Other) == 2);
    CHECK(tree.meta().issues.total == 2);
}

TEST_CASE("mft_deleted_or_nondirectory_parents_leave_orphans") {
    const auto tree = build({root_record(),
                             {20, raw_record({file_name(5, u"deleted-parent")}, true, 1, 0, false)},
                             file(21, 5, u"not-directory", 3),
                             file(32, 20, u"lost-one", 7),
                             file(33, 21, u"lost-two", 11)});
    CHECK(tree.size() == 3);
    CHECK(tree.node(require_node(tree, "not-directory")).size == 3);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 2);
}

TEST_CASE("mft_duplicate_record_ids_are_invalidated_independent_of_merge_order") {
    const auto a = file(40, 5, u"ambiguous-a", 7);
    const auto b = file(40, 5, u"ambiguous-b", 11);
    for (const auto reverse : {false, true}) {
        dafree::MftIndex first, second;
        ingest(first, root_record());
        ingest(first, reverse ? a : b);
        ingest(second, reverse ? b : a);
        ingest(second, file(41, 5, u"live", 3));
        first.merge(std::move(second));
        dafree::IssueSink sink;
        const auto tree = dafree::build_tree_from_mft(first, volume_root(), std::nullopt, {}, sink);
        CHECK(tree.size() == 3);
        CHECK_FALSE(lookup(tree, "ambiguous-a"));
        CHECK_FALSE(lookup(tree, "ambiguous-b"));
        CHECK(tree.node(require_node(tree, "live")).size == 3);
        CHECK(issues(tree, dafree::IssueKind::Other) == 1);
    }
}

TEST_CASE("mft_large_record_numbers_use_sparse_indexing_and_safe_reference_checks") {
    constexpr std::uint64_t large = UINT64_C(0x0000ffffffff0000);
    constexpr std::uint64_t absent = UINT64_C(0x0000fffffffffff0);
    const auto tree =
        build({root_record(), file(large, 5, u"large-id", 7), file(32, absent, u"orphan", 3)});
    CHECK(tree.size() == 3);
    CHECK(tree.node(require_node(tree, "large-id")).size == 7);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == 1);
}

TEST_CASE("mft_ingest_owns_data_after_input_reuse_and_disjoint_merge") {
    dafree::MftIndex first, second;
    ingest(first, root_record());
    auto bytes = file(32, 5, u"first", 7, 512).second;
    first.ingest(32, bytes, 512);
    bytes.assign(bytes.size(), std::byte{0});
    bytes = file(33, 5, u"second", 11, 1024).second;
    second.ingest(33, bytes, 512);
    bytes.assign(bytes.size(), std::byte{0xff});
    first.merge(std::move(second));
    dafree::IssueSink sink;
    const auto tree = dafree::build_tree_from_mft(first, volume_root(), std::nullopt, {}, sink);
    CHECK(tree.node(require_node(tree, "first")).size == 7);
    CHECK(tree.node(require_node(tree, "second")).size == 11);
    CHECK(tree.node(selected_root(tree)).size == 18);
    CHECK(tree.node(selected_root(tree)).alloc == 1536);
    CHECK(tree.meta().issues.total == 0);
}

TEST_CASE("mft_issue_retention_is_bounded_while_counts_and_sink_remain_complete") {
    dafree::MftIndex index;
    ingest(index, root_record());
    constexpr std::size_t total = 1105;
    for (std::size_t number = 0; number < total; ++number)
        ingest(index, file(number + 32, 9999, ascii_name("lost" + std::to_string(number)), 1));
    std::size_t delivered = 0;
    dafree::IssueSink sink = [&delivered](dafree::ScanIssue issue) {
        CHECK(issue.kind == dafree::IssueKind::Orphaned);
        ++delivered;
    };
    const auto tree = dafree::build_tree_from_mft(index, volume_root(), std::nullopt, {}, sink);
    CHECK(tree.size() == 2);
    CHECK(delivered == total);
    CHECK(tree.meta().issues.total == total);
    CHECK(issues(tree, dafree::IssueKind::Orphaned) == total);
    CHECK(tree.meta().issues.first.size() == 1000);
    CHECK(tree.meta().issues.overflow == total - 1000);
}

TEST_CASE("mft_missing_root_invalid_subtree_and_following_are_explicit_errors") {
    scan_error_is([] { return build({}); }, dafree::ScanError::Code::InvalidTarget);
    scan_error_is([] { return build({file(5, 5, u"not-directory", 0)}); },
                  dafree::ScanError::Code::InvalidTarget);
    const std::vector<RawRecord> records = {root_record(), directory(20, 5, u"scope")};
    for (const auto &path :
         {std::string("missing"), std::string("../outside"), volume_root() + "-outside/scope"})
        scan_error_is([&] { return build(records, {}, path); },
                      dafree::ScanError::Code::InvalidTarget);
    dafree::ScanOptions options;
    options.follow_symlinks = true;
    scan_error_is([&] { return build(records, options); },
                  dafree::ScanError::Code::UnsupportedMode);
}

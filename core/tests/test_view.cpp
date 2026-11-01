#include "../src/view/view_internal.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <atomic>
#include <numeric>
#include <random>
#include <thread>
#include <variant>

namespace {

std::shared_ptr<dafree::Tree> sample_tree() {
    dafree::TreeBuilder builder({"/view"});
    const std::array<dafree::TreeBuilder::NewNode, 3> root{{
        {"folder", dafree::kDir, 0, 0, 1, 0, 0, {}},
        {"file10.txt", dafree::kHidden, 10, 16, 10, 0, 0, {}},
        {"file2.txt", 0, 2, 8, 2, 0, 0, {}},
    }};
    builder.add_children(1, root);
    const std::array<dafree::TreeBuilder::NewNode, 3> folder{{
        {"nested", dafree::kDir, 0, 0, 1, 0, 0, {}},
        {"a.bin", 0, 3, 8, 3, 0, 0, {}},
        {"z.bin", 0, 4, 8, 4, 0, 0, {}},
    }};
    builder.add_children(2, folder);
    const dafree::TreeBuilder::NewNode leaf{"needle.iso", 0, 20, 32, 20, 0, 0, {}};
    builder.add_children(5, std::span(&leaf, 1));
    return std::make_shared<dafree::Tree>(std::move(builder).finish({}));
}

std::vector<dafree::NodeId> ids(const dafree::TreeView &view) {
    std::vector<dafree::NodeId> result;
    for (std::uint32_t start = 0; start < view.row_count(); start += 500)
        for (const auto &row : view.rows(start, 500))
            result.push_back(row.id);
    return result;
}

dafree::ViewOptions name_options() {
    dafree::ViewOptions options;
    options.sort = dafree::SortKey::Name;
    options.descending = false;
    return options;
}

} // namespace

TEST_SUITE("view") {

    TEST_CASE("expand_inserts_sorted_children") {
        auto tree = sample_tree();
        dafree::TreeView view(tree, name_options());
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 4, 3, 2});
        CHECK(view.expand(2) == 3);
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 4, 3, 2, 6, 5, 7});
        CHECK(view.expand(2) == 0);
        CHECK(view.expand(4) == 0);
        CHECK(view.expand(5) == 1);
        CHECK(view.rows(*view.index_of(8), 1).front().depth == 3);
    }

    TEST_CASE("collapse_removes_descendants") {
        dafree::TreeView view(sample_tree(), name_options());
        view.expand_to(8);
        CHECK(view.collapse(2) == 4);
        CHECK_FALSE(view.index_of(8).has_value());
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 4, 3, 2});
        CHECK(view.expand(2) == 4); // Preserve the nested directory's expansion preference.
        CHECK(view.index_of(8).has_value());
        CHECK(view.collapse(1) == 7);
        CHECK(view.row_count() == 1);
        CHECK(view.collapse(1) == 0);
        CHECK(view.expand(1) == 7);
    }

    TEST_CASE("natural_name_sort") {
        const std::vector<std::string> input{"file10",
                                             "file02",
                                             "file2",
                                             "file000",
                                             "file0",
                                             "file9999999999999999999999999",
                                             "file10000000000000000000000000",
                                             "\xC3\x84pfel10",
                                             "\xC3\xA4pfel2"};
        const std::vector<std::string> expected{"file0",
                                                "file000",
                                                "file2",
                                                "file02",
                                                "file10",
                                                "file9999999999999999999999999",
                                                "file10000000000000000000000000",
                                                "\xC3\xA4pfel2",
                                                "\xC3\x84pfel10"};
        dafree::TreeBuilder builder({"/names"});
        std::vector<dafree::TreeBuilder::NewNode> children;
        for (const auto &name : input)
            children.push_back({name, 0, 1, 1, 0, 0, 0, {}});
        builder.add_children(1, children);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        dafree::TreeView view(tree, name_options());
        std::vector<std::string> actual;
        for (const auto &row : view.rows(1, 100))
            actual.push_back(row.name);
        CHECK(actual == expected);
        auto options = name_options();
        options.descending = true;
        view.set_options(options);
        std::reverse(actual.begin(), actual.end());
        std::vector<std::string> descending;
        for (const auto &row : view.rows(1, 100))
            descending.push_back(row.name);
        CHECK(descending == actual);
    }

    TEST_CASE("filter_shows_ancestors_of_matches") {
        dafree::TreeView view(sample_tree(), name_options());
        auto options = name_options();
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::NameGlob;
        filter.values = {"NEEDLE*"};
        options.filter = filter;
        view.set_options(options);
        view.expand_to(8);
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 2, 5, 8});
        CHECK_FALSE(view.index_of(6).has_value());
        options.show_files = false;
        view.set_options(options);
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 2, 5});
        CHECK_FALSE(view.rows(2, 1).front().has_children);
        options.filter.reset();
        options.show_files = true;
        view.set_options(options);
        CHECK(view.row_count() == 8);
    }

    TEST_CASE("sort_each_key_both_directions") {
        constexpr std::uint32_t count = 120;
        std::mt19937 random(671);
        std::vector<std::string> names;
        std::vector<dafree::TreeBuilder::NewNode> entries;
        const std::array<std::string, 3> extensions{".bin", ".dat", ".txt"};
        names.reserve(count);
        for (std::uint32_t index = 0; index < count; ++index)
            names.push_back("item" + std::to_string(index) +
                            (index % 3 == 0 ? "" : extensions[index % 3]));
        for (std::uint32_t index = 0; index < count; ++index)
            entries.push_back(
                {names[index], static_cast<std::uint16_t>(index % 3 == 0 ? dafree::kDir : 0),
                 random() % 50u, random() % 70u, static_cast<std::uint32_t>(random() % 20u), 0, 0,
                 dafree::OwnerKey::posix_uid(index % 3)});
        dafree::TreeBuilder builder({"/sort"});
        builder.add_children(1, entries);
        for (std::uint32_t index = 0; index < count; index += 3) {
            std::vector<dafree::TreeBuilder::NewNode> children;
            for (std::uint32_t file = 0; file < index % 5; ++file)
                children.push_back({"child", 0, random() % 20u, random() % 40u, 1, 0, 0, {}});
            if (index % 2 != 0)
                children.push_back({"directory", dafree::kDir, 0, 0, 1, 0, 0, {}});
            builder.add_children(index + 2, children);
        }
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        const std::array<std::string, 3> owners{"alice", "bob", "zoe"};
        for (std::uint32_t index = 0; index < count; ++index)
            tree->set_owner(index + 2, dafree::OwnerKey::posix_uid(index % 3), owners[index % 3]);
        const std::array keys{
            dafree::SortKey::Name,      dafree::SortKey::Size,  dafree::SortKey::Alloc,
            dafree::SortKey::PctParent, dafree::SortKey::Files, dafree::SortKey::Dirs,
            dafree::SortKey::Mtime,     dafree::SortKey::Owner, dafree::SortKey::Ext};
        using Value = std::variant<std::uint64_t, std::string>;
        const auto value = [&](dafree::NodeId id, dafree::SortKey key) -> Value {
            switch (key) {
            case dafree::SortKey::Name:
                return std::uint64_t{id - 2};
            case dafree::SortKey::Size:
            case dafree::SortKey::PctParent:
                return tree->node(id).size;
            case dafree::SortKey::Alloc:
                return tree->node(id).alloc;
            case dafree::SortKey::Files:
                return std::uint64_t{tree->counts(id).files};
            case dafree::SortKey::Dirs:
                return std::uint64_t{tree->counts(id).dirs};
            case dafree::SortKey::Mtime:
                return std::uint64_t{tree->node(id).mtime};
            case dafree::SortKey::Owner:
                return std::string(*tree->owner_name(id));
            case dafree::SortKey::Ext:
                return std::string(tree->ext(id).value_or(""));
            }
            throw std::logic_error("oracle key");
        };
        dafree::TreeView view(tree, {});
        for (auto key : keys)
            for (bool descending : {false, true})
                for (bool directories : {false, true}) {
                    std::vector<dafree::NodeId> expected(count);
                    std::iota(expected.begin(), expected.end(),
                              2u); // Natural-name order is the fixture's numeric index.
                    std::stable_sort(expected.begin(), expected.end(), [&](auto a, auto b) {
                        return descending ? value(a, key) > value(b, key)
                                          : value(a, key) < value(b, key);
                    });
                    if (directories)
                        std::stable_partition(expected.begin(), expected.end(), [&](auto id) {
                            return (tree->node(id).flags & dafree::kDir) != 0;
                        });
                    dafree::ViewOptions options;
                    options.sort = key;
                    options.descending = descending;
                    options.dirs_first = directories;
                    view.set_options(options);
                    const auto rows = view.rows(1, count);
                    std::vector<dafree::NodeId> actual;
                    for (const auto &row : rows)
                        actual.push_back(row.id);
                    INFO("key=", static_cast<unsigned>(key), " descending=", descending,
                         " directories=", directories);
                    CHECK(actual == expected);
                }
    }

    TEST_CASE("view_chunked_rows_match_vector_after_random_splices") {
        constexpr std::uint32_t limit = 300'000;
        dafree::detail::VisibleRows rows(limit);
        std::vector<dafree::detail::RowRef> expected;
        std::mt19937 random(1741);
        dafree::NodeId next = 1;
        for (unsigned step = 0; step < 500; ++step) {
            if (expected.empty() || (random() % 2 == 0 && next + 1200 < limit)) {
                const auto count = random() % 1200 + 1;
                const auto at = static_cast<std::uint32_t>(random() % (expected.size() + 1));
                std::vector<dafree::detail::RowRef> inserted;
                for (std::uint32_t index = 0; index < count; ++index)
                    inserted.push_back({next++, static_cast<std::uint32_t>(random() % 12)});
                rows.insert(at, inserted);
                expected.insert(expected.begin() + at, inserted.begin(), inserted.end());
            } else {
                const auto at = static_cast<std::uint32_t>(random() % expected.size());
                const auto count = static_cast<std::uint32_t>(
                    std::min<std::size_t>(random() % 1800 + 1, expected.size() - at));
                const auto removed = expected[at].id;
                rows.erase(at, count);
                expected.erase(expected.begin() + at, expected.begin() + at + count);
                CHECK_FALSE(rows.index_of(removed).has_value());
            }
            REQUIRE(rows.size() == expected.size());
            std::size_t visited = 0;
            rows.visit(0, rows.size(), [&](const auto &row) {
                REQUIRE(visited < expected.size());
                CHECK(row.id == expected[visited].id);
                CHECK(row.depth == expected[visited].depth);
                ++visited;
                return true;
            });
            CHECK(visited == expected.size());
            for (unsigned sample = 0; sample < 12 && !expected.empty(); ++sample) {
                const auto at = static_cast<std::uint32_t>(random() % expected.size());
                CHECK(rows.at(at).id == expected[at].id);
                CHECK(rows.index_of(expected[at].id) == at);
            }
        }
    }

    TEST_CASE("view_filter_predicates_and_boolean_expressions") {
        using K = dafree::FilterSpec::Kind;
        auto tree = sample_tree();
        tree->set_owner(8, dafree::OwnerKey::posix_uid(42), "Alice");
        dafree::TreeView view(tree, name_options());
        view.expand_to(8);
        const auto check = [&](const dafree::FilterSpec &filter,
                               std::vector<dafree::NodeId> expected) {
            auto options = name_options();
            options.filter = filter;
            view.set_options(options);
            std::vector<dafree::NodeId> actual;
            for (const auto &row : view.rows(0, 500))
                if ((row.flags & dafree::kDir) == 0)
                    actual.push_back(row.id);
            std::sort(actual.begin(), actual.end());
            std::sort(expected.begin(), expected.end());
            CHECK(actual == expected);
        };
        dafree::FilterSpec size;
        size.kind = K::Size;
        size.cmp = {dafree::Cmp64::Gt, 3};
        check(size, {3, 7, 8});
        auto alloc = size;
        alloc.kind = K::Alloc;
        alloc.cmp = {dafree::Cmp64::Le, 8};
        check(alloc, {4, 6, 7});
        auto files = size;
        files.kind = K::Files;
        files.cmp = {dafree::Cmp64::Eq, 0};
        check(files, {3, 4, 6, 7, 8});
        dafree::FilterSpec ext;
        ext.kind = K::Ext;
        ext.values = {".TXT"};
        check(ext, {3, 4});
        auto glob = ext;
        glob.kind = K::NameGlob;
        glob.values = {"?.bin"};
        check(glob, {6, 7});
        auto path = glob;
        path.kind = K::PathGlob;
        path.values = {"**/nested/*"};
        check(path, {8});
        dafree::FilterSpec regex;
        regex.kind = K::Regex;
        regex.regex = "^FILE(?:2|10)\\.TXT$";
        check(regex, {3, 4});
        auto owner = glob;
        owner.kind = K::Owner;
        owner.values = {"ALICE"};
        check(owner, {8});
        auto time = size;
        time.kind = K::Time;
        time.cmp = {dafree::Cmp64::Ge, 10};
        check(time, {3, 8});
        time.time_field = dafree::TimeField::Created;
        time.cmp = {dafree::Cmp64::Lt, 100};
        check(time, {}); // Unknown timestamps are not accidentally classified as old files.
        time.time_field = dafree::TimeField::Accessed;
        time.cmp = {dafree::Cmp64::Eq, 0};
        check(time, {3, 4, 6, 7, 8});
        dafree::FilterSpec type;
        type.kind = K::Type;
        type.type_dir = true;
        check(type, {});
        type.type_dir = false;
        check(type, {3, 4, 6, 7, 8});
        dafree::FilterSpec flag;
        flag.kind = K::Flag;
        flag.flag = dafree::kHidden;
        check(flag, {3});
        dafree::FilterSpec combined;
        combined.kind = K::And;
        combined.children = {size, ext, type};
        check(combined, {3});
        combined.kind = K::Or;
        combined.children = {ext, owner};
        check(combined, {3, 4, 8});
        dafree::FilterSpec negated;
        negated.kind = K::Not;
        negated.children = {combined};
        check(negated, {6, 7});
    }

    TEST_CASE("view_regex_handles_invalid_utf_subjects_and_rejects_bad_patterns") {
        const std::string name = "bad-\xff.txt";
        dafree::TreeBuilder builder({"/invalid-utf"});
        const dafree::TreeBuilder::NewNode file{name, 0, 2, 2, 0, 0, 0, {}};
        builder.add_children(1, std::span(&file, 1));
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        auto options = name_options();
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::Regex;
        filter.regex = "\\.txt$";
        options.filter = filter;
        dafree::TreeView view(tree, options);
        REQUIRE(view.row_count() == 2);
        CHECK(view.rows(1, 1).front().name == name);
        const auto before = ids(view);
        options.filter->regex = "(";
        CHECK_THROWS_AS(view.set_options(options), std::invalid_argument);
        CHECK(ids(view) == before);
        CHECK(view.options().filter->regex == "\\.txt$");
        options.filter->regex = std::string(1u << 20, 'a');
        CHECK_THROWS_AS(view.set_options(options), std::invalid_argument);
        options.filter->regex.push_back('a');
        CHECK_THROWS_AS(view.set_options(options), std::invalid_argument);
        CHECK(ids(view) == before);
        options.filter->kind = dafree::FilterSpec::Kind::Not;
        options.filter->regex.clear();
        CHECK_THROWS_AS(view.set_options(options), std::invalid_argument);
        CHECK(ids(view) == before);
    }

    TEST_CASE("view_filters_apply_to_single_file_target_basename") {
        const auto path = dafree::platform::windows_paths() ? "C:/file.txt" : "/file.txt";
        dafree::RawEntry file;
        file.kind = dafree::EntryKind::File;
        file.size = file.alloc = 7;
        dafree::MockSpec spec;
        spec.entries.push_back({path, file});
        dafree::ScanOptions scan;
        scan.targets = {path};
        auto handle = dafree::start_scan(scan, dafree::make_mock_backend(std::move(spec)));
        REQUIRE(handle.wait(std::chrono::seconds(5)));
        auto result = handle.take_result();
        for (auto kind : {dafree::FilterSpec::Kind::NameGlob, dafree::FilterSpec::Kind::Ext,
                          dafree::FilterSpec::Kind::Regex}) {
            auto options = name_options();
            dafree::FilterSpec filter;
            filter.kind = kind;
            filter.values = kind == dafree::FilterSpec::Kind::Ext
                                ? std::vector<std::string>{"txt"}
                                : std::vector<std::string>{"file*"};
            filter.regex = "^file\\.txt$";
            options.filter = filter;
            dafree::TreeView view(result.tree, options);
            CHECK(view.row_count() == 1);
        }
    }

    TEST_CASE("view_filter_parallel_words_and_excluded_subtrees") {
        constexpr std::uint32_t count = 20'003;
        std::vector<std::string> names;
        std::vector<dafree::TreeBuilder::NewNode> files;
        names.reserve(count);
        files.reserve(count);
        for (std::uint32_t index = 0; index < count; ++index)
            names.push_back("file" + std::to_string(index));
        for (std::uint32_t index = 0; index < count; ++index)
            files.push_back({names[index], 0, index, index, 0, 0, 0, {}});
        dafree::TreeBuilder builder({"/parallel"});
        builder.add_children(1, files);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        auto options = name_options();
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::Size;
        filter.cmp = {dafree::Cmp64::Eq, 12'345};
        options.filter = filter;
        dafree::TreeView view(tree, options);
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 12'347});
        auto excluded = sample_tree();
        excluded->mark_deleted(2);
        filter.kind = dafree::FilterSpec::Kind::NameGlob;
        filter.values = {"needle*"};
        options.filter = filter;
        dafree::TreeView hidden(excluded, options);
        CHECK(hidden.row_count() == 0);
    }

    TEST_CASE("view_owner_resolution_uses_shared_context_and_cheapest_candidates") {
        dafree::TreeBuilder builder({"/owners"});
        const std::array<dafree::TreeBuilder::NewNode, 2> files{{
            {"small", 0, 1, 1, 0, 0, 0, dafree::OwnerKey::posix_uid(41)},
            {"large", 0, 100, 100, 0, 0, 0, dafree::OwnerKey::posix_uid(42)},
        }};
        builder.add_children(1, files);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        auto shared = std::make_shared<dafree::TreeHandle>(tree);
        dafree::MockSpec spec;
        spec.owner_names = {{41, "Bob"}, {42, "Alice"}};
        auto backend = std::make_shared<dafree::MockBackend>(std::move(spec));
        dafree::FilterSpec owner;
        owner.kind = dafree::FilterSpec::Kind::Owner;
        owner.values = {"Alice"};
        dafree::FilterSpec size;
        size.kind = dafree::FilterSpec::Kind::Size;
        size.cmp = {dafree::Cmp64::Gt, 10};
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::And;
        filter.children = {owner, size}; // Deliberately expensive-first input.
        auto options = name_options();
        options.filter = filter;
        options.resolve_owner = true;
        dafree::TreeView view(shared, backend, options);
        CHECK(backend->owner_resolution_calls() == 1);
        REQUIRE(ids(view) == std::vector<dafree::NodeId>{1, 3});
        CHECK(view.rows(1, 1).front().owner == "Alice");
        CHECK(tree->owner_name(3) == "Alice");
        CHECK(tree->node(2).owner != 0);
        CHECK(tree->owner_name(2).value_or("").empty());
        CHECK(backend->owner_resolution_calls() == 1);
        options.filter.reset();
        view.set_options(options);
        CHECK(view.rows(0, 500).size() == 3);
        CHECK(backend->owner_resolution_calls() == 2);
        CHECK(view.rows(0, 500).size() == 3);
        CHECK(backend->owner_resolution_calls() == 2);
    }

    TEST_CASE("view_pages_are_capped_and_unknown_owner_context_is_explicit") {
        dafree::TreeBuilder builder({"/pages"});
        std::vector<dafree::TreeBuilder::NewNode> files(700, {"file", 0, 1, 1, 0, 0, 0, {}});
        builder.add_children(1, files);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        dafree::TreeView view(tree, {});
        CHECK(view.rows(0, 10'000).size() == 500);
        CHECK(view.rows(699, 500).size() == 2);
        CHECK(view.rows(std::numeric_limits<std::uint32_t>::max(), 100).empty());
        CHECK_FALSE(view.index_of(dafree::kRoot).has_value());
        CHECK_THROWS_AS(view.expand(9999), std::out_of_range);
        CHECK_THROWS_AS(view.collapse(9999), std::out_of_range);
        tree->set_owner(2, dafree::OwnerKey::posix_uid(42), "");
        auto options = view.options();
        options.resolve_owner = true;
        view.set_options(options);
        CHECK_THROWS_AS((void)view.rows(0, 500), std::invalid_argument);
    }

    TEST_CASE("view_regex_match_budget_failure_is_explicit") {
        const std::string name = std::string(1000, 'a') + "!";
        dafree::TreeBuilder builder({"/bounded-match"});
        const dafree::TreeBuilder::NewNode file{name, 0, 1, 1, 0, 0, 0, {}};
        builder.add_children(1, std::span(&file, 1));
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        dafree::ViewOptions options;
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::Regex;
        filter.regex = "^(a+)+$";
        options.filter = filter;
        CHECK_THROWS_AS(dafree::TreeView(tree, options), std::runtime_error);
    }

    TEST_CASE("view_percent_sort_zero_parent_and_unknown_timestamps") {
        dafree::TreeBuilder builder({"/zero"});
        const std::array<dafree::TreeBuilder::NewNode, 2> files{{
            {"a", dafree::kHardlinkDup, 1, 1, 0, 0, 0, {}},
            {"b", dafree::kHardlinkDup, 2, 2, 0, 0, 0, {}},
        }};
        builder.add_children(1, files);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        dafree::ViewOptions options;
        options.sort = dafree::SortKey::PctParent;
        dafree::TreeView view(tree, options);
        CHECK(ids(view) == std::vector<dafree::NodeId>{1, 2, 3});
        for (const auto &row : view.rows(0, 500))
            CHECK(row.pct_parent == 0.0f);
    }

    TEST_CASE("view_concurrent_filtering_and_owner_resolution_share_reader_locks") {
        dafree::TreeBuilder builder({"/concurrent"});
        std::vector<dafree::TreeBuilder::NewNode> files;
        for (std::uint32_t i = 0; i < 9000; ++i)
            files.push_back({"file", 0, i, i, 0, 0, 0, dafree::OwnerKey::posix_uid(42)});
        builder.add_children(1, files);
        auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
        auto shared = std::make_shared<dafree::TreeHandle>(tree);
        dafree::MockSpec spec;
        spec.owner_names = {{42, "Alice"}};
        auto backend = std::make_shared<dafree::MockBackend>(std::move(spec));
        dafree::ViewOptions options;
        options.resolve_owner = true;
        dafree::FilterSpec filter;
        filter.kind = dafree::FilterSpec::Kind::Size;
        filter.cmp = {dafree::Cmp64::Ge, 4500};
        options.filter = filter;
        std::atomic<bool> correct{true};
        const auto read = [&] {
            for (unsigned i = 0; i < 3; ++i) {
                dafree::TreeView view(shared, backend, options);
                const auto rows = view.rows(1, 500);
                if (view.row_count() != 4501 || rows.size() != 500 ||
                    std::any_of(rows.begin(), rows.end(),
                                [](const auto &row) { return row.owner != "Alice"; }))
                    correct = false;
            }
        };
        std::thread first(read), second(read);
        const std::array<dafree::NodeId, 2> ids{2, 3};
        dafree::resolve_owners(*shared, ids, *backend);
        first.join();
        second.join();
        CHECK(correct.load());
        CHECK(tree->owner_name(2) == "Alice");
    }

} // TEST_SUITE

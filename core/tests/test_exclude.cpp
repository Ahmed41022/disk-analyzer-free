#include "../src/scan/glob.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

#include <array>
#include <string>

namespace {

#if defined(_WIN32) || defined(__APPLE__)
constexpr bool insensitive = true;
#else
constexpr bool insensitive = false;
#endif
#ifdef _WIN32
constexpr std::string_view root = "C:/root";
#else
constexpr std::string_view root = "/root";
#endif

} // namespace

TEST_CASE("exclude_semantics_table") {
    using dafree::EntryKind;
    struct Case {
        std::string glob, path, name;
        EntryKind kind;
        bool expected;
    };
    const std::array cases{
        Case{"node_modules", "a/b/node_modules", "node_modules", EntryKind::Dir, true},
        Case{"node_modules", "a/b/other", "other", EntryKind::Dir, false},
        Case{"build/**", "build", "build", EntryKind::Dir, true},
        Case{"build/**", "build/a/file", "file", EntryKind::File, true},
        Case{"build/**", "a/build/file", "file", EntryKind::File, false},
        Case{"build/*", "build/file", "file", EntryKind::File, true},
        Case{"build/*", "build/sub/file", "file", EntryKind::File, false},
        Case{"**/cache/**", "cache", "cache", EntryKind::Dir, true},
        Case{"**/cache/**", "a/cache/b/file", "file", EntryKind::File, true},
        Case{"*.TMP", "a/file.TMP", "file.TMP", EntryKind::File, true},
        Case{"*.TMP", "a/file.tmp", "file.tmp", EntryKind::File, insensitive},
        Case{"/cache", "a/cache", "cache", EntryKind::Dir, false},
        Case{"/cache", "cache", "cache", EntryKind::Dir, true},
        Case{"log?.txt", "log1.txt", "log1.txt", EntryKind::File, true},
        Case{"log?.txt", "log12.txt", "log12.txt", EntryKind::File, false},
        Case{"[ab].txt", "a.txt", "a.txt", EntryKind::File, true},
        Case{"[!a-c].txt", "z.txt", "z.txt", EntryKind::File, true},
        Case{"[!a-c].txt", "b.txt", "b.txt", EntryKind::File, false},
        Case{"file[0-9].bin", "file7.bin", "file7.bin", EntryKind::File, true},
        Case{"cache/", "a/cache", "cache", EntryKind::File, false},
        Case{"cache/", "a/cache", "cache", EntryKind::Dir, true},
        Case{"literal\\[1\\].txt", "literal[1].txt", "literal[1].txt", EntryKind::File, true},
        Case{"??.txt", "مل.txt", "مل.txt", EntryKind::File, true},
        Case{"Ä.TXT", "ä.txt", "ä.txt", EntryKind::File, insensitive},
        Case{"a/**/b", "a/b", "b", EntryKind::File, true},
        Case{"a/**/b", "a/x/y/b", "b", EntryKind::File, true},
        Case{"a/*/b", "a/b", "b", EntryKind::File, false},
        Case{"**/x", "x", "x", EntryKind::File, true},
        Case{"**/x", "a/b/x", "x", EntryKind::File, true},
        Case{"raw-\xFF", "raw-\xFF", "raw-\xFF", EntryKind::File, true}};
    for (const auto &test : cases) {
        CAPTURE(test.glob);
        CAPTURE(test.path);
        dafree::ExcludeRules rules;
        rules.globs.push_back(test.glob);
        const auto compiled = dafree::CompiledExcludes::compile(rules, root);
        dafree::RawEntry entry;
        entry.kind = test.kind;
        CHECK(compiled.excluded(test.path, test.name, entry) == test.expected);
    }
}

TEST_CASE("exclude_paths_and_attributes") {
    dafree::ExcludeRules rules;
    rules.paths = {std::string(root) + "/cache", std::string(root) + "/a/../build"};
    const auto compiled = dafree::CompiledExcludes::compile(rules, root);
    dafree::RawEntry entry;
    entry.kind = dafree::EntryKind::File;
    CHECK(compiled.excluded("cache", "cache", entry));
    CHECK(compiled.excluded("cache/sub/file", "file", entry));
    CHECK_FALSE(compiled.excluded("cache2/file", "file", entry));
    CHECK(compiled.excluded("build/file", "file", entry));
    CHECK_FALSE(compiled.excluded("a/build/file", "file", entry));
    rules.paths = {std::string(root)};
    CHECK(dafree::CompiledExcludes::compile(rules, root).excluded("anything", "anything", entry));
    rules.paths.clear();
    rules.hidden = true;
    const auto hidden = dafree::CompiledExcludes::compile(rules, root);
#ifdef _WIN32
    CHECK_FALSE(hidden.excluded(".dot", ".dot", entry));
#else
    CHECK(hidden.excluded(".dot", ".dot", entry));
#endif
    entry.hidden = true;
    CHECK(hidden.excluded("hidden", "hidden", entry));
    rules.hidden = false;
    rules.system = true;
    entry.hidden = false;
    entry.system = true;
    const auto system = dafree::CompiledExcludes::compile(rules, root);
#ifdef _WIN32
    CHECK(system.excluded("system", "system", entry));
#else
    CHECK_FALSE(system.excluded("system", "system", entry));
#endif
}

TEST_CASE("bad_glob_throws") {
    for (const std::string pattern : {"[", "[]", "[z-a]", "[!]", "abc\\", ""}) {
        dafree::ExcludeRules rules;
        rules.globs.push_back(pattern);
        CHECK_THROWS_AS(dafree::CompiledExcludes::compile(rules, root), dafree::ExcludeError);
    }
    dafree::ExcludeRules rules;
    rules.paths.push_back("relative/path");
    CHECK_THROWS_AS(dafree::CompiledExcludes::compile(rules, root), dafree::ExcludeError);
    rules.paths.clear();
    rules.globs = {"/broken["};
    try {
        (void)dafree::CompiledExcludes::compile(rules, root);
        FAIL("invalid glob was accepted");
    } catch (const dafree::ExcludeError &error) {
        CHECK(error.pattern == "/broken[");
    }
}

TEST_CASE("glob_matching_is_bounded") {
    const auto repeated = dafree::detail::CompiledGlob::compile("**a**a**a**a**c", false);
    CHECK_FALSE(repeated.matches(std::string(5000, 'a') + "b"));
    const std::string long_literal(300, 'a');
    CHECK(dafree::detail::CompiledGlob::compile(long_literal, false).matches(long_literal));
    CHECK_FALSE(
        dafree::detail::CompiledGlob::compile(long_literal, false).matches(long_literal + "b"));
}

TEST_CASE("glob_long_pattern_workspace_can_be_reused") {
    const std::string literal(300, 'a');
    const auto glob = dafree::detail::CompiledGlob::compile(literal + "*b", false);
    dafree::detail::CompiledGlob::Workspace workspace;
    CHECK(glob.matches(literal + "b", false, workspace));
    CHECK_FALSE(glob.matches(literal + "c", false, workspace));
    CHECK(glob.matches(literal + "xxb", false, workspace));
    CHECK_FALSE(glob.matches("b", false, workspace));
    CHECK(glob.matches(literal + "b", false, workspace));
}

#include "dafree/export.hpp"

#include <doctest/doctest.h>

#include <array>
#include <cstdint>
#include <locale>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using dafree::CsvOptions;
using dafree::NodeId;
using dafree::Tree;
using dafree::TreeBuilder;

constexpr std::string_view header = "path,name,type,size,alloc,pct_parent,files,dirs,mtime_iso,"
                                    "btime_iso,atime_iso,owner,ext,flags\r\n";

#ifdef _WIN32
constexpr std::string_view root = "C:\\scan";
constexpr char separator = '\\';
#else
constexpr std::string_view root = "/scan";
constexpr char separator = '/';
#endif

std::string path_with(std::string_view leaf) {
    return std::string(root) + separator + std::string(leaf);
}

class CommaDecimal final : public std::numpunct<char> {
  private:
    char do_decimal_point() const override { return ','; }
    char do_thousands_sep() const override { return '.'; }
    std::string do_grouping() const override { return "\3"; }
};

std::string serialize(const Tree &tree, const CsvOptions &options = {},
                      std::span<const NodeId> scopes = {}) {
    std::ostringstream output;
    output.imbue(std::locale(std::locale::classic(), new CommaDecimal));
    dafree::write_csv(tree, scopes, output, options);
    return output.str();
}

} // namespace

TEST_CASE("csv_header_exact") {
    auto tree = TreeBuilder(std::vector<std::string>{}).finish({});
    CHECK(serialize(tree) == header);
}

TEST_CASE("csv_rfc4180_quoting") {
    constexpr auto flags = static_cast<std::uint16_t>(dafree::kHidden | dafree::kSparse);
    constexpr std::string_view name = "comma,\"quote\"\r\nline\nLF\rCR.dat";
    TreeBuilder builder({std::string(root)});
    const std::array children{
        TreeBuilder::NewNode{name, flags, 9000, 1'234'567'890'123u, 1, 0, 2'147'483'648u, {}},
        TreeBuilder::NewNode{"peer.dat", 0, 9000, 4096, 0, 0, 0, {}}};
    const auto id = builder.add_children(1, children).first;
    auto tree = std::move(builder).finish({});
    tree.set_owner(id, dafree::OwnerKey::posix_uid(42), "A \"User\", Team");
    const std::array scopes{id};
    CsvOptions options;
    options.include_owner = true;

    const auto expected = std::string(header) + '"' +
                          path_with("comma,\"\"quote\"\"\r\nline\nLF\rCR.dat") +
                          "\",\"comma,\"\"quote\"\"\r\nline\nLF\rCR.dat\","
                          "file,9000,1234567890123,0.5,0,0,1970-01-01T00:00:01Z,,"
                          "2038-01-19T03:14:08Z,\"A \"\"User\"\", Team\",dat,hidden|sparse\r\n";
    CHECK(serialize(tree, options, scopes) == expected);
}

TEST_CASE("csv_excel_delimiter_and_repaired_utf8") {
    TreeBuilder builder({std::string(root)});
    const std::array children{TreeBuilder::NewNode{"a;\xff.dat", 0, 0, 0, 0, 0, 0, {}},
                              TreeBuilder::NewNode{"b;\xed\xa0\x80.dat", 0, 0, 0, 0, 0, 0, {}}};
    const auto [first, last] = builder.add_children(1, children);
    const auto tree = std::move(builder).finish({});
    const std::array scopes{first, last - 1};
    CsvOptions options;
    options.excel = true;
    options.delimiter = ';';
    const auto expected =
        std::string("\xef\xbb\xbf"
                    "path;name;type;size;alloc;pct_parent;files;dirs;mtime_iso;btime_iso;atime_iso;"
                    "owner;ext;flags\r\n\"") +
        path_with("a;\xef\xbf\xbd.dat") +
        "\";\"a;\xef\xbf\xbd.dat\";file;0;0;0;0;0;;;;;dat;\r\n\"" +
        path_with("b;\xef\xbf\xbd.dat") + "\";\"b;\xef\xbf\xbd.dat\";file;0;0;0;0;0;;;;;dat;\r\n";
    CHECK(serialize(tree, options, scopes) == expected);
}

TEST_CASE("csv_scoped_depth_files_and_excluded_subtrees") {
    TreeBuilder builder({std::string(root)});
    const std::array root_children{
        TreeBuilder::NewNode{"selected", dafree::kDir, 0, 0, 0, 0, 0, {}},
        TreeBuilder::NewNode{"elsewhere.dat", 0, 8, 8, 0, 0, 0, {}}};
    const auto scope = builder.add_children(1, root_children).first;
    constexpr auto excluded = static_cast<std::uint16_t>(dafree::kDir | dafree::kExcluded);
    const std::array scope_children{TreeBuilder::NewNode{"subdir", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                    TreeBuilder::NewNode{"entry.dat", 0, 8, 8, 0, 0, 0, {}},
                                    TreeBuilder::NewNode{"deleted", excluded, 0, 0, 0, 0, 0, {}}};
    const auto last = builder.add_children(scope, scope_children).second;
    const std::array nested{TreeBuilder::NewNode{"descendant.dat", 0, 1, 1, 0, 0, 0, {}}};
    builder.add_children(last - 1, nested);
    const auto tree = std::move(builder).finish({});
    const std::array scopes{scope};
    CsvOptions options;
    options.depth = std::uint16_t{0};
    const auto root_row = path_with("selected") + ",selected,directory,8,8,0.5,1,1,,,,,,dir\r\n";
    CHECK(serialize(tree, options, scopes) == std::string(header) + root_row);

    options.depth = std::uint16_t{1};
    options.include_files = false;
    const auto directory_row =
        path_with("selected") + separator + "subdir,subdir,directory,0,0,0,0,0,,,,,,dir\r\n";
    CHECK(serialize(tree, options, scopes) == std::string(header) + root_row + directory_row);

    options.depth.reset();
    options.include_files = true;
    const auto document = serialize(tree, options, scopes);
    CHECK(document.find(",entry.dat,file,") != std::string::npos);
    CHECK(document.find("elsewhere.dat") == std::string::npos);
    CHECK(document.find("deleted") == std::string::npos);
    CHECK(document.find("descendant.dat") == std::string::npos);
}

#include "dafree/model.hpp"

#include <doctest/doctest.h>

#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

TEST_CASE("roundtrip_arbitrary_bytes") {
    dafree::NameArena arena;
    std::string bytes{"folder/"};
    bytes.append("\xFF", 1);
    bytes.push_back('\0');
    bytes.append("\xD9\x85\xD9\x84\xD9\x81", 6);  // Arabic: ملف
    bytes.append("/\xE6\x96\x87\xE4\xBB\xB6", 7); // CJK: 文件
    bytes.append("/\xF0\x9F\x98\x80", 5);         // Emoji: 😀
    const std::string composed{"caf\xC3\xA9"};
    const std::string decomposed{"cafe\xCC\x81"};

    const auto [bytes_offset, bytes_length] = arena.push(bytes);
    const auto [composed_offset, composed_length] = arena.push(composed);
    const auto [decomposed_offset, decomposed_length] = arena.push(decomposed);

    CHECK(arena.get(bytes_offset, bytes_length) == bytes);
    CHECK(arena.get(composed_offset, composed_length) == composed);
    CHECK(arena.get(decomposed_offset, decomposed_length) == decomposed);
    CHECK(arena.get(composed_offset, composed_length) !=
          arena.get(decomposed_offset, decomposed_length));
    CHECK(arena.heap_bytes() == 1024 * 1024);
}

TEST_CASE("name_chunks_keep_names_contiguous_and_enforce_length") {
    dafree::NameArena arena;
    const std::string maximum_name(std::numeric_limits<std::uint16_t>::max(), 'x');
    std::vector<std::pair<std::uint32_t, std::uint16_t>> names;
    for (int i = 0; i < 17; ++i) {
        names.push_back(arena.push(maximum_name));
    }

    CHECK(arena.heap_bytes() == 2 * 1024 * 1024);
    CHECK(names[15].first < 1024 * 1024);
    CHECK(names[16].first == 1024 * 1024);
    for (const auto &[offset, length] : names) {
        CHECK(length == maximum_name.size());
        CHECK(arena.get(offset, length) == maximum_name);
    }
    CHECK_THROWS_AS(arena.push(std::string(65'536, 'y')), dafree::NameTooLong);
}

TEST_CASE("ext_rules_table") {
    dafree::ExtInterner extensions;
    const auto text_id = extensions.intern("a.TXT");
    CHECK(text_id != 0);
    CHECK(extensions.get(text_id) == "txt");
    CHECK(extensions.intern("other.txt") == text_id);
    CHECK(extensions.get(extensions.intern("archive.tar.gz")) == "gz");
    CHECK(extensions.intern(".bashrc") == 0);
    CHECK(extensions.intern("noext") == 0);
    CHECK(extensions.intern("x.verylongextension123") == 0);
    CHECK(extensions.intern("my file.a b") == 0);
    CHECK(extensions.intern("a.\xC2\xA0") == 0); // No-break space.
    CHECK(extensions.intern("a.TXT", true) == 0);

    const auto umlaut_id = extensions.intern("a.\xC3\x84"
                                             "BC"); // ÄBC
    CHECK(extensions.get(umlaut_id) == "\xC3\xA4"
                                       "bc"); // äbc
    CHECK(extensions.intern("a.\xCE\xA3") == extensions.intern("a.\xCF\x82"));
    const auto invalid_utf8_id = extensions.intern("a.\xFF");
    CHECK(invalid_utf8_id != 0);
    CHECK(extensions.get(invalid_utf8_id) == "\xFF");
    CHECK(extensions.get(0).empty());
}

TEST_CASE("owner_table_dedups_keys") {
    dafree::OwnerTable owners;
    const auto alice = dafree::OwnerKey::posix_uid(1000);
    const auto alice_id = owners.intern(alice, "alice");

    CHECK(alice_id != 0);
    CHECK(owners.intern(dafree::OwnerKey::posix_uid(1000), "other spelling") == alice_id);
    CHECK(owners.get(alice_id) == "alice");

    const std::string binary_sid{"\x01\x02\x03", 3};
    const auto sid_id = owners.intern(dafree::OwnerKey::windows_sid(binary_sid), "S-1-5-21");
    CHECK(owners.intern(dafree::OwnerKey::windows_sid(binary_sid), "another display") == sid_id);
    CHECK(owners.get(sid_id) == "S-1-5-21");

    const auto remote_id = owners.intern(dafree::OwnerKey::remote(binary_sid), "remote user");
    CHECK(remote_id != sid_id);
    CHECK(remote_id != alice_id);
    CHECK(owners.intern(dafree::OwnerKey::remote(binary_sid), "other remote display") == remote_id);
    CHECK(owners.get(remote_id) == "remote user");
    CHECK(owners.get(0).empty());
}

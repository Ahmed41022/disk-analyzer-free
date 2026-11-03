#pragma once

#include "dafree/mft.hpp"

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace dafree::mft_detail {

void append_utf8(std::string &output, char32_t value);

struct IndexedName {
    std::uint64_t parent;
    std::uint8_t name_space;
    std::string name;
};

struct IndexedStream {
    std::string name;
    std::uint64_t size, alloc;
};

struct IndexedRecord {
    RecordHeader header{};
    std::optional<MftError> error;
    bool duplicate = false, reparse = false;
    std::optional<StdInfo> standard;
    std::vector<IndexedName> names;
    std::vector<IndexedStream> streams;
};

struct IndexData {
    std::unordered_map<std::uint64_t, IndexedRecord> records;
};

} // namespace dafree::mft_detail

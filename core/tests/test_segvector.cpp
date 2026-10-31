#include "dafree/model.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <concepts>
#include <cstdint>
#include <random>
#include <span>
#include <vector>

static_assert(std::random_access_iterator<dafree::SegVector<int>::iterator>);
static_assert(std::random_access_iterator<dafree::SegVector<int>::const_iterator>);

namespace {

template <class T> std::uint64_t field(const T &value) {
    if constexpr (std::is_same_v<T, dafree::Node>)
        return value.size;
    else if constexpr (std::is_same_v<T, dafree::Counts>)
        return value.files;
    else
        return static_cast<std::uint64_t>(value);
}

template <class T> T item(unsigned value) {
    T result{};
    if constexpr (std::is_same_v<T, dafree::Node>)
        result.size = value;
    else if constexpr (std::is_same_v<T, dafree::Counts>)
        result.files = value;
    else
        result = static_cast<T>(value);
    return result;
}

template <class T> void check_container_contract() {
    dafree::SegVector<T> actual;
    std::vector<T> expected;
    actual.shrink_last();
    CHECK(actual.begin() == actual.end());
    CHECK(actual.heap_bytes() == 0);
    const auto equal = [](const T &a, const T &b) { return field(a) == field(b); };
    actual.push_back(item<T>(4));
    actual.push_back(item<T>(1));
    expected = {item<T>(4), item<T>(1), item<T>(9), item<T>(2)};
    const std::array addition{item<T>(9), item<T>(2)};
    CHECK(actual.append(addition) == std::pair<std::uint32_t, std::uint32_t>{2, 4});
    const auto &constant = actual;
    CHECK(std::equal(constant.cbegin(), constant.cend(), expected.begin(), equal));
    CHECK(std::equal(constant.rbegin(), constant.rend(), expected.rbegin(), equal));
    CHECK(field(constant[2]) == 9);
    typename dafree::SegVector<T>::iterator cursor;
    cursor = actual.begin();
    CHECK(field(*cursor.operator->()) == 4);
    CHECK(field(*cursor++) == 4);
    CHECK(field(cursor[1]) == 9);
    CHECK(field(*(2 + actual.begin())) == 9);
    CHECK(field(*(actual.end() - 1)) == 2);
    CHECK(actual.end() - actual.begin() == 4);
    auto tail = actual.end();
    CHECK(tail-- == actual.end());
    CHECK(field(*tail) == 2);
    typename dafree::SegVector<T>::const_iterator converted(actual.begin());
    CHECK(converted == constant.begin());
    CHECK(field(*converted.operator->()) == 4);
    CHECK(field(*converted++) == 4);
    CHECK(field(converted[1]) == 9);
    auto const_tail = constant.end();
    CHECK(const_tail-- == constant.end());
    CHECK(field(*const_tail) == 2);
    const auto less = [](const T &a, const T &b) { return field(a) < field(b); };
    std::sort(actual.begin(), actual.end(), less);
    std::sort(expected.begin(), expected.end(), less);
    CHECK(std::equal(actual.begin(), actual.end(), expected.begin(), equal));
    actual.shrink_last();
    actual.shrink_last();
    CHECK(actual.heap_bytes() == expected.size() * sizeof(T));
    CHECK(actual.append({}).first == expected.size());
    actual.push_back(item<T>(7));
    CHECK(field(actual[4]) == 7);
    CHECK(field(constant[4]) == 7);
    CHECK(field(*constant.rbegin()) == 7);
}

} // namespace

TEST_CASE("segvector_standard_algorithm_contract_for_model_types") {
    check_container_contract<int>();
    check_container_contract<std::uint32_t>();
    check_container_contract<std::uint64_t>();
    check_container_contract<dafree::Node>();
    check_container_contract<dafree::Counts>();
}

TEST_CASE("push_get_across_segments") {
    dafree::SegVector<std::uint32_t> values;
    constexpr std::uint32_t count = 65'536 + 17;

    for (std::uint32_t i = 0; i < count; ++i) {
        CHECK(values.push_back(i * 3) == i);
    }

    CHECK(values.size() == count);
    CHECK(values[0] == 0);
    CHECK(values[65'535] == 65'535 * 3);
    CHECK(values[65'536] == 65'536 * 3);
    CHECK(values[count - 1] == (count - 1) * 3);
}

TEST_CASE("append_returns_contiguous_range") {
    dafree::SegVector<int> values;
    for (int i = 0; i < 65'530; ++i) {
        values.push_back(i);
    }
    const std::vector<int> addition{11, 12, 13, 14, 15, 16, 17, 18, 19, 20};

    const auto [first, last] = values.append(addition);

    CHECK(first == 65'530);
    CHECK(last == 65'540);
    CHECK(last - first == addition.size());
    for (std::uint32_t i = first; i < last; ++i) {
        CHECK(values[i] == addition[i - first]);
    }
}

TEST_CASE("shrink_last_reduces_heap_bytes") {
    dafree::SegVector<std::uint64_t> values;
    values.push_back(1);
    values.push_back(2);
    const auto allocated = values.heap_bytes();

    values.shrink_last();

    CHECK(allocated == 65'536 * sizeof(std::uint64_t));
    CHECK(values.heap_bytes() == values.size() * sizeof(std::uint64_t));
    CHECK(values[0] == 1);
    CHECK(values[1] == 2);

    // A later append starts a fresh segment and preserves the shrunken values.
    CHECK(values.push_back(3) == 2);
    CHECK(values[2] == 3);
}

TEST_CASE("matches_std_vector_random_ops") {
    dafree::SegVector<int> actual;
    std::vector<int> expected;
    std::mt19937 random(0xDAFEE);

    for (int operation = 0; operation < 10'000; ++operation) {
        const auto kind = random() % 4;
        if (kind < 2 || expected.empty()) {
            const auto value = static_cast<int>(random());
            CHECK(actual.push_back(value) == expected.size());
            expected.push_back(value);
        } else if (kind == 2) {
            const auto count = static_cast<std::size_t>(random() % 12);
            std::vector<int> addition;
            addition.reserve(count);
            for (std::size_t i = 0; i < count; ++i) {
                addition.push_back(static_cast<int>(random()));
            }
            const auto [first, last] = actual.append(addition);
            CHECK(first == expected.size());
            CHECK(last == expected.size() + addition.size());
            expected.insert(expected.end(), addition.begin(), addition.end());
        } else {
            actual.shrink_last();
        }

        REQUIRE(actual.size() == expected.size());
        if (operation % 100 == 0 || operation == 9'999) {
            CHECK(std::equal(actual.begin(), actual.end(), expected.begin(), expected.end()));
            CHECK(std::equal(actual.rbegin(), actual.rend(), expected.rbegin(), expected.rend()));
        }
        if (!expected.empty()) {
            const auto index = static_cast<std::uint32_t>(random() % expected.size());
            CHECK(actual[index] == expected[index]);
        }
    }
}

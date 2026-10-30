#pragma once

#include "dafree/error.hpp"

#include <algorithm>
#include <compare>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <limits>
#include <memory>
#include <span>
#include <type_traits>
#include <utility>
#include <vector>

namespace dafree {

/// A segmented vector that preserves existing segments as it grows.
///
/// Segments contain at most 65,536 values. Appending never moves values from
/// earlier segments. The returned indices describe a contiguous logical range,
/// even when the range spans multiple segments.
template <class T> class SegVector {
  private:
    static constexpr std::uint32_t kSegmentSize = 65'536;
    static constexpr std::uint32_t kMaxSize = std::numeric_limits<std::uint32_t>::max() - 1;

    struct Segment {
        std::uint32_t begin;
        std::uint32_t capacity;
        std::unique_ptr<T[]> values;
    };

    template <bool IsConst> class Iterator {
      private:
        using Owner = std::conditional_t<IsConst, const SegVector, SegVector>;

      public:
        using iterator_category = std::random_access_iterator_tag;
        using iterator_concept = std::random_access_iterator_tag;
        using value_type = T;
        using difference_type = std::ptrdiff_t;
        using reference = std::conditional_t<IsConst, const T &, T &>;
        using pointer = std::conditional_t<IsConst, const T *, T *>;

        Iterator() = default;
        Iterator(Owner *owner, std::uint32_t index) : owner_(owner), index_(index) {}

        template <bool OtherConst>
            requires(IsConst && !OtherConst)
        Iterator(const Iterator<OtherConst> &other) : owner_(other.owner_), index_(other.index_) {}

        reference operator*() const { return (*owner_)[index_]; }
        pointer operator->() const { return &(**this); }
        reference operator[](difference_type offset) const { return *(*this + offset); }

        Iterator &operator++() {
            ++index_;
            return *this;
        }
        Iterator operator++(int) {
            auto previous = *this;
            ++*this;
            return previous;
        }
        Iterator &operator--() {
            --index_;
            return *this;
        }
        Iterator operator--(int) {
            auto previous = *this;
            --*this;
            return previous;
        }
        Iterator &operator+=(difference_type offset) {
            index_ = static_cast<std::uint32_t>(static_cast<difference_type>(index_) + offset);
            return *this;
        }
        Iterator &operator-=(difference_type offset) { return *this += -offset; }

        friend Iterator operator+(Iterator iterator, difference_type offset) {
            iterator += offset;
            return iterator;
        }
        friend Iterator operator+(difference_type offset, Iterator iterator) {
            iterator += offset;
            return iterator;
        }
        friend Iterator operator-(Iterator iterator, difference_type offset) {
            iterator -= offset;
            return iterator;
        }
        friend difference_type operator-(const Iterator &lhs, const Iterator &rhs) {
            return static_cast<difference_type>(lhs.index_) -
                   static_cast<difference_type>(rhs.index_);
        }
        friend bool operator==(const Iterator &lhs, const Iterator &rhs) {
            return lhs.owner_ == rhs.owner_ && lhs.index_ == rhs.index_;
        }
        friend auto operator<=>(const Iterator &lhs, const Iterator &rhs) {
            return lhs.index_ <=> rhs.index_;
        }

      private:
        template <bool> friend class Iterator;

        Owner *owner_ = nullptr;
        std::uint32_t index_ = 0;
    };

  public:
    using value_type = T;
    using size_type = std::uint32_t;
    using iterator = Iterator<false>;
    using const_iterator = Iterator<true>;
    using reverse_iterator = std::reverse_iterator<iterator>;
    using const_reverse_iterator = std::reverse_iterator<const_iterator>;

    /// Append one value and return its index. Throws CapacityError at the size limit.
    std::uint32_t push_back(const T &value) {
        if (size_ == kMaxSize) {
            throw CapacityError();
        }
        ensure_tail_capacity();
        const auto index = size_;
        auto &segment = segments_.back();
        segment.values[index - segment.begin] = value;
        ++size_;
        return index;
    }

    /// Append a span and return its contiguous logical half-open index range.
    std::pair<std::uint32_t, std::uint32_t> append(std::span<const T> values) {
        const auto count = values.size();
        if (count > static_cast<std::size_t>(kMaxSize - size_)) {
            throw CapacityError();
        }
        const auto first = size_;
        for (const auto &value : values) {
            push_back(value);
        }
        return {first, size_};
    }

    /// Return the value at an index without bounds checking.
    T &operator[](std::uint32_t index) {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the value at an index without bounds checking.
    const T &operator[](std::uint32_t index) const {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the number of stored values.
    [[nodiscard]] std::uint32_t size() const noexcept { return size_; }

    /// Return the bytes reserved by segment arrays.
    [[nodiscard]] std::size_t heap_bytes() const noexcept {
        std::size_t bytes = 0;
        for (const auto &segment : segments_) {
            bytes += static_cast<std::size_t>(segment.capacity) * sizeof(T);
        }
        return bytes;
    }

    /// Reallocate the final segment to exactly the number of values it holds.
    void shrink_last() {
        if (segments_.empty()) {
            return;
        }
        auto &segment = segments_.back();
        const auto used = size_ - segment.begin;
        if (used == segment.capacity) {
            return;
        }
        if (used == 0) {
            segments_.pop_back();
            return;
        }
        auto values = std::make_unique_for_overwrite<T[]>(used);
        for (std::uint32_t i = 0; i < used; ++i) {
            values[i] = std::move_if_noexcept(segment.values[i]);
        }
        segment.values = std::move(values);
        segment.capacity = used;
    }

    /// Return an iterator to the first value.
    iterator begin() noexcept { return {this, 0}; }
    /// Return an iterator past the final value.
    iterator end() noexcept { return {this, size_}; }
    /// Return a const iterator to the first value.
    const_iterator begin() const noexcept { return {this, 0}; }
    /// Return a const iterator past the final value.
    const_iterator end() const noexcept { return {this, size_}; }
    /// Return a const iterator to the first value.
    const_iterator cbegin() const noexcept { return begin(); }
    /// Return a const iterator past the final value.
    const_iterator cend() const noexcept { return end(); }
    /// Return a reverse iterator to the final value.
    reverse_iterator rbegin() noexcept { return reverse_iterator(end()); }
    /// Return a reverse iterator before the first value.
    reverse_iterator rend() noexcept { return reverse_iterator(begin()); }
    /// Return a const reverse iterator to the final value.
    const_reverse_iterator rbegin() const noexcept { return const_reverse_iterator(end()); }
    /// Return a const reverse iterator before the first value.
    const_reverse_iterator rend() const noexcept { return const_reverse_iterator(begin()); }

  private:
    void ensure_tail_capacity() {
        if (!segments_.empty()) {
            const auto &tail = segments_.back();
            if (size_ - tail.begin < tail.capacity) {
                return;
            }
        }
        segments_.push_back(
            {size_, kSegmentSize, std::make_unique_for_overwrite<T[]>(kSegmentSize)});
    }

    [[nodiscard]] std::size_t find_segment(std::uint32_t index) const {
        const auto it = std::upper_bound(
            segments_.begin(), segments_.end(), index,
            [](std::uint32_t value, const Segment &segment) { return value < segment.begin; });
        return static_cast<std::size_t>(std::distance(segments_.begin(), it) - 1);
    }

    std::vector<Segment> segments_;
    std::uint32_t size_ = 0;
};

} // namespace dafree

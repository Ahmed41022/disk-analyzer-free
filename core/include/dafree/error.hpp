#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>

namespace dafree {

/// Base class for recoverable errors reported by the core library.
class Error : public std::runtime_error {
  public:
    /// Construct an error with a human-readable diagnostic.
    explicit Error(const std::string &message) : std::runtime_error(message) {}
};

/// Raised when an index would exceed the supported node capacity.
class CapacityError : public Error {
  public:
    /// Construct a capacity error.
    CapacityError() : Error("capacity exceeded") {}
};

/// Raised when a stored name exceeds the supported byte length.
class NameTooLong : public Error {
  public:
    /// Construct a name length error.
    NameTooLong() : Error("name exceeds 65535 bytes") {}
};

/// Raised when a directory is populated more than once.
class AlreadyPopulated : public Error {
  public:
    /// Construct an already populated error.
    AlreadyPopulated() : Error("directory is already populated") {}
};

/// Raised when the user cancels an operation at an operating-system prompt.
class Cancelled : public Error {
  public:
    using Error::Error;
};

/// Raised when a requested platform service is unavailable.
class Unsupported : public Error {
  public:
    using Error::Error;
};

/// A value-or-error result for APIs that report expected failures.
template <typename T, typename E> class Expected {
  public:
    /// Construct a successful result.
    Expected(T value) : storage_(std::in_place_index<0>, std::move(value)) {}

    /// Construct a failed result.
    Expected(E error) : storage_(std::in_place_index<1>, std::move(error)) {}

    /// Return true when the result contains a value.
    [[nodiscard]] auto has_value() const noexcept -> bool { return storage_.index() == 0; }

    /// Return the contained value.
    [[nodiscard]] auto value() -> T & { return std::get<0>(storage_); }

    /// Return the contained value.
    [[nodiscard]] auto value() const -> const T & { return std::get<0>(storage_); }

    /// Return the contained error.
    [[nodiscard]] auto error() -> E & { return std::get<1>(storage_); }

    /// Return the contained error.
    [[nodiscard]] auto error() const -> const E & { return std::get<1>(storage_); }

  private:
    std::variant<T, E> storage_;
};

/// A value-or-error result for operations that return no value on success.
template <typename E> class Expected<void, E> {
  public:
    /// Construct a successful result.
    Expected() = default;

    /// Construct a failed result.
    Expected(E error) : error_(std::move(error)) {}

    /// Return true when the result represents success.
    [[nodiscard]] auto has_value() const noexcept -> bool { return !error_.has_value(); }

    /// Return the contained error.
    [[nodiscard]] auto error() -> E & {
        if (!error_)
            throw std::bad_optional_access();
        return *error_;
    }

    /// Return the contained error.
    [[nodiscard]] auto error() const -> const E & {
        if (!error_)
            throw std::bad_optional_access();
        return *error_;
    }

  private:
    std::optional<E> error_;
};

} // namespace dafree

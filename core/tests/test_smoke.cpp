#include "dafree/error.hpp"

#include <doctest/doctest.h>

TEST_CASE("native test harness is available") { CHECK(true); }

TEST_CASE("void expected errors preserve checked access") {
    dafree::Expected<void, int> success;
    CHECK(success.has_value());
    CHECK_THROWS_AS(static_cast<void>(success.error()), std::bad_optional_access);
    const auto &constant_success = success;
    CHECK_THROWS_AS(static_cast<void>(constant_success.error()), std::bad_optional_access);

    dafree::Expected<void, int> failure(7);
    CHECK_FALSE(failure.has_value());
    CHECK(failure.error() == 7);
    failure.error() = 9;
    const auto &constant_failure = failure;
    CHECK(constant_failure.error() == 9);
}

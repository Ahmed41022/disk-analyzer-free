#include "dafree/platform.hpp"

#include <doctest/doctest.h>
#include <stdexcept>

TEST_CASE("verbatim_conversion_table") {
    using dafree::platform::to_verbatim;
    CHECK(to_verbatim("C:\\x") == "\\\\?\\C:\\x");
    CHECK(to_verbatim("C:/x/y") == "\\\\?\\C:\\x\\y");
    CHECK(to_verbatim("\\\\srv\\sh\\x") == "\\\\?\\UNC\\srv\\sh\\x");
    CHECK(to_verbatim("\\\\?\\C:\\x") == "\\\\?\\C:\\x");
    CHECK(to_verbatim("\\\\?\\UNC\\srv\\sh\\x") == "\\\\?\\UNC\\srv\\sh\\x");
    CHECK_THROWS_AS(to_verbatim("relative"), std::invalid_argument);
    CHECK_THROWS_AS(to_verbatim("C:relative"), std::invalid_argument);
    CHECK_THROWS_AS(to_verbatim("\\root-relative"), std::invalid_argument);
    CHECK_THROWS_AS(to_verbatim("\\\\server"), std::invalid_argument);
    CHECK_THROWS_AS(to_verbatim("\\\\.\\device"), std::invalid_argument);
}

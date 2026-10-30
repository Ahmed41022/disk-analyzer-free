cmake_minimum_required(VERSION 3.26)
project(dafree LANGUAGES CXX)

option(DAFREE_BUILD_TESTS "Build native tests" ON)
option(DAFREE_BUILD_BENCH "Build benchmarks" OFF)
option(DAFREE_BUILD_FUZZ "Build fuzz targets" OFF)
set(DAFREE_SANITIZE "" CACHE STRING "Comma-separated sanitizers")

# Permit legacy minimums in small, vendored header-only dependencies with CMake 4.
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

if(DAFREE_BUILD_TESTS)
  include(CTest)
endif()

if(DEFINED SKBUILD_PROJECT_VERSION AND NOT SKBUILD_PROJECT_VERSION STREQUAL "")
  set(DAFREE_VERSION "${SKBUILD_PROJECT_VERSION}")
else()
  file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml" _version_line REGEX "^version = ")
  string(REGEX MATCH "version = \"([^\"]+)\"" _version_match "${_version_line}")
  set(DAFREE_VERSION "${CMAKE_MATCH_1}")
endif()
if(DAFREE_VERSION STREQUAL "")
  message(FATAL_ERROR "Could not determine the package version from pyproject.toml")
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(CompilerWarnings)
include(Sanitizers)
find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module Development.SABIModule)
include(Dependencies)

add_subdirectory(core)
add_subdirectory(bindings)

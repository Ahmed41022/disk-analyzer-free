cmake_minimum_required(VERSION 3.26)
project(dafree LANGUAGES CXX)

option(DAFREE_BUILD_TESTS "Build native tests" ON)
option(DAFREE_BUILD_BENCH "Build benchmarks" OFF)
option(DAFREE_BUILD_FUZZ "Build fuzz targets" OFF)
option(DAFREE_COVERAGE "Instrument native test coverage with GCC" OFF)
set(DAFREE_SANITIZE "" CACHE STRING "Comma-separated sanitizers")

if(DAFREE_COVERAGE)
  if(NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    message(FATAL_ERROR "DAFREE_COVERAGE currently requires GCC and gcov")
  endif()
  add_compile_options(--coverage -O0 -g)
  add_link_options(--coverage)
endif()

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

set(DAFREE_LOCALES en_US ar de)
set(_dafree_mo_files)
foreach(_locale IN LISTS DAFREE_LOCALES)
  set(_po_file "${CMAKE_CURRENT_SOURCE_DIR}/src/dafree/i18n/locales/${_locale}/LC_MESSAGES/dafree.po")
  set(_mo_dir "${CMAKE_CURRENT_BINARY_DIR}/i18n/${_locale}/LC_MESSAGES")
  set(_mo_file "${_mo_dir}/dafree.mo")
  add_custom_command(
    OUTPUT "${_mo_file}"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${_mo_dir}"
    COMMAND "${Python_EXECUTABLE}" -m babel.messages.frontend compile
            --input-file "${_po_file}" --output-file "${_mo_file}"
            --domain dafree --locale "${_locale}"
    DEPENDS "${_po_file}"
    COMMENT "Compiling ${_locale} gettext catalogue"
    VERBATIM
  )
  list(APPEND _dafree_mo_files "${_mo_file}")
  install(FILES "${_mo_file}"
          DESTINATION "dafree/i18n/locales/${_locale}/LC_MESSAGES")
endforeach()
add_custom_target(dafree_translations ALL DEPENDS ${_dafree_mo_files})

if(DAFREE_BUILD_BENCH)
  FetchContent_MakeAvailable(benchmark)
endif()

add_subdirectory(core)
add_subdirectory(bindings)
add_dependencies(_core dafree_translations)

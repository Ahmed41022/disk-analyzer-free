add_library(dafree_core STATIC src/version.cpp src/units.cpp src/model/aggregate.cpp src/model/builder.cpp
                                src/model/intern.cpp src/model/names.cpp src/model/segvector.cpp
                                src/model/tree.cpp)
target_include_directories(dafree_core PUBLIC include)
target_compile_features(dafree_core PUBLIC cxx_std_20)
set_target_properties(dafree_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_compile_definitions(dafree_core PUBLIC DAFREE_VERSION="${DAFREE_VERSION}")
dafree_enable_warnings(dafree_core)

if(UNIX)
  target_sources(dafree_core PRIVATE src/platform/posix/read_dir.cpp
                                    src/platform/posix/stat.cpp
                                    src/platform/posix/owner.cpp
                                    src/platform/common/volume.cpp)
  if(APPLE)
    target_sources(dafree_core PRIVATE src/platform/macos/getattrlistbulk.cpp
                                      src/platform/macos/volume_macos.cpp)
  else()
    target_sources(dafree_core PRIVATE src/platform/linux/statx.cpp
                                      src/platform/linux/volume_linux.cpp)
  endif()
endif()

if(DAFREE_BUILD_TESTS)
  add_executable(dafree_core_tests tests/test_smoke.cpp tests/test_names.cpp
                                     tests/test_aggregate.cpp tests/test_segvector.cpp
                                     tests/test_tree.cpp tests/test_units.cpp)
  target_link_libraries(dafree_core_tests PRIVATE doctest::doctest_with_main dafree_core)
  if(UNIX)
    target_sources(dafree_core_tests PRIVATE tests/test_posix_enum.cpp)
  endif()
  target_compile_features(dafree_core_tests PRIVATE cxx_std_20)
  dafree_enable_warnings(dafree_core_tests)
  add_test(NAME dafree_core_tests COMMAND dafree_core_tests)
endif()

if(DAFREE_BUILD_BENCH)
  add_subdirectory(bench)
endif()

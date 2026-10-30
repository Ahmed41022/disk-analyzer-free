add_library(dafree_core STATIC src/version.cpp src/units.cpp src/model/aggregate.cpp src/model/builder.cpp
                                src/model/intern.cpp src/model/names.cpp src/model/segvector.cpp
                                src/model/tree.cpp)
target_include_directories(dafree_core PUBLIC include)
target_compile_features(dafree_core PUBLIC cxx_std_20)
target_compile_definitions(dafree_core PUBLIC DAFREE_VERSION="${DAFREE_VERSION}")
dafree_enable_warnings(dafree_core)

if(DAFREE_BUILD_TESTS)
  add_executable(dafree_core_tests tests/test_smoke.cpp tests/test_names.cpp
                                     tests/test_aggregate.cpp tests/test_segvector.cpp
                                     tests/test_tree.cpp tests/test_units.cpp)
  target_link_libraries(dafree_core_tests PRIVATE doctest::doctest_with_main dafree_core)
  target_compile_features(dafree_core_tests PRIVATE cxx_std_20)
  dafree_enable_warnings(dafree_core_tests)
  add_test(NAME dafree_core_tests COMMAND dafree_core_tests)
endif()

if(DAFREE_BUILD_BENCH)
  add_subdirectory(bench)
endif()

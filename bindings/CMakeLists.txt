nanobind_add_module(_core STABLE_ABI NB_STATIC LTO NB_SUPPRESS_WARNINGS
  src/module.cpp src/strings.cpp src/scan_bind.cpp src/tree_bind.cpp src/view_bind.cpp src/testing_bind.cpp)
target_compile_features(_core PRIVATE cxx_std_20)
if(MINGW AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_EQUAL "15.1.0")
  # This optional local toolchain ICEs in nanobind's wrap_move during the LTO alias pass.
  # Keep Release optimization; official Windows wheels use MSVC with LTO unchanged.
  set_property(TARGET _core PROPERTY INTERPROCEDURAL_OPTIMIZATION_RELEASE OFF)
endif()
target_link_libraries(_core PRIVATE dafree_core)
dafree_enable_warnings(_core)
if(MINGW)
  target_link_options(_core PRIVATE -static -static-libgcc -static-libstdc++)
endif()
install(TARGETS _core LIBRARY DESTINATION dafree RUNTIME DESTINATION dafree)

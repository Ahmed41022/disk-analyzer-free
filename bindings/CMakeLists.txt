nanobind_add_module(_core STABLE_ABI NB_STATIC LTO NB_SUPPRESS_WARNINGS
  src/module.cpp src/strings.cpp src/scan_bind.cpp src/tree_bind.cpp src/view_bind.cpp src/testing_bind.cpp)
target_compile_features(_core PRIVATE cxx_std_20)
target_link_libraries(_core PRIVATE dafree_core)
dafree_enable_warnings(_core)
if(MINGW)
  target_link_options(_core PRIVATE -static -static-libgcc -static-libstdc++)
endif()
install(TARGETS _core LIBRARY DESTINATION dafree RUNTIME DESTINATION dafree)

if(DAFREE_SANITIZE STREQUAL "")
  return()
endif()

string(REPLACE "," ";" _sanitizers "${DAFREE_SANITIZE}")
if(MSVC)
  message(FATAL_ERROR "DAFREE_SANITIZE is not supported by this MSVC configuration")
endif()

foreach(_sanitizer IN LISTS _sanitizers)
  if(NOT _sanitizer MATCHES "^(address|undefined|thread)$")
    message(FATAL_ERROR "Unsupported sanitizer: ${_sanitizer}")
  endif()
endforeach()

list(JOIN _sanitizers "," _sanitizer_list)
add_compile_options(-fsanitize=${_sanitizer_list} -fno-omit-frame-pointer)
add_link_options(-fsanitize=${_sanitizer_list})

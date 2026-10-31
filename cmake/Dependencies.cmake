include(FetchContent)

# Versions and permissive licenses are tracked here for reproducible builds.
# SHA256 values were calculated from the upstream release archives.
# dafree-dep: name=robin-map license=MIT url=https://github.com/Tessil/robin-map
FetchContent_Declare(
  robin_map
  URL https://github.com/Tessil/robin-map/archive/refs/tags/v1.3.0.tar.gz
  URL_HASH SHA256=a8424ad3b0affd4c57ed26f0f3d8a29604f0e1f2ef2089f497f614b1c94c7236
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=nanobind license=BSD-3-Clause url=https://github.com/wjakob/nanobind
FetchContent_Declare(
  nanobind
  URL https://github.com/wjakob/nanobind/archive/refs/tags/v3.1.0.tar.gz
  URL_HASH SHA256=39659890a112e84e7263e4a263c71dd2621f866f7a4386ce95ef410e6c0e5c2f
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=zstd license=BSD-3-Clause url=https://github.com/facebook/zstd
FetchContent_Declare(
  zstd
  URL https://github.com/facebook/zstd/archive/refs/tags/v1.5.7.tar.gz
  URL_HASH SHA256=37d7284556b20954e56e1ca85b80226768902e2edabd3b649e9e72c0c9012ee3
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=xxhash license=BSD-2-Clause url=https://github.com/Cyan4973/xxHash
FetchContent_Declare(
  xxhash
  URL https://github.com/Cyan4973/xxHash/archive/refs/tags/v0.8.3.tar.gz
  URL_HASH SHA256=aae608dfe8213dfd05d909a57718ef82f30722c392344583d3f39050c7f29a80
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=blake3 license=Apache-2.0 url=https://github.com/BLAKE3-team/BLAKE3
FetchContent_Declare(
  blake3
  URL https://github.com/BLAKE3-team/BLAKE3/archive/refs/tags/1.8.2.tar.gz
  URL_HASH SHA256=6b51aefe515969785da02e87befafc7fdc7a065cd3458cf1141f29267749e81f
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=pcre2 license=BSD-3-Clause url=https://github.com/PCRE2Project/pcre2
FetchContent_Declare(
  pcre2
  URL https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.46/pcre2-10.46.tar.gz
  URL_HASH SHA256=8d28d7f2c3b970c3a4bf3776bcbb5adfc923183ce74bc8df1ebaad8c1985bd07
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=doctest license=MIT url=https://github.com/doctest/doctest
FetchContent_Declare(
  doctest
  URL https://github.com/doctest/doctest/archive/refs/tags/v2.4.12.tar.gz
  URL_HASH SHA256=73381c7aa4dee704bd935609668cf41880ea7f19fa0504a200e13b74999c2d70
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
# dafree-dep: name=benchmark license=Apache-2.0 url=https://github.com/google/benchmark
FetchContent_Declare(
  benchmark
  URL https://github.com/google/benchmark/archive/refs/tags/v1.9.4.tar.gz
  URL_HASH SHA256=b334658edd35efcf06a99d9be21e4e93e092bd5f95074c1673d5c8705d95c104
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(NB_USE_SUBMODULE_DEPS OFF CACHE BOOL "Use separately pinned robin-map source" FORCE)
FetchContent_MakeAvailable(robin_map nanobind doctest)
# Keep project warnings strict while treating the pinned vendor headers as external.
set_property(TARGET robin_map PROPERTY SYSTEM ON)

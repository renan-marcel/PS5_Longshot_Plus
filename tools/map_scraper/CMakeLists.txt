cmake_minimum_required(VERSION 3.20)
project(lsms VERSION 0.1.0 LANGUAGES C CXX)

# lsms: the Longshot map scraper. A C++20 library (lsms), its C interface (in the library, and as a shared library with
# LSMS_SHARED), a command-line tool (lsms-scan) and its unit tests (lsms-tests).
#
#   cmake -S tools/map_scraper -B build/lsms -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/lsms
#   ctest --test-dir build/lsms
#
# zstd: the decoder in third_party/zstd (the repository's own, unmodified; LSMS_ZSTD=bundled), the system's libzstd
# (LSMS_ZSTD=system), or none (LSMS_ZSTD=off: .zs files answer Errc::unsupported, the rest works).

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(LSMS_ZSTD "bundled" CACHE STRING "zstd decoder: bundled (third_party/zstd), system, or off")
set_property(CACHE LSMS_ZSTD PROPERTY STRINGS bundled system off)
option(LSMS_SHARED "Also build the C interface as a shared library (lsms_c)" OFF)
option(LSMS_BUILD_CLI "Build lsms-scan" ON)
option(LSMS_BUILD_TESTS "Build lsms-tests" ON)
option(LSMS_SANITIZE "Build with AddressSanitizer and UBSan (GCC, Clang)" OFF)

if(LSMS_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

add_library(lsms STATIC
  src/zstd_stream.cpp
  src/sarc_reader.cpp
  src/byml_parser.cpp
  src/romfs_index.cpp
  src/json_writer.cpp
  src/map_scraper.cpp
  src/c_api.cpp)
target_include_directories(lsms PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
set_target_properties(lsms PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
  target_compile_options(lsms PRIVATE /W4 /utf-8)
else()
  target_compile_options(lsms PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(LSMS_ZSTD STREQUAL "bundled")
  set(LSMS_ZSTD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/zstd/lib" CACHE PATH "zstd's lib/ folder")
  file(GLOB LSMS_ZSTD_SOURCES ${LSMS_ZSTD_DIR}/common/*.c ${LSMS_ZSTD_DIR}/decompress/*.c)
  add_library(lsms_zstd STATIC ${LSMS_ZSTD_SOURCES})
  target_include_directories(lsms_zstd PUBLIC ${LSMS_ZSTD_DIR})
  # (the decoder only, in C, as the repository builds it: nx2/build.py)
  target_compile_definitions(lsms_zstd PRIVATE ZSTD_DISABLE_ASM)
  set_target_properties(lsms_zstd PROPERTIES POSITION_INDEPENDENT_CODE ON)
  target_link_libraries(lsms PRIVATE lsms_zstd)
  target_compile_definitions(lsms PRIVATE LSMS_WITH_ZSTD=1)
elseif(LSMS_ZSTD STREQUAL "system")
  find_path(LSMS_ZSTD_INCLUDE zstd.h REQUIRED)
  find_library(LSMS_ZSTD_LIBRARY NAMES zstd libzstd REQUIRED)
  target_include_directories(lsms PRIVATE ${LSMS_ZSTD_INCLUDE})
  target_link_libraries(lsms PRIVATE ${LSMS_ZSTD_LIBRARY})
  target_compile_definitions(lsms PRIVATE LSMS_WITH_ZSTD=1)
else()
  target_compile_definitions(lsms PRIVATE LSMS_WITH_ZSTD=0)
endif()

if(LSMS_SHARED)
  add_library(lsms_c SHARED src/c_api.cpp)
  target_link_libraries(lsms_c PRIVATE lsms)
  target_compile_definitions(lsms_c PRIVATE LSMS_SHARED=1 PUBLIC LSMS_SHARED=1)
  set_target_properties(lsms_c PROPERTIES CXX_VISIBILITY_PRESET hidden)
endif()

if(LSMS_BUILD_CLI)
  add_executable(lsms-scan cli/main.cpp)
  target_link_libraries(lsms-scan PRIVATE lsms)
  if(WIN32)
    target_link_libraries(lsms-scan PRIVATE shell32)
  endif()
endif()

if(LSMS_BUILD_TESTS)
  enable_testing()
  add_executable(lsms-tests tests/test_main.cpp)
  target_link_libraries(lsms-tests PRIVATE lsms)
  add_test(NAME lsms-tests COMMAND lsms-tests)
endif()

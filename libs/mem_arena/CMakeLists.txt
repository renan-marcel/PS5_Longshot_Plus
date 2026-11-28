if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    cmake_minimum_required(VERSION 3.16)
    project(mem_arena LANGUAGES CXX)
endif()

find_package(Threads REQUIRED)

if(CMAKE_SYSTEM_NAME STREQUAL "Prospero" OR PS5 OR PROSPERO)
    set(MEM_ARENA_OS_SRC src/os_mem_ps5.cpp)
else()
    set(MEM_ARENA_OS_SRC src/os_mem_posix.cpp)
endif()

add_library(mem_arena STATIC "${MEM_ARENA_OS_SRC}")
target_compile_features(mem_arena PUBLIC cxx_std_20)
target_include_directories(mem_arena PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(mem_arena PRIVATE Threads::Threads)

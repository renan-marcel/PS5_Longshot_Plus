if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    cmake_minimum_required(VERSION 3.16)
    project(mem_arena LANGUAGES CXX)
endif()

find_package(Threads REQUIRED)

add_library(mem_arena STATIC src/os_mem_posix.cpp)
target_compile_features(mem_arena PUBLIC cxx_std_20)
target_include_directories(mem_arena PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(mem_arena PRIVATE Threads::Threads)

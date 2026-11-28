cmake_minimum_required(VERSION 3.16)
project(Longshot LANGUAGES NONE)

# The game builds through its existing scripts. CMake builds standalone libraries.
if(UNIX)
    enable_language(CXX)
    include(CTest)
    add_subdirectory(libs/mem_arena)
    if(BUILD_TESTING AND NOT CMAKE_CROSSCOMPILING)
        add_executable(scratch_arena_test libs/mem_arena/tests/scratch_arena_test.cpp)
        target_link_libraries(scratch_arena_test PRIVATE mem_arena)
        add_test(NAME scratch_arena_test COMMAND scratch_arena_test)
    endif()
endif()

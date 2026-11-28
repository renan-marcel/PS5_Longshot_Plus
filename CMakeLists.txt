cmake_minimum_required(VERSION 3.16)
project(Longshot LANGUAGES NONE)

# The game builds through its existing scripts. CMake builds standalone libraries.
if(UNIX)
    enable_language(CXX)
    include(CTest)
    add_subdirectory(libs/mem_arena)
endif()

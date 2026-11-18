cmake_minimum_required(VERSION 3.22)
project(ChoanoWindowsCodecs C CXX)

include("${KRYON_DIR}/cmake/AVIF.cmake")
kryon_avif_decoder("${AVIF_DIR}" "${AOM_DIR}")

# The locked AVIF recipe exposes the static objects on Windows. Package the
# same decoder API as a DLL for the Cairo renderer's runtime loader.
target_compile_definitions(avif_obj PRIVATE AVIF_DLL AVIF_BUILDING_SHARED_LIBS)
add_library(kryonavif SHARED $<TARGET_OBJECTS:avif_obj>)
target_link_libraries(kryonavif PRIVATE aom dav1d::dav1d Threads::Threads)
set_target_properties(kryonavif PROPERTIES PREFIX "")

#include "dafree/analysis.hpp"

namespace dafree {
namespace {

constexpr std::string_view kImages =
    "3fr arw avif bmp dib cr2 cr3 crw dcr dng emf erf exr gif heic heif ico jfif jif jp2 j2k "
    "jpf jpx jpm jpg jpeg jpe k25 kdc mef mos mrw nef nrw orf pef png psd psp raf rw2 rwl "
    "sr2 srf svg tif tiff webp wmf x3f";
constexpr std::string_view kVideos =
    "3g2 3gp amv asf avi bik braw cavs divx drc dv f4v flv h264 h265 hevc m2ts m2v m4v mkv "
    "mov mp2 mp4 mpe mpeg mpg mpeg2 mpeg4 mxf nsv nut ogv qt rm rmvb roq rtp swf ts vob "
    "webm wmv yuv";
constexpr std::string_view kAudio =
    "aac ac3 aif aiff alac amr ape au awb caf dss flac gsm iklax ivs m4a m4b m4p mid midi "
    "mka mp3 mpc oga ogg opus ra ram rf64 sln tta voc vox wav wma wv";
constexpr std::string_view kArchives =
    "7z ace alz arc arj bh bz bz2 cab cfs cpio ear gca gz jar lha lzh lz "
    "lz4 lzma lzo lzx pak rar sda sea sit sitx sqx tar tgz tlz txz war xz z zip zst";
constexpr std::string_view kDocuments =
    "abw azw azw3 bib doc docm docx dot dotm dotx epub fb2 fodt md odf odm odp ods odt "
    "pages pmd ppt pptm pptx ps rtf sdc sdd sdw tex txt wpd wps xls xlsb xlsm xlsx xltx "
    "csv tsv pdf djvu mobi numbers key";
constexpr std::string_view kCode =
    "asm bash c cc cpp cxx h hh hpp hxx cs css cjs dart diff el go hs html htm ini "
    "java js jsx json jsonc kt kts lua m makefile mjs mm pas php pl py pyc pyi rb rs "
    "scala sc ss sql swift tcl tsx vb xml xsd xsl yaml yml toml sh zsh gradle cmake "
    "dockerfile gitignore editorconfig vue svelte graphql gql proto r rst ipynb rmd wasm";
constexpr std::string_view kExecutables =
    "app bat cmd com dll exe msi msix scr cpl ocx bin elf appimage "
    "ps1 vbs reg lnk";
constexpr std::string_view kDiskImages =
    "adf aff4 chd cue dmg dsk fdi g64 img iso mdf mds nrg qcow qcow2 vdi vhd vhdx vmdk wim xva";
constexpr std::string_view kSystemExtensions =
    "bak cache cfg conf dat db db3 dump err log old orig pid sav swp tmp temp torrent lock "
    "manifest meta package plist service socket winmd cat drv inf sys pch pdb obj lib "
    "class pyo so dylib";

constexpr bool equal_ascii_fold(std::string_view left, std::string_view right) noexcept {
    if (left.size() != right.size())
        return false;
    for (std::size_t index = 0; index < left.size(); ++index) {
        auto a = left[index];
        auto b = right[index];
        if (a >= 'A' && a <= 'Z')
            a = static_cast<char>(a + ('a' - 'A'));
        if (b >= 'A' && b <= 'Z')
            b = static_cast<char>(b + ('a' - 'A'));
        if (a != b)
            return false;
    }
    return true;
}

constexpr bool contains(std::string_view extensions, std::string_view ext) noexcept {
    std::size_t start = 0;
    while (start < extensions.size()) {
        while (start < extensions.size() && extensions[start] == ' ')
            ++start;
        auto end = start;
        while (end < extensions.size() && extensions[end] != ' ')
            ++end;
        if (equal_ascii_fold(extensions.substr(start, end - start), ext))
            return true;
        start = end + 1;
    }
    return false;
}

} // namespace

ExtCategory classify_extension(std::string_view ext) noexcept {
    if (contains(kImages, ext))
        return ExtCategory::Image;
    if (contains(kVideos, ext))
        return ExtCategory::Video;
    if (contains(kAudio, ext))
        return ExtCategory::Audio;
    if (contains(kArchives, ext))
        return ExtCategory::Archive;
    if (contains(kDocuments, ext))
        return ExtCategory::Document;
    if (contains(kCode, ext))
        return ExtCategory::Code;
    if (contains(kExecutables, ext))
        return ExtCategory::Executable;
    if (contains(kDiskImages, ext))
        return ExtCategory::DiskImage;
    if (contains(kSystemExtensions, ext))
        return ExtCategory::System;
    return ExtCategory::Other;
}

} // namespace dafree

#pragma once

// Parser for the panel-written native_god_state.txt (v1.2.0).
//
// v1.1.2 read the file with _wfopen_s(L"r") (CRT text mode) and an fgets loop
// over a 256-byte buffer. v1.2.0 reads it through sbcore::status::StableReader
// (FILE_SHARE_READ|WRITE|DELETE, so the panel's POSIX-rename replace is never
// blocked; plan A12) and parses the bytes here with exactly the old semantics:
//
//   * text mode: "\r\n" becomes "\n" and a Ctrl-Z (0x1A) ends the input;
//   * fgets(line, 256): a "line" is at most 255 characters and ends after '\n';
//   * godlive=     parse_bool (leading blanks skipped; "1", "true", "on" prefix)
//   * playerguid=  strtoul base 10
//   * actorptr=    hex (optional 0x), strtoull base 16
//   * bagptr=      hex (optional 0x), strtoull base 16
//   * a missing godlive= keeps the previous desired state; the other values
//     default to 0.
//
// Pure function: no I/O, no globals. tools/state_parse_test.cpp compares it
// with the verbatim v1.1.2 fgets loop on randomized inputs.

#include <cstdint>
#include <string_view>

namespace sbgod::state
{
    struct DesiredState
    {
        bool god = false;
        std::uint32_t player_guid = 0;
        std::uint64_t actor_ptr = 0;
        std::uint64_t bag_ptr = 0;
    };

    DesiredState parse_state_text(std::string_view raw, bool previous_god);
} // namespace sbgod::state

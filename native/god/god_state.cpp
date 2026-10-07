#include "god_state.hpp"

#include <cstdlib>
#include <cstring>
#include <string>

namespace sbgod::state
{
    namespace
    {
        // Verbatim v1.1.2 value parsers (god_hook.cpp).
        bool parse_bool(const char* v)
        {
            if (!v) return false;
            while (*v == ' ' || *v == '\t' || *v == '\r' || *v == '\n') ++v;
            return std::strncmp(v, "1", 1) == 0 || _strnicmp(v, "true", 4) == 0 || _strnicmp(v, "on", 2) == 0;
        }

        std::uint64_t parse_hex_u64(const char* v)
        {
            if (!v) return 0;
            while (*v == ' ' || *v == '\t') ++v;
            if (v[0] == '0' && (v[1] == 'x' || v[1] == 'X')) v += 2;
            return std::strtoull(v, nullptr, 16);
        }

        // CRT text-mode read: CR LF -> LF, Ctrl-Z ends the input.
        std::string text_mode(std::string_view raw)
        {
            std::string text;
            text.reserve(raw.size());
            for (std::size_t i = 0; i < raw.size(); ++i)
            {
                const char c = raw[i];
                if (c == '\x1A') break;
                if (c == '\r' && i + 1 < raw.size() && raw[i + 1] == '\n') continue;
                text.push_back(c);
            }
            return text;
        }
    } // namespace

    DesiredState parse_state_text(std::string_view raw, bool previous_god)
    {
        DesiredState out{};
        out.god = previous_god;
        const std::string text = text_mode(raw);
        constexpr std::size_t kLineBuffer = 256; // fgets(line, sizeof(line) == 256, f)
        std::size_t pos = 0;
        std::string line;
        while (pos < text.size())
        {
            std::size_t end = pos;
            const std::size_t limit = (text.size() - pos < kLineBuffer - 1) ? text.size() : pos + kLineBuffer - 1;
            while (end < limit)
            {
                if (text[end++] == '\n') break;
            }
            line.assign(text, pos, end - pos);
            pos = end;
            const char* l = line.c_str();
            if (std::strncmp(l, "godlive=", 8) == 0) out.god = parse_bool(l + 8);
            else if (std::strncmp(l, "playerguid=", 11) == 0)
                out.player_guid = static_cast<std::uint32_t>(std::strtoul(l + 11, nullptr, 10));
            else if (std::strncmp(l, "actorptr=", 9) == 0) out.actor_ptr = parse_hex_u64(l + 9);
            else if (std::strncmp(l, "bagptr=", 7) == 0) out.bag_ptr = parse_hex_u64(l + 7);
        }
        return out;
    }
} // namespace sbgod::state

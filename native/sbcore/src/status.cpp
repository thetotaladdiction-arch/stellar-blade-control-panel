#include "sbcore/status.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

#include <windows.h>

#include "sbcore/version.hpp"

namespace sbcore::status
{
    namespace
    {
#if defined(SBCORE_TESTING)
        std::size_t g_fail_after = static_cast<std::size_t>(-1);
#endif

        bool valid_key(const char* key)
        {
            if (!key || !key[0]) return false;
            for (const char* p = key; *p; ++p)
            {
                const char c = *p;
                const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
                if (!ok) return false;
            }
            return true;
        }

        bool plain_single_link(HANDLE file)
        {
            BY_HANDLE_FILE_INFORMATION information{};
            return GetFileInformationByHandle(file, &information)
                && (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0
                && information.nNumberOfLinks == 1;
        }

        // For readers: 0 links means the file was replaced (POSIX rename) after
        // this handle opened it; the handle still reads that complete previous
        // version. More than one link is a hard link and is refused.
        bool plain_readable(HANDLE file)
        {
            BY_HANDLE_FILE_INFORMATION information{};
            return GetFileInformationByHandle(file, &information)
                && (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) == 0
                && information.nNumberOfLinks <= 1;
        }

        std::wstring full_path(const std::wstring& path)
        {
            const DWORD needed = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
            if (needed == 0) return {};
            std::wstring out(needed, L'\0');
            const DWORD length = GetFullPathNameW(path.c_str(), needed, out.data(), nullptr);
            if (length == 0 || length >= needed) return {};
            out.resize(length);
            return out;
        }

        bool unsupported_rename_error(DWORD error)
        {
            return error == ERROR_INVALID_PARAMETER || error == ERROR_NOT_SUPPORTED || error == ERROR_INVALID_FUNCTION;
        }

        bool transient_rename_error(DWORD error)
        {
            // A third-party handle without FILE_SHARE_DELETE (an AV scan, the
            // indexer, a legacy reader) briefly open on the target.
            return error == ERROR_ACCESS_DENIED || error == ERROR_SHARING_VIOLATION;
        }

        // Bounded retry: attempt, Sleep(0), Sleep(1), Sleep(1). Only on a
        // transient error; worst case a few ms on the worker thread.
        bool rename_with_retry(HANDLE file, std::wstring_view target, unsigned attempts, unsigned& retries, DWORD& error)
        {
            retries = 0;
            error = ERROR_SUCCESS;
            for (unsigned attempt = 0; attempt < attempts; ++attempt)
            {
                if (attempt > 0)
                {
                    ++retries;
                    Sleep(attempt == 1 ? 0 : 1);
                }
                if (rename_handle_posix(file, target)) return true;
                error = GetLastError();
                if (!transient_rename_error(error)) return false;
            }
            return false;
        }
    }

    bool is_absolute_path(std::wstring_view path)
    {
        const bool drive = path.size() >= 3 && ((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z'))
            && path[1] == L':' && (path[2] == L'\\' || path[2] == L'/');
        const bool unc = path.size() >= 3 && path[0] == L'\\' && path[1] == L'\\';
        return drive || unc;
    }

    bool rename_handle_posix(void* file, std::wstring_view absolute_target)
    {
        // KernelBase converts FILE_RENAME_INFO.FileName as a DOS path: a bare
        // name would resolve against the process's current directory, so only
        // an absolute path is accepted.
        if (!file || file == INVALID_HANDLE_VALUE || !is_absolute_path(absolute_target))
        {
            SetLastError(ERROR_INVALID_PARAMETER);
            return false;
        }
        const std::size_t bytes = sizeof(FILE_RENAME_INFO) + absolute_target.size() * sizeof(wchar_t);
        std::vector<std::uint64_t> storage((bytes + 7) / 8, 0); // 8-byte aligned (HANDLE member)
        auto* info = reinterpret_cast<FILE_RENAME_INFO*>(storage.data());
        info->Flags = FILE_RENAME_FLAG_REPLACE_IF_EXISTS | FILE_RENAME_FLAG_POSIX_SEMANTICS;
        info->RootDirectory = nullptr;
        info->FileNameLength = static_cast<DWORD>(absolute_target.size() * sizeof(wchar_t));
        std::memcpy(info->FileName, absolute_target.data(), absolute_target.size() * sizeof(wchar_t));
        return SetFileInformationByHandle(static_cast<HANDLE>(file), FileRenameInfoEx, info, static_cast<DWORD>(bytes)) != FALSE;
    }

    bool replace_file_posix(const std::wstring& source, const std::wstring& target, unsigned attempts, unsigned* retries_used,
                            unsigned long* error_out)
    {
        unsigned retries = 0;
        DWORD error = ERROR_SUCCESS;
        bool ok = false;
        const HANDLE file = CreateFileW(source.c_str(), DELETE | SYNCHRONIZE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (file == INVALID_HANDLE_VALUE)
        {
            error = GetLastError();
        }
        else
        {
            ok = rename_with_retry(file, target, attempts == 0 ? 1 : attempts, retries, error);
            CloseHandle(file);
        }
        if (retries_used) *retries_used = retries;
        if (error_out) *error_out = ok ? 0 : error;
        return ok;
    }

    std::uint64_t fnv1a64(std::string_view data)
    {
        std::uint64_t hash = 0xCBF29CE484222325ULL;
        for (const char c : data)
        {
            hash ^= static_cast<std::uint8_t>(c);
            hash *= 0x100000001B3ULL;
        }
        return hash;
    }

    // ---- Builder -------------------------------------------------------------

    Builder::Builder(char* buffer, std::size_t capacity) : buffer_(buffer), capacity_(buffer ? capacity : 0)
    {
        if (!buffer_ || capacity_ < 4) error_ = "no_buffer";
    }

    void Builder::clear()
    {
        length_ = 0;
        key_count_ = 0;
        error_ = (!buffer_ || capacity_ < 4) ? "no_buffer" : nullptr;
    }

    void Builder::fail(const char* reason)
    {
        if (!error_) error_ = reason;
    }

    void Builder::append(std::string_view text)
    {
        if (error_) return;
        if (text.size() > capacity_ - length_)
        {
            fail("overflow");
            return;
        }
        std::memcpy(buffer_ + length_, text.data(), text.size());
        length_ += text.size();
    }

    bool Builder::begin_line(const char* key)
    {
        if (error_) return false;
        if (!valid_key(key))
        {
            fail("invalid_key");
            return false;
        }
        const std::string_view name(key);
        // Duplicate detection (64-bit FNV-1a of the key; a collision can only
        // cause a false rejection, never a duplicate): the panel's strict parser rejects a
        // repeated key, so a builder with one never publishes.
        const std::uint64_t hash = fnv1a64(name);
        for (std::size_t i = 0; i < key_count_; ++i)
        {
            if (key_hashes_[i] == hash)
            {
                fail("duplicate_key");
                return false;
            }
        }
        if (key_count_ >= kMaxKeys)
        {
            fail("too_many_keys");
            return false;
        }
        key_hashes_[key_count_++] = hash;
        append(name);
        append("=");
        return !error_;
    }

    void Builder::end_line()
    {
        append("\r\n");
    }

    void Builder::add_u64(const char* key, std::uint64_t value)
    {
        if (!begin_line(key)) return;
        char text[32];
        const int n = std::snprintf(text, sizeof(text), "%llu", static_cast<unsigned long long>(value));
        append(std::string_view(text, n > 0 ? static_cast<std::size_t>(n) : 0));
        end_line();
    }

    void Builder::add_i64(const char* key, std::int64_t value)
    {
        if (!begin_line(key)) return;
        char text[32];
        const int n = std::snprintf(text, sizeof(text), "%lld", static_cast<long long>(value));
        append(std::string_view(text, n > 0 ? static_cast<std::size_t>(n) : 0));
        end_line();
    }

    void Builder::add_bool(const char* key, bool value)
    {
        if (!begin_line(key)) return;
        append(value ? "1" : "0");
        end_line();
    }

    void Builder::add_hex32(const char* key, std::uint32_t value)
    {
        if (!begin_line(key)) return;
        char text[16];
        const int n = std::snprintf(text, sizeof(text), "0x%08X", value);
        append(std::string_view(text, n > 0 ? static_cast<std::size_t>(n) : 0));
        end_line();
    }

    void Builder::add_hex64(const char* key, std::uint64_t value)
    {
        if (!begin_line(key)) return;
        char text[24];
        const int n = std::snprintf(text, sizeof(text), "0x%016llX", static_cast<unsigned long long>(value));
        append(std::string_view(text, n > 0 ? static_cast<std::size_t>(n) : 0));
        end_line();
    }

    void Builder::add_float(const char* key, double value, int precision)
    {
        if (!begin_line(key)) return;
        if (precision < 0 || precision > 9)
        {
            fail("invalid_precision");
            return;
        }
        // Same text as the natives' fprintf("%.Nf"), NaN/inf included.
        char text[400];
        const int n = std::snprintf(text, sizeof(text), "%.*f", precision, value);
        if (n <= 0 || static_cast<std::size_t>(n) >= sizeof(text))
        {
            fail("float_format");
            return;
        }
        append(std::string_view(text, static_cast<std::size_t>(n)));
        end_line();
    }

    void Builder::add_str(const char* key, std::string_view value)
    {
        if (!begin_line(key)) return;
        if (value.empty())
        {
            fail("empty_value");
            return;
        }
        for (const char c : value)
        {
            if (c < 0x20 || c > 0x7E)
            {
                fail("non_printable_value");
                return;
            }
        }
        append(value);
        end_line();
    }

    // ---- Writer --------------------------------------------------------------

    bool Writer::configure(std::wstring final_path, std::wstring temp_path)
    {
        if (final_path.empty()) return false;
        if (temp_path.empty()) temp_path = final_path + L".tmp";
        // Absolute paths only: the rename by handle resolves a relative name
        // against the process's current directory.
        std::wstring final_full = full_path(final_path);
        std::wstring temp_full = full_path(temp_path);
        if (final_full.empty() || temp_full.empty() || temp_full == final_full) return false;
        final_path_ = std::move(final_full);
        temp_path_ = std::move(temp_full);
        return true;
    }

    PublishResult Writer::publish(std::string_view body, bool flush)
    {
        auto failed = [this](PublishResult result, bool rename) {
            counters_.last_error = GetLastError();
            if (rename) ++counters_.rename_failures;
            else ++counters_.write_failures;
            counters_.last_result = result;
            return result;
        };
        if (!configured())
        {
            counters_.last_result = PublishResult::NotConfigured;
            return PublishResult::NotConfigured;
        }
        if (body.empty() || body.size() > std::numeric_limits<DWORD>::max())
        {
            return failed(PublishResult::InvalidBody, false);
        }
        const DWORD existing = GetFileAttributesW(temp_path_.c_str());
        if (existing != INVALID_FILE_ATTRIBUTES)
        {
            if ((existing & FILE_ATTRIBUTE_DIRECTORY) != 0 || !DeleteFileW(temp_path_.c_str()))
            {
                return failed(PublishResult::TempBlocked, false);
            }
        }
        // Share READ|DELETE: the handle is renamed onto the final name before
        // it is closed, and readers must be able to open the final name then
        // (share 0 made them fail with ERROR_SHARING_VIOLATION - measured).
        // Nobody can write through the temp name meanwhile (no FILE_SHARE_WRITE).
        const HANDLE file = CreateFileW(temp_path_.c_str(), GENERIC_WRITE | DELETE, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                                        CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) return failed(PublishResult::CreateFailed, false);
        if (!plain_single_link(file))
        {
            CloseHandle(file);
            DeleteFileW(temp_path_.c_str());
            return failed(PublishResult::NotPlainFile, false);
        }
        std::size_t to_write = body.size();
#if defined(SBCORE_TESTING)
        const bool simulate_short = g_fail_after != static_cast<std::size_t>(-1);
        if (simulate_short)
        {
            to_write = g_fail_after < to_write ? g_fail_after : to_write;
            g_fail_after = static_cast<std::size_t>(-1);
        }
#endif
        DWORD written = 0;
        bool write_ok = to_write == 0 || (WriteFile(file, body.data(), static_cast<DWORD>(to_write), &written, nullptr) != FALSE);
        write_ok = write_ok && written == body.size();
#if defined(SBCORE_TESTING)
        if (simulate_short) SetLastError(ERROR_HANDLE_DISK_FULL);
#endif
        const DWORD write_error = GetLastError();
        const bool flush_ok = !write_ok || !flush || FlushFileBuffers(file) != FALSE;
        if (!write_ok || !flush_ok)
        {
            CloseHandle(file);
            DeleteFileW(temp_path_.c_str());
            SetLastError(write_error);
            return failed(!write_ok ? PublishResult::WriteFailed : PublishResult::FlushFailed, false);
        }
        // Rename the very handle that was written, with POSIX semantics: the
        // replace succeeds even while readers that share DELETE (sbcore's
        // read_small_file) hold the old file. Plain MoveFileExW - what
        // Python's os.replace() uses - fails with ERROR_ACCESS_DENIED whenever
        // the target is open at all (measured, see README).
        unsigned retries = 0;
        DWORD rename_error = ERROR_SUCCESS;
        bool renamed = rename_with_retry(file, final_path_, kRenameAttempts, retries, rename_error);
        counters_.rename_retries += retries;
        if (renamed && flush) FlushFileBuffers(file);
        const bool close_ok = CloseHandle(file) != FALSE;
        if (!renamed && unsupported_rename_error(rename_error))
        {
            // File systems / builds without FileRenameInfoEx: classic rename.
            const DWORD flags = MOVEFILE_REPLACE_EXISTING | (flush ? MOVEFILE_WRITE_THROUGH : 0);
            renamed = close_ok && MoveFileExW(temp_path_.c_str(), final_path_.c_str(), flags) != FALSE;
            rename_error = renamed ? ERROR_SUCCESS : GetLastError();
            if (renamed) ++counters_.fallback_renames;
        }
        if (!renamed)
        {
            DeleteFileW(temp_path_.c_str());
            SetLastError(rename_error);
            return failed(PublishResult::RenameFailed, true);
        }
        if (!close_ok) return failed(PublishResult::CloseFailed, false);
        ++counters_.publishes;
        counters_.last_result = PublishResult::Published;
        return PublishResult::Published;
    }

    // ---- Publisher -----------------------------------------------------------

    bool Publisher::configure(const Options& options, std::wstring final_path, std::wstring temp_path)
    {
        auto ascii_ok = [](const char* text) {
            if (!text || !text[0]) return false;
            for (const char* p = text; *p; ++p)
            {
                if (*p < 0x21 || *p > 0x7E) return false;
            }
            return true;
        };
        if (!ascii_ok(options.module) || !ascii_ok(options.module_version) || options.beat_ms == 0) return false;
        if (!writer_.configure(std::move(final_path), std::move(temp_path))) return false;
        module_ = options.module;
        module_version_ = options.module_version;
        beat_ms_ = options.beat_ms;
        min_interval_ms_ = options.min_interval_ms;
        return true;
    }

    PublishResult Publisher::maybe_publish(const Builder& body, std::uint64_t now_ms, bool force)
    {
        if (!writer_.configured()) return PublishResult::NotConfigured;
        if (!body.ok() || body.view().empty()) return PublishResult::InvalidBody;
        const std::uint64_t hash = fnv1a64(body.view());
        const std::uint64_t since = published_once_ && now_ms >= last_publish_ms_ ? now_ms - last_publish_ms_ : UINT64_MAX;
        const bool beat_due = !published_once_ || since >= beat_ms_;
        const bool changed = !published_once_ || hash != last_hash_;
        if (!force && !beat_due && !(changed && since >= min_interval_ms_))
        {
            ++skipped_;
            return PublishResult::Skipped;
        }
        const std::uint64_t sequence = sequence_ + 1;
        char header[512];
        const auto& counters = writer_.counters();
        const int n = std::snprintf(header, sizeof(header),
                                    "sbcore_protocol=%u\r\nsbcore_version=%s\r\nsbcore_module=%s\r\n"
                                    "sbcore_module_version=%s\r\nsbcore_pid=%lu\r\nsbcore_seq=%llu\r\n"
                                    "sbcore_write_failures=%llu\r\nsbcore_rename_failures=%llu\r\n",
                                    kStatusProtocol, kVersion, module_.c_str(), module_version_.c_str(),
                                    GetCurrentProcessId(), static_cast<unsigned long long>(sequence),
                                    static_cast<unsigned long long>(counters.write_failures),
                                    static_cast<unsigned long long>(counters.rename_failures));
        if (n <= 0 || static_cast<std::size_t>(n) >= sizeof(header)) return PublishResult::InvalidBody;
        scratch_.assign(header, static_cast<std::size_t>(n));
        scratch_.append(body.view());
        const auto result = writer_.publish(scratch_);
        if (result == PublishResult::Published)
        {
            sequence_ = sequence;
            last_hash_ = hash;
            last_publish_ms_ = now_ms;
            published_once_ = true;
        }
        return result;
    }

    // ---- Reader --------------------------------------------------------------

    ReadResult read_small_file(const std::wstring& path, std::string& output, std::size_t max_bytes)
    {
        output.clear();
        HANDLE file = INVALID_HANDLE_VALUE;
        DWORD open_error = ERROR_SUCCESS;
        for (int attempt = 0; attempt < 3; ++attempt)
        {
            if (attempt > 0) Sleep(attempt == 1 ? 0 : 1);
            file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                               OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            if (file != INVALID_HANDLE_VALUE) break;
            open_error = GetLastError();
            const bool transient = open_error == ERROR_SHARING_VIOLATION || open_error == ERROR_ACCESS_DENIED
                || open_error == ERROR_LOCK_VIOLATION || open_error == 303 /* ERROR_DELETE_PENDING */;
            if (!transient) break;
        }
        if (file == INVALID_HANDLE_VALUE)
        {
            if (open_error == ERROR_FILE_NOT_FOUND || open_error == ERROR_PATH_NOT_FOUND) return ReadResult::Missing;
            if (open_error == ERROR_SHARING_VIOLATION || open_error == ERROR_ACCESS_DENIED || open_error == ERROR_LOCK_VIOLATION
                || open_error == 303)
            {
                return ReadResult::Busy;
            }
            return ReadResult::ReadFailed;
        }
        if (!plain_readable(file))
        {
            CloseHandle(file);
            return ReadResult::NotPlain;
        }
        LARGE_INTEGER size{};
        if (!GetFileSizeEx(file, &size))
        {
            CloseHandle(file);
            return ReadResult::ReadFailed;
        }
        if (size.QuadPart <= 0)
        {
            CloseHandle(file);
            return ReadResult::Empty;
        }
        if (static_cast<std::uint64_t>(size.QuadPart) > max_bytes || size.QuadPart > 0x7FFFFFFF)
        {
            CloseHandle(file);
            return ReadResult::TooLarge;
        }
        output.resize(static_cast<std::size_t>(size.QuadPart));
        std::size_t done = 0;
        bool ok = true;
        while (done < output.size())
        {
            DWORD read = 0;
            if (!ReadFile(file, output.data() + done, static_cast<DWORD>(output.size() - done), &read, nullptr) || read == 0)
            {
                ok = false;
                break;
            }
            done += read;
        }
        CloseHandle(file);
        if (!ok)
        {
            output.clear();
            return ReadResult::ReadFailed;
        }
        if (output.find('\0') != std::string::npos)
        {
            output.clear();
            return ReadResult::ContainsNul;
        }
        return ReadResult::Ok;
    }

    // ---- StableReader ----------------------------------------------------------

    bool StableReader::configure(std::wstring path, const Options& options)
    {
        if (path.empty() || options.max_bytes == 0) return false;
        path_ = std::move(path);
        options_ = options;
        content_.clear();
        have_content_ = false;
        failing_ = false;
        return true;
    }

    bool StableReader::configure(std::wstring path)
    {
        return configure(std::move(path), Options{});
    }

    StableReader::Read StableReader::read(std::uint64_t now_ms)
    {
        Read result;
        std::string fresh;
        result.raw = path_.empty() ? ReadResult::Missing : read_small_file(path_, fresh, options_.max_bytes);
        if (result.raw == ReadResult::Ok)
        {
            content_ = std::move(fresh);
            have_content_ = true;
            failing_ = false;
            result.effective = ReadResult::Ok;
            return result;
        }
        const bool transient = result.raw == ReadResult::Missing || result.raw == ReadResult::Busy;
        if (!transient)
        {
            // Hard failure: fail closed at once.
            content_.clear();
            have_content_ = false;
            failing_ = false;
            result.effective = result.raw;
            return result;
        }
        if (!failing_)
        {
            failing_ = true;
            first_failure_ms_ = now_ms;
        }
        const std::uint64_t failing_for = now_ms >= first_failure_ms_ ? now_ms - first_failure_ms_ : 0;
        if (have_content_ && failing_for < options_.grace_ms)
        {
            ++grace_hits_;
            result.effective = ReadResult::Ok;
            result.from_cache = true;
            return result;
        }
        content_.clear();
        have_content_ = false;
        result.effective = result.raw;
        return result;
    }

    const char* publish_result_name(PublishResult result)
    {
        switch (result)
        {
        case PublishResult::Published: return "published";
        case PublishResult::NotConfigured: return "not_configured";
        case PublishResult::InvalidBody: return "invalid_body";
        case PublishResult::TempBlocked: return "temp_blocked";
        case PublishResult::CreateFailed: return "create_failed";
        case PublishResult::NotPlainFile: return "not_plain_file";
        case PublishResult::WriteFailed: return "write_failed";
        case PublishResult::FlushFailed: return "flush_failed";
        case PublishResult::CloseFailed: return "close_failed";
        case PublishResult::RenameFailed: return "rename_failed";
        case PublishResult::Skipped: return "skipped";
        }
        return "unknown";
    }

    const char* read_result_name(ReadResult result)
    {
        switch (result)
        {
        case ReadResult::Ok: return "ok";
        case ReadResult::Missing: return "missing";
        case ReadResult::NotPlain: return "not_plain";
        case ReadResult::Empty: return "empty";
        case ReadResult::TooLarge: return "too_large";
        case ReadResult::ReadFailed: return "read_failed";
        case ReadResult::ContainsNul: return "contains_nul";
        case ReadResult::Busy: return "busy";
        }
        return "unknown";
    }

#if defined(SBCORE_TESTING)
    namespace testing
    {
        void fail_next_write_after(std::size_t bytes)
        {
            g_fail_after = bytes;
        }
    }
#endif
}

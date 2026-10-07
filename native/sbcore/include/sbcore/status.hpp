#pragma once

// Status-file IPC (A12).
//
// Writing: Builder formats key=value lines (ASCII, CRLF, unique keys,
// non-empty values: the panel's strict heartbeat parser rejects anything
// else). Writer replaces a file atomically: delete a stale temp, CREATE_NEW
// the temp, check the write, then rename THAT handle over the final name with
// POSIX semantics (FileRenameInfoEx, REPLACE_IF_EXISTS | POSIX_SEMANTICS), so
// the replace succeeds even while readers that share DELETE hold the old
// file; MoveFileExW(REPLACE_EXISTING) is the fallback where FileRenameInfoEx
// is unsupported. A failed write never replaces the previous good file. No
// fsync by default (the rename is what makes the update atomic for readers).
// Publisher adds the common header and writes on change plus a liveness beat.
//
// Reading: read_small_file opens with FILE_SHARE_READ|WRITE|DELETE and refuses
// reparse points, hard-linked files, directories, empty, oversized and
// NUL-containing files. Sharing DELETE is necessary but NOT sufficient for the
                                                                               
                                                                          
// (88-95% of replaces under a continuously polling reader); a POSIX-semantics
// rename (replace_file_posix below) never did. Readers that hold the file
// without FILE_SHARE_DELETE block even the POSIX rename (ERROR_SHARING_VIOLATION).
//
// Header (prepended by Publisher; every key is new, existing panel fields are
// untouched):
//   sbcore_protocol=1  sbcore_version=<sbcore>  sbcore_module=<native>
//   sbcore_module_version=<ver>  sbcore_pid=<pid>  sbcore_seq=<n>
//   sbcore_write_failures=<n>  sbcore_rename_failures=<n>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace sbcore::status
{
    class Builder
    {
      public:
        static constexpr std::size_t kMaxKeys = 256;

        Builder(char* buffer, std::size_t capacity);

        void add_u64(const char* key, std::uint64_t value);
        void add_i64(const char* key, std::int64_t value);
        void add_bool(const char* key, bool value); // 1 / 0
        void add_hex32(const char* key, std::uint32_t value); // 0x%08X
        void add_hex64(const char* key, std::uint64_t value); // 0x%016llX
        void add_float(const char* key, double value, int precision); // %.Nf, same text as fprintf (nan/inf too)
        void add_str(const char* key, std::string_view value); // printable ASCII, non-empty

        bool ok() const { return error_ == nullptr; }
        const char* error() const { return error_ ? error_ : "none"; }
        std::string_view view() const { return {buffer_, length_}; }
        std::size_t key_count() const { return key_count_; }
        void clear();

      private:
        bool begin_line(const char* key);
        void append(std::string_view text);
        void end_line();
        void fail(const char* reason);

        char* buffer_;
        std::size_t capacity_;
        std::size_t length_ = 0;
        const char* error_ = nullptr;
        std::uint64_t key_hashes_[kMaxKeys] = {};
        std::size_t key_count_ = 0;
    };

    enum class PublishResult : std::uint8_t
    {
        Published = 0,
        NotConfigured,
        InvalidBody,   // Builder error or empty body
        TempBlocked,   // stale temp is a directory / cannot be deleted
        CreateFailed,
        NotPlainFile,  // the new temp is a reparse point / hard-linked
        WriteFailed,   // short or failed write (the old file is untouched)
        FlushFailed,
        CloseFailed,
        RenameFailed,  // MoveFileExW failed (e.g. a reader without FILE_SHARE_DELETE)
        Skipped,       // Publisher: unchanged and the beat is not due
    };

    struct WriterCounters
    {
        std::uint64_t publishes = 0;
        std::uint64_t write_failures = 0;  // everything before the rename
        std::uint64_t rename_failures = 0;
        std::uint64_t fallback_renames = 0; // MoveFileExW used (FileRenameInfoEx unsupported)
        std::uint64_t rename_retries = 0;   // transient ACCESS_DENIED/SHARING_VIOLATION retried
        std::uint32_t last_error = 0;      // GetLastError of the last failure
        PublishResult last_result = PublishResult::NotConfigured;
    };

    class Writer
    {
      public:
        static constexpr unsigned kRenameAttempts = 4;

        // temp_path defaults to final_path + L".tmp" when empty. Both are
        // made absolute (GetFullPathNameW) here, once.
        bool configure(std::wstring final_path, std::wstring temp_path = {});
        bool configured() const { return !final_path_.empty(); }
        PublishResult publish(std::string_view body, bool flush = false);
        const WriterCounters& counters() const { return counters_; }
        const std::wstring& final_path() const { return final_path_; }
        const std::wstring& temp_path() const { return temp_path_; }

      private:
        std::wstring final_path_;
        std::wstring temp_path_;
        WriterCounters counters_;
    };

    // Renames an open handle (opened with DELETE access) to absolute_target,
    // replacing an existing file with POSIX semantics (FileRenameInfoEx,
    // REPLACE_IF_EXISTS | POSIX_SEMANTICS). A relative path is refused:
    // KernelBase would resolve it against the current directory. The panel
    // can do the same through ctypes instead of os.replace().
    bool rename_handle_posix(void* file, std::wstring_view absolute_target);
    bool is_absolute_path(std::wstring_view path);

    // The replace the panel should use instead of os.replace() (reference
    // implementation; Python can do the same through ctypes): open `source`
    // with DELETE access and rename it over `target` with POSIX semantics,
    // retrying a transient ACCESS_DENIED/SHARING_VIOLATION up to `attempts`
    // times (Sleep(0), then Sleep(1)).
    bool replace_file_posix(const std::wstring& source, const std::wstring& target, unsigned attempts = 4,
                            unsigned* retries_used = nullptr, unsigned long* error_out = nullptr);

    class Publisher
    {
      public:
        struct Options
        {
            const char* module = nullptr;         // ASCII, copied
            const char* module_version = nullptr; // ASCII, copied
            std::uint64_t beat_ms = 1000;         // liveness beat; keep <= panel max_age / 3
            std::uint64_t min_interval_ms = 100;  // rate limit for changed bodies
        };

        bool configure(const Options& options, std::wstring final_path, std::wstring temp_path = {});
        // Publishes if the body changed (and min_interval passed) or the beat
        // is due, or force. now_ms: GetTickCount64() or a test clock.
        PublishResult maybe_publish(const Builder& body, std::uint64_t now_ms, bool force = false);
        std::uint64_t sequence() const { return sequence_; }
        std::uint64_t skipped() const { return skipped_; }
        const Writer& writer() const { return writer_; }

      private:
        Writer writer_;
        std::string module_;
        std::string module_version_;
        std::uint64_t beat_ms_ = 1000;
        std::uint64_t min_interval_ms_ = 100;
        std::uint64_t sequence_ = 0;
        std::uint64_t skipped_ = 0;
        std::uint64_t last_hash_ = 0;
        std::uint64_t last_publish_ms_ = 0;
        bool published_once_ = false;
        std::string scratch_;
    };

    enum class ReadResult : std::uint8_t
    {
        Ok = 0,
        Missing,     // ERROR_FILE_NOT_FOUND / ERROR_PATH_NOT_FOUND: the writer removed it
        NotPlain,    // directory, reparse point or more than one hard link
        Empty,
        TooLarge,
        ReadFailed,
        ContainsNul,
        Busy,        // transient: sharing/lock violation, access denied or delete pending
                     // after 3 attempts. Keep the last good state; do NOT treat as Missing.
    };

    // Opens with FILE_SHARE_READ|WRITE|DELETE. A file replaced after the open
    // (0 links) is still read: it is a complete previous version.
    ReadResult read_small_file(const std::wstring& path, std::string& output, std::size_t max_bytes = 4096);

                                                                           
                                                                          
    // alike) the name is occasionally absent for a few ms (~1 window per
    // 10,000 replaces), and a file can be briefly Busy. StableReader returns
    // the last good content while the file is Missing/Busy for less than
    // grace_ms, and reports the failure only once it has lasted grace_ms.
    // Hard failures (NotPlain, TooLarge, ContainsNul, Empty, ReadFailed) are
    // reported at once and drop the cached content (fail closed).
    class StableReader
    {
      public:
        struct Options
        {
            std::size_t max_bytes = 4096;
            std::uint64_t grace_ms = 500;
        };

        struct Read
        {
            ReadResult raw = ReadResult::Missing; // what read_small_file returned now
            ReadResult effective = ReadResult::Missing; // Ok when content is usable
            bool from_cache = false;                    // content is the last good read
        };

        bool configure(std::wstring path, const Options& options);
        bool configure(std::wstring path);
        // now_ms: GetTickCount64() or a test clock.
        Read read(std::uint64_t now_ms);
        const std::string& content() const { return content_; }
        std::uint64_t grace_hits() const { return grace_hits_; }

      private:
        std::wstring path_;
        Options options_{};
        std::string content_;
        bool have_content_ = false;
        std::uint64_t first_failure_ms_ = 0;
        bool failing_ = false;
        std::uint64_t grace_hits_ = 0;
    };

    const char* publish_result_name(PublishResult result);
    const char* read_result_name(ReadResult result);

    // FNV-1a 64 (the Publisher's change detector; exposed for tests).
    std::uint64_t fnv1a64(std::string_view data);

#if defined(SBCORE_TESTING)
    namespace testing
    {
        // Makes the next Writer::publish write only `bytes` bytes and report a
        // short write (simulated disk-full / short write).
        void fail_next_write_after(std::size_t bytes);
    }
#endif
}

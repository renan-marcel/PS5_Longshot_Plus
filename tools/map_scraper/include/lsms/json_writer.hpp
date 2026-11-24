// lsms: a small streaming JSON writer (the catalogue's export). Strings are checked as UTF-8: a byte that is not
// valid UTF-8 is written as U+FFFD, so a damaged name in a game file never makes the whole file invalid JSON.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace lsms {

class JsonWriter {
public:
    explicit JsonWriter(bool pretty = true) : pretty_(pretty) {}

    JsonWriter& begin_object();
    JsonWriter& end_object();
    JsonWriter& begin_array();
    JsonWriter& end_array();
    JsonWriter& key(std::string_view k);
    JsonWriter& str(std::string_view s);
    JsonWriter& num(double v);  // NaN and infinities as null
    JsonWriter& uint(std::uint64_t v);
    JsonWriter& sint(std::int64_t v);
    JsonWriter& boolean(bool v);
    JsonWriter& null();

    std::string take() { return std::move(out_); }
    static void escape_into(std::string& out, std::string_view s);

private:
    void value_prefix();
    void comma();
    void indent();
    void open(char c);
    void close(char c);

    std::string out_;
    std::vector<bool> has_items_;
    bool pretty_;
    bool after_key_ = false;
};

}  // namespace lsms

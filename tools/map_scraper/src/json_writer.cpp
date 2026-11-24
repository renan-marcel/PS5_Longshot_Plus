// lsms: the JSON writer.
#include "lsms/json_writer.hpp"

#include <cmath>
#include <cstdio>

namespace lsms {

JsonWriter& JsonWriter::begin_object() { open('{'); return *this; }
JsonWriter& JsonWriter::end_object() { close('}'); return *this; }
JsonWriter& JsonWriter::begin_array() { open('['); return *this; }
JsonWriter& JsonWriter::end_array() { close(']'); return *this; }

JsonWriter& JsonWriter::key(std::string_view k) {
    comma();
    escape_into(out_, k);
    out_ += pretty_ ? ": " : ":";
    after_key_ = true;
    return *this;
}

JsonWriter& JsonWriter::str(std::string_view s) {
    value_prefix();
    escape_into(out_, s);
    return *this;
}

JsonWriter& JsonWriter::num(double v) {
    value_prefix();
    if (!std::isfinite(v)) {
        out_ += "null";
        return *this;
    }
    char buf[40];
    std::snprintf(buf, sizeof buf, "%.9g", v);
    out_ += buf;
    return *this;
}

JsonWriter& JsonWriter::uint(std::uint64_t v) {
    value_prefix();
    out_ += std::to_string(v);
    return *this;
}

JsonWriter& JsonWriter::sint(std::int64_t v) {
    value_prefix();
    out_ += std::to_string(v);
    return *this;
}

JsonWriter& JsonWriter::boolean(bool v) {
    value_prefix();
    out_ += v ? "true" : "false";
    return *this;
}

JsonWriter& JsonWriter::null() {
    value_prefix();
    out_ += "null";
    return *this;
}

void JsonWriter::value_prefix() {
    if (after_key_) {
        after_key_ = false;
        return;
    }
    comma();
}

void JsonWriter::comma() {
    if (has_items_.empty()) return;
    if (has_items_.back()) out_ += ',';
    has_items_.back() = true;
    indent();
}

void JsonWriter::indent() {
    if (!pretty_) return;
    out_ += '\n';
    out_.append(has_items_.size() * 2, ' ');
}

void JsonWriter::open(char c) {
    value_prefix();
    out_ += c;
    has_items_.push_back(false);
}

void JsonWriter::close(char c) {
    const bool had = !has_items_.empty() && has_items_.back();
    if (!has_items_.empty()) has_items_.pop_back();
    if (had) indent();
    out_ += c;
}

void JsonWriter::escape_into(std::string& out, std::string_view s) {
    static const char* const hex = "0123456789abcdef";
    out += '"';
    const auto* p = reinterpret_cast<const unsigned char*>(s.data());
    const std::size_t n = s.size();
    for (std::size_t i = 0; i < n;) {
        const unsigned char c = p[i];
        if (c < 0x80) {
            switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    out += "\\u00";
                    out += hex[c >> 4];
                    out += hex[c & 15];
                } else {
                    out += static_cast<char>(c);
                }
            }
            ++i;
            continue;
        }
        // A UTF-8 sequence: kept whole when valid (no overlongs, no surrogates, at most U+10FFFF), else U+FFFD
        std::size_t len = 0;
        std::uint32_t cp = 0, min = 0;
        if ((c & 0xE0) == 0xC0) { len = 2; cp = c & 0x1F; min = 0x80; }
        else if ((c & 0xF0) == 0xE0) { len = 3; cp = c & 0x0F; min = 0x800; }
        else if ((c & 0xF8) == 0xF0) { len = 4; cp = c & 0x07; min = 0x10000; }
        bool ok = len != 0 && i + len <= n;
        for (std::size_t k = 1; ok && k < len; ++k) {
            if ((p[i + k] & 0xC0) != 0x80) ok = false;
            else cp = (cp << 6) | (p[i + k] & 0x3F);
        }
        ok = ok && cp >= min && cp <= 0x10FFFF && (cp < 0xD800 || cp > 0xDFFF);
        if (ok) {
            out.append(s.substr(i, len));
            i += len;
        } else {
            out += "\xEF\xBF\xBD";
            ++i;
        }
    }
    out += '"';
}

}  // namespace lsms

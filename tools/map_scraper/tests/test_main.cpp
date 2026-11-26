// lsms unit tests, on synthetic buffers only (builders.hpp). No framework: CHECK records a failure and goes on,
// REQUIRE stops the test. Exit status: the number of failed checks (0: all passed).
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>

#include "builders.hpp"
#include "lsms/byml_parser.hpp"
#include "lsms/lsms.h"
#include "lsms/map_scraper.hpp"
#include "lsms/sarc_reader.hpp"
#include "lsms/zstd_stream.hpp"

using namespace lsms_test;

static int failures = 0;
#define CHECK(c)                                                                     \
    do {                                                                             \
        if (!(c)) {                                                                  \
            std::fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #c); \
            ++failures;                                                              \
        }                                                                            \
    } while (0)
#define REQUIRE(c)                                                                     \
    do {                                                                               \
        if (!(c)) {                                                                    \
            std::fprintf(stderr, "%s:%d: REQUIRE(%s) failed\n", __FILE__, __LINE__, #c); \
            ++failures;                                                                \
            return;                                                                    \
        }                                                                              \
    } while (0)

static ByteVec bytes(std::string_view s) {
    ByteVec v;
    for (char c : s) v.push_back(std::byte(static_cast<unsigned char>(c)));
    return v;
}

static bool near(float a, float b) { return std::fabs(a - b) < 1e-5f; }

// A small map: two Octoroks (one transform as an array, one as X/Y/Z), a chest with its model and collision by key and
// by extension, a sub-map list, and a nested group with a weak "Name" key beside a transform.
static BValue sample_map() {
    return dict({
        {"Actors", arr({
                       dict({{"Gyaml", "Enemy_Octorok"},
                             {"Translate", arr({1.0, 2.0, 3.0})},
                             {"Rotate", arr({0.0, 1.5, 0.0})},
                             {"Scale", dict({{"X", 1.0}, {"Y", 1.0}, {"Z", 1.0}})}}),
                       dict({{"Gyaml", "Enemy_Octorok"}, {"Translate", dict({{"X", 4.0}, {"Y", 5.0}, {"Z", 6.0}})}}),
                       dict({{"Gyaml", "Obj_TreasureBox"},
                             {"Translate", arr({7.0, 8.0, 9.0})},
                             {"ModelName", "Obj_TreasureBox_A"},
                             {"Phive", dict({{"Shape", "Phive/Shape/Dcc/TreasureBox.bphsh"}}) },
                             {"Fx", "Effect/Sparkle.esetb.byml.zs"}}),
                   })},
        {"SubMaps", arr({"Banc/Field_A1", "Banc/Field_A2"})},
        {"Group", dict({{"Items", arr({dict({{"Name", "Item_Rupee"}, {"Pos", arr({1.0, 1.0, 1.0})}}),
                                       dict({{"Name", "NotAnActor"}})})}})},
        {"Comment", "a string with spaces.bfres is not a path"},
    });
}

static void test_sarc() {
    const ByteVec a = bytes("first file"), b = bytes("second"), c = bytes("");
    const ByteVec archive = make_sarc({{"Map/A.byml", a}, {"Map/B.byml", b}, {"Empty.bin", c}});
    auto s = lsms::SarcReader::open(archive);
    REQUIRE(s);
    CHECK(s->size() == 3);
    CHECK(!s->big_endian());
    CHECK(s->hash_key() == 0x65);
    const auto* e = s->find("Map/B.byml");
    REQUIRE(e);
    CHECK(e->data.size() == b.size() && std::memcmp(e->data.data(), b.data(), b.size()) == 0);
    CHECK(e->name_hash == lsms::SarcReader::name_hash("Map/B.byml"));
    CHECK(s->find("Empty.bin") && s->find("Empty.bin")->data.empty());
    CHECK(!s->find("missing"));
    // (entries come out sorted by hash, as the format keeps them)
    for (std::size_t i = 1; i < s->size(); ++i) CHECK((*s)[i - 1].name_hash <= (*s)[i].name_hash);

    // Damage: a cut archive, a wrong magic, a data range past the end
    ByteVec cut(archive.begin(), archive.begin() + 0x30);
    CHECK(!lsms::SarcReader::open(cut));
    ByteVec bad = archive;
    bad[0] = std::byte{'X'};
    CHECK(!lsms::SarcReader::open(bad) && lsms::SarcReader::open(bad).error().code == lsms::Errc::bad_magic);
    ByteVec far = archive;
    far[0x20 + 12] = std::byte{0xFF};   // the first node's data end
    far[0x20 + 13] = std::byte{0xFF};
    CHECK(!lsms::SarcReader::open(far));
}

static void test_byml() {
    const ByteVec doc_bytes = BymlWriter().write(dict({
        {"Name", "Field"},
        {"Count", 3},
        {"Scale", 1.5},
        {"On", true},
        {"Hash", BValue::hash(0xDEADBEEFu)},
        {"List", arr({"a", 2, arr({})})},
    }));
    auto doc = lsms::byml::Document::parse(doc_bytes);
    REQUIRE(doc);
    CHECK(doc->version() == 7);
    CHECK(!doc->big_endian());
    const auto root = doc->root();
    REQUIRE(root && root->is_dictionary());
    CHECK(root->size() && *root->size() == 6);
    CHECK(root->find("Name") && root->find("Name")->as_string() == std::string_view("Field"));
    CHECK(root->find("Count") && root->find("Count")->as_int() == 3);
    CHECK(root->find("Scale") && near(float(*root->find("Scale")->as_double()), 1.5f));
    CHECK(root->find("On") && root->find("On")->as_bool() == true);
    CHECK(root->find("Hash") && root->find("Hash")->as_uint() == 0xDEADBEEFu);
    CHECK(!root->find("Nope"));
    const auto list = root->find("List");
    REQUIRE(list && list->is_array());
    CHECK(*list->size() == 3);
    CHECK(list->at(0)->as_string() == std::string_view("a"));
    CHECK(list->at(1)->as_int() == 2);
    CHECK(list->at(2)->is_array() && *list->at(2)->size() == 0);
    CHECK(!list->at(3));
    // Members come out in key order, with their names
    const auto m0 = root->member(0);
    REQUIRE(m0);
    CHECK(m0->key == "Count" && !m0->hashed_key);

    // An empty document, a version out of range, a wrong magic, a root past the end
    auto empty = BymlWriter().write(dict({}));
    auto e = lsms::byml::Document::parse(empty);
    CHECK(e && e->root() && *e->root()->size() == 0);
    ByteVec v1 = doc_bytes;
    v1[2] = std::byte{1};
    CHECK(!lsms::byml::Document::parse(v1) && lsms::byml::Document::parse(v1).error().code == lsms::Errc::unsupported_version);
    ByteVec bad = doc_bytes;
    bad[0] = std::byte{'Z'};
    CHECK(!lsms::byml::Document::parse(bad));
    ByteVec far = doc_bytes;
    far[12] = far[13] = far[14] = std::byte{0x7F};
    CHECK(!lsms::byml::Document::parse(far));
}

static void test_zstd() {
    CHECK(lsms::is_zstd_frame(zstd_raw(bytes("x"))));
    CHECK(!lsms::is_zstd_frame(bytes("YB..")));
    if (!lsms::zstd_available()) {
        CHECK(lsms::zstd_decompress(zstd_raw(bytes("x"))).error().code == lsms::Errc::unsupported);
        return;
    }
    const ByteVec text = bytes("a map, stored in a raw zstd block");
    auto out = lsms::zstd_decompress(zstd_raw(text));
    REQUIRE(out);
    CHECK(*out == text);
    // Larger than one block (two raw blocks), and two frames back to back
    ByteVec big(300 * 1024);
    for (std::size_t i = 0; i < big.size(); ++i) big[i] = std::byte(i * 7);
    ByteVec two = zstd_raw(big);
    const ByteVec second = zstd_raw(text);
    two.insert(two.end(), second.begin(), second.end());
    auto both = lsms::zstd_decompress(two);
    REQUIRE(both);
    CHECK(both->size() == big.size() + text.size());
    // Streaming: fed in small pieces (each frame's header whole in its first piece)
    lsms::ZstdStream stream;
    std::size_t got = 0;
    bool done = false;
    const ByteVec one = zstd_raw(big);
    for (std::size_t at = 0; at < one.size(); at += 4096) {
        const std::size_t n = std::min<std::size_t>(4096, one.size() - at);
        auto r = stream.feed(lsms::Bytes(one.data() + at, n), [&](lsms::Bytes c) { got += c.size(); return true; });
        REQUIRE(r);
        done = *r;
    }
    CHECK(done && got == big.size());
    // A frame that names a dictionary nobody loaded; a frame cut short; the output limit
    auto need = lsms::zstd_decompress(zstd_raw(text, 12345));
    CHECK(!need && need.error().code == lsms::Errc::missing_dictionary);
    ByteVec cut = zstd_raw(text);
    cut.resize(cut.size() - 5);
    CHECK(!lsms::zstd_decompress(cut));
    CHECK(lsms::zstd_decompress(zstd_raw(big), nullptr, lsms::ZstdOptions{1000}).error().code == lsms::Errc::too_large);
}

static void test_scraper() {
    lsms::MapScraper s;
    const ByteVec map = BymlWriter().write(sample_map());
    REQUIRE(s.scan_buffer(map, "Banc/Test.bcett.byml"));
    const auto& c = s.catalog();
    CHECK(c.maps_scanned().size() == 1);

    const auto* octo = c.find("Banc/Test.bcett.byml", lsms::Category::actor, "Enemy_Octorok");
    REQUIRE(octo);
    CHECK(octo->instance_count == 2);
    CHECK(octo->via_key == "Gyaml");
    REQUIRE(octo->sample_transform && octo->sample_transform->translate);
    // (records are kept in walk order: the first Octorok's transform is the sample)
    CHECK(near(octo->sample_transform->translate->x, 1) && near(octo->sample_transform->translate->z, 3));
    CHECK(octo->sample_transform->rotate && near(octo->sample_transform->rotate->y, 1.5f));
    CHECK(octo->sample_transform->scale && near(octo->sample_transform->scale->x, 1));

    const auto* box = c.find("Banc/Test.bcett.byml", lsms::Category::actor, "Obj_TreasureBox");
    CHECK(box && box->instance_count == 1);
    const auto* model = c.find("Banc/Test.bcett.byml", lsms::Category::model, "Obj_TreasureBox_A");
    REQUIRE(model);
    CHECK(model->via_key == "ModelName");
    CHECK(model->sample_transform && near(model->sample_transform->translate->y, 8));   // (the chest's placement)
    // "Phive" is a collision key: its dictionary's string is a collision reference (and by extension too, the same)
    CHECK(c.find("Banc/Test.bcett.byml", lsms::Category::collision, "Phive/Shape/Dcc/TreasureBox.bphsh"));
    CHECK(c.find("Banc/Test.bcett.byml", lsms::Category::effect, "Effect/Sparkle.esetb.byml.zs"));
    CHECK(c.find("Banc/Test.bcett.byml", lsms::Category::submap, "Banc/Field_A1"));
    CHECK(c.find("Banc/Test.bcett.byml", lsms::Category::submap, "Banc/Field_A2"));
    // The weak key: "Name" beside a transform is an actor; without one it is not
    CHECK(c.find("Banc/Test.bcett.byml", lsms::Category::actor, "Item_Rupee"));
    CHECK(!c.find("Banc/Test.bcett.byml", lsms::Category::actor, "NotAnActor"));
    // A sentence that happens to end in an extension is not a path
    for (const auto& r : c.records()) CHECK(r.name.find(' ') == std::string::npos);
    // The census saw the keys
    CHECK(c.key_census().count("Gyaml") && c.key_census().at("Gyaml").count == 3);

    // Scanning the same map again under another name: separate records, aggregated in the summary
    REQUIRE(s.scan_buffer(map, "Banc/Copy.bcett.byml"));
    bool seen = false;
    for (const auto& a : c.aggregate())
        if (a.category == lsms::Category::actor && a.name == "Enemy_Octorok") {
            seen = true;
            CHECK(a.instance_count == 4 && a.maps.size() == 2);
        }
    CHECK(seen);
}

static void test_config() {
    // Another title's schema: the actor under "UnitConfigName", the model under "Mdl", vectors as {x, y, z}
    lsms::ScraperConfig cfg;
    cfg.actor_keys = {"UnitConfigName"};
    cfg.resource_keys.push_back({"Mdl", lsms::Category::model});
    cfg.x_keys = {"x"};
    cfg.y_keys = {"y"};
    cfg.z_keys = {"z"};
    cfg.case_insensitive_keys = false;
    lsms::MapScraper s(cfg);
    const ByteVec map = BymlWriter().write(dict({{"Objs", arr({dict({{"UnitConfigName", "Kuribo"},
                                                                     {"Mdl", "Kuribo_Mdl"},
                                                                     {"Translate", dict({{"x", 1.0}, {"y", 2.0}, {"z", 3.0}})},
                                                                     {"Gyaml", "IgnoredHere"}})})}}));
    REQUIRE(s.scan_buffer(map, "Stage.byml"));
    const auto* k = s.catalog().find("Stage.byml", lsms::Category::actor, "Kuribo");
    REQUIRE(k);
    CHECK(k->sample_transform && near(k->sample_transform->translate->z, 3));
    CHECK(s.catalog().find("Stage.byml", lsms::Category::model, "Kuribo_Mdl"));
    CHECK(!s.catalog().find("Stage.byml", lsms::Category::actor, "IgnoredHere"));

    // Hashed actor names, named through hash_names
    lsms::MapScraper h;
    h.config().hash_names[0x1234u] = "Npc_Saria";
    const ByteVec hashed = BymlWriter().write(dict({{"Actors", arr({dict({{"Gyaml", BValue::hash(0x1234u)}}),
                                                                    dict({{"Gyaml", BValue::hash(0x99u)}})})}}));
    REQUIRE(h.scan_buffer(hashed, "H.byml"));
    CHECK(h.catalog().find("H.byml", lsms::Category::actor, "Npc_Saria"));
    CHECK(h.catalog().find("H.byml", lsms::Category::actor, "hash:0x00000099"));
}

static void test_layers_and_resolution() {
    if (!lsms::zstd_available()) return;
    // Pack/Field.pack.zs = zstd( SARC{ "Banc/Field.bcett.byml.zs" = zstd(BYML), "Model/x.bfres" = noise } )
    const ByteVec inner = zstd_raw(BymlWriter().write(sample_map()));
    const ByteVec pack = zstd_raw(make_sarc({{"Banc/Field.bcett.byml.zs", inner}, {"Model/x.bfres", bytes("not a map")}}));
    lsms::MapScraper s;
    auto index = std::make_shared<lsms::RomfsIndex>();
    index->add("Pack/Actor/Enemy_Octorok.pack.zs");
    index->add("Model/Obj_TreasureBox_A.bfres.zs");
    index->add("Banc/Field_A1.bcett.byml.zs");
    index->add("Effect\\Sparkle.esetb.byml.zs");   // (backslashes normalized)
    index->add("Pack/Actor/Item_Rupee.pack.zs");
    s.set_romfs_index(index);
    REQUIRE(s.scan_buffer(pack, "Pack/Field.pack.zs"));
    const std::string src = "Pack/Field.pack.zs:Banc/Field.bcett.byml.zs";
    CHECK(s.catalog().maps_scanned().size() == 1 && s.catalog().maps_scanned()[0] == src);
    const std::size_t missing = s.resolve();
    const auto* octo = s.catalog().find(src, lsms::Category::actor, "Enemy_Octorok");
    REQUIRE(octo);
    CHECK(octo->resolution == lsms::Resolution::found);
    CHECK(octo->resolved_paths.size() == 1 && octo->resolved_paths[0] == "Pack/Actor/Enemy_Octorok.pack.zs");
    const auto* model = s.catalog().find(src, lsms::Category::model, "Obj_TreasureBox_A");
    CHECK(model && model->resolution == lsms::Resolution::found);
    const auto* fx = s.catalog().find(src, lsms::Category::effect, "Effect/Sparkle.esetb.byml.zs");
    CHECK(fx && fx->resolution == lsms::Resolution::found);
    const auto* sub = s.catalog().find(src, lsms::Category::submap, "Banc/Field_A1");
    CHECK(sub && sub->resolution == lsms::Resolution::found);
    const auto* box = s.catalog().find(src, lsms::Category::actor, "Obj_TreasureBox");
    CHECK(box && box->resolution == lsms::Resolution::missing);
    CHECK(missing == s.catalog().unresolved().size());
    CHECK(missing >= 3);   // the box, Field_A2, the collision shape

    // The JSON names the unresolved, and stays valid around awkward strings
    lsms::MapScraper q;
    const ByteVec odd = BymlWriter().write(dict({{"Actors", arr({dict({{"Gyaml", "Quote\"Back\\slash\x01\xff"}})})}}));
    REQUIRE(q.scan_buffer(odd, "odd.byml"));
    const std::string j = q.to_json();
    CHECK(j.find("\"Quote\\\"Back\\\\slash\\u0001\xEF\xBF\xBD\"") != std::string::npos);
    const std::string full = s.to_json({true, true, true, 10});
    CHECK(full.find("\"unresolved\"") != std::string::npos);
    CHECK(full.find("\"key_census\"") != std::string::npos);
    CHECK(full.find("\"Obj_TreasureBox\"") != std::string::npos);
}

static void test_damaged_input_never_crashes() {
    // Every single-byte change of a valid pack-less map, and random overwrites: the scraper answers or reports, never
    // reads out of bounds (run this under -fsanitize=address,undefined)
    const ByteVec good = BymlWriter().write(sample_map());
    std::uint32_t seed = 12345;
    auto rnd = [&] { seed = seed * 1664525u + 1013904223u; return seed; };
    for (std::size_t i = 0; i < good.size(); ++i) {
        ByteVec d = good;
        d[i] = std::byte(rnd() & 0xFF);
        lsms::MapScraper s;
        (void)s.scan_buffer(d, "fuzz");
        (void)s.to_json();
    }
    for (int round = 0; round < 3000; ++round) {
        ByteVec d = good;
        for (int k = 0; k < 4; ++k) d[rnd() % d.size()] = std::byte(rnd() & 0xFF);
        if (rnd() % 4 == 0) d.resize(rnd() % d.size());
        lsms::MapScraper s;
        (void)s.scan_buffer(d, "fuzz");
    }
    const ByteVec sarc = make_sarc({{"a.byml", good}});
    for (std::size_t i = 0; i < 0x60 && i < sarc.size(); ++i) {
        ByteVec d = sarc;
        d[i] = std::byte(rnd() & 0xFF);
        lsms::MapScraper s;
        (void)s.scan_buffer(d, "fuzz.sarc");
    }
    CHECK(true);
}

static void test_c_api() {
    CHECK(lsms_api_version() == LSMS_C_API_VERSION);
    lsms_scraper* s = lsms_create();
    REQUIRE(s);
    CHECK(lsms_add_actor_key(s, "Gyaml") == LSMS_OK);
    CHECK(lsms_add_resource_key(s, "bogus", "X") == LSMS_E_INVALID_ARGUMENT);
    CHECK(std::strlen(lsms_last_error(s)) > 0);
    CHECK(lsms_set_option(s, "key_census", 0) == LSMS_OK);
    const ByteVec map = BymlWriter().write(sample_map());
    CHECK(lsms_scan_buffer(s, map.data(), map.size(), "c.byml") == LSMS_OK);
    CHECK(lsms_record_count(s) > 0);
    CHECK(lsms_scan_buffer(s, "garbage!", 8, "g") == LSMS_E_FAILED);
    char* json = lsms_to_json(s, 0, 0);
    REQUIRE(json);
    CHECK(std::strstr(json, "Enemy_Octorok") != nullptr);
    lsms_free(json);
    CHECK(lsms_resolve(s) == 0);   // (no index: nothing resolved, a warning in the diagnostics)
    lsms_destroy(s);
}

int main() {
    test_sarc();
    test_byml();
    test_zstd();
    test_scraper();
    test_config();
    test_layers_and_resolution();
    test_damaged_input_never_crashes();
    test_c_api();
    if (failures) {
        std::fprintf(stderr, "lsms tests: %d failed\n", failures);
        return 1;
    }
    std::puts("lsms tests: all passed");
    return 0;
}

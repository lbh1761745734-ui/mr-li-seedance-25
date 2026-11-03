"""Real-data retrieval and corruption tests; no LLM or media quality claims."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("query_cinematique", ROOT / "scripts/query_cinematique.py")
query_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(query_tool)
DATA_PRESENT = (ROOT / "references/cinematique-data/aesthetics.json").is_file()


@unittest.skipUnless(DATA_PRESENT, "cinematique-data 未随开源版分发")
class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.library = query_tool.Library(ROOT / "references/cinematique-data")

    def test_real_library_coverage_and_mappings(self):
        result = self.library.verify()
        self.assertTrue(result["ok"], result["errors"])

    def test_catalog_contains_labels_not_full_cards(self):
        result = self.library.catalog()
        self.assertEqual(98, len(result["styles"]))
        self.assertEqual(18, len(result["categories"]))
        self.assertEqual(2733, sum(result["categories"].values()))
        self.assertTrue(all(set(card) == {"id", "label", "kind"} for card in result["styles"]))

    def test_exact_id_returns_complete_card(self):
        expected = self.library.load("aesthetics")["style_family_cards"][0]
        result = self.library.search("styles", identifier=expected["id"])
        self.assertEqual([expected], [row["card"] for row in result["results"]])
        self.assertIn("未逐图审阅", result["evidence_boundary"])

    def test_source_key_resolves_full_target_without_other_modules(self):
        source = next(row for row in self.library.load("sources") if row["category"] == "摄影机运动")
        result = self.library.search("techniques", identifier=source["key"])
        self.assertEqual({m["card_id"] for m in source["distilled_mapping"]},
                         {row["id"] for row in result["results"]})
        for row in result["results"]:
            self.assertEqual([source], row["source_evidence"])
        self.assertEqual([], self.library.search("portraits", identifier=source["key"])["results"])
        self.assertEqual([], self.library.search("styles", identifier=source["key"])["results"])

    def test_source_query_returns_original_source_and_full_mapping(self):
        source = self.library.load("sources")[0]
        row = self.library.search("sources", identifier=source["source_id"])["results"][0]
        self.assertEqual(source, row["card"])
        target = self.library.targets()[(source["distilled_mapping"][0]["module"],
                                         source["distilled_mapping"][0]["card_id"])]
        self.assertEqual(target["card"], row["mapped_cards"][0]["card"])

    def test_portrait_option_resolves_entire_field(self):
        group = self.library.load("assets-portraits")["taxonomy"]["肖像大师"]["groups"][0]
        result = self.library.search("portraits", identifier=group["options"][-1]["key"])
        self.assertEqual(group, result["results"][0]["card"])

    def test_keyword_module_isolation_and_limits(self):
        result = self.library.search("portraits", query="年龄", limit=1)
        self.assertGreater(result["total_matches"], 0)
        self.assertEqual(1, len(result["results"]))
        self.assertTrue(all(row["kind"] == "portrait_field" for row in result["results"]))
        self.assertEqual([], self.library.search("films", query="__不存在的独特关键词__")["results"])

    def test_combination_atom_wording_and_source_id_are_retrievable(self):
        atom = next(row for row in self.library.load("aesthetics")["combinator_atoms"]
                    if row["source_label"] == "钢灰")
        for query in (atom["source_label"], atom["translated_use"]):
            result = self.library.search("styles", query=query)
            self.assertTrue(any(atom in row.get("executable_details", []) for row in result["results"]), result)
        result = self.library.search("styles", identifier=atom["source_id"])
        self.assertEqual([atom], result["results"][0]["executable_details"])
        result = self.library.search("sources", identifier=atom["source_id"])
        self.assertEqual([atom], result["results"][0]["mapped_cards"][0]["executable_details"])

    def test_complete_technique_hint_retrieves_its_concept(self):
        term = self.library.load("cinematic-technique")["complete_term_index"][-1]
        result = self.library.search("techniques", query=term["executable_hint"], limit=20)
        self.assertTrue(any(term in row.get("executable_details", []) for row in result["results"]), result)
        result = self.library.search("sources", identifier=term["source_metadata_id"])
        self.assertTrue(all(term in card.get("executable_details", []) for card in result["results"][0]["mapped_cards"]))

    def test_english_source_alias_keeps_its_executable_atom(self):
        result = self.library.search("styles", query="Steel Gray")
        self.assertEqual("钢灰", result["results"][0]["executable_details"][0]["source_label"])

    def test_source_id_plus_keyword_does_not_match_sibling_atom(self):
        result = self.library.search("styles", identifier="电影感组合器:0639", query="奶白")
        self.assertEqual(0, result["total_matches"])
        result = self.library.search("styles", identifier="电影感组合器:0639", query="Steel Gray")
        self.assertEqual("钢灰", result["results"][0]["executable_details"][0]["source_label"])

    def test_no_query_does_not_read_or_dump_data(self):
        library = query_tool.Library(Path("/nonexistent/cinematique-test-path"))
        self.assertEqual([], library.search()["results"])
        self.assertEqual({}, library._data)

    def test_invalid_limit_rejected(self):
        for value in (0, 21, -1):
            with self.subTest(value=value), self.assertRaises(query_tool.DataError):
                self.library.search(query="人物", limit=value)

    def test_cli_exact_film_and_no_results(self):
        film = self.library.load("films")[0]
        output = io.StringIO()
        with redirect_stdout(output):
            code = query_tool.main(["--module", "films", "--id", film["english_title"]])
        self.assertEqual(0, code)
        self.assertEqual(film, json.loads(output.getvalue())["results"][0]["card"])
        output = io.StringIO()
        with redirect_stdout(output):
            code = query_tool.main(["--module", "assets", "--id", "unknown-exact-id"])
        self.assertEqual(0, code)
        self.assertEqual(0, json.loads(output.getvalue())["total_matches"])


@unittest.skipUnless(DATA_PRESENT, "cinematique-data 未随开源版分发")
class CorruptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = ROOT / "references/cinematique-data"
        for filename in query_tool.FILES.values():
            shutil.copyfile(source / filename, self.root / filename)

    def modify(self, name, mutate):
        path = self.root / query_tool.FILES[name]
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def assert_invalid(self, name, mutate, message):
        self.modify(name, mutate)
        result = query_tool.Library(self.root).verify()
        self.assertFalse(result["ok"])
        self.assertTrue(any(message in error for error in result["errors"]), result["errors"])

    def test_unknown_mapping_target_rejected(self):
        self.assert_invalid("sources", lambda rows: rows[0]["distilled_mapping"][0].update(card_id="missing-card"),
                            "不存在的映射目标")

    def test_empty_mapping_rejected(self):
        self.assert_invalid("sources", lambda rows: rows[0].update(distilled_mapping=[]), "空来源映射")

    def test_existing_but_wrong_target_rejected(self):
        def corrupt(rows):
            other = next(row for row in rows if row["category"] == "摄影机运动")
            rows[0]["distilled_mapping"] = copy.deepcopy(other["distilled_mapping"])
        self.assert_invalid("sources", corrupt, "映射目标不包含来源")

    def test_duplicate_real_source_id_rejected(self):
        self.assert_invalid("sources", lambda rows: rows[1].update(source_id=rows[0]["source_id"]), "来源ID: 重复")

    def test_swapped_unique_source_ids_rejected(self):
        def corrupt(rows):
            rows[0]["source_id"], rows[1]["source_id"] = rows[1]["source_id"], rows[0]["source_id"]
        self.assert_invalid("sources", corrupt, "来源key与真实ID错配")

    def test_duplicate_card_id_rejected(self):
        def corrupt(data):
            data["style_family_cards"][1]["id"] = data["style_family_cards"][0]["id"]
        self.assert_invalid("aesthetics", corrupt, "重复卡片 ID")

    def test_missing_required_data_reported(self):
        (self.root / query_tool.FILES["stills"]).unlink()
        result = query_tool.Library(self.root).verify()
        self.assertFalse(result["ok"])
        self.assertTrue(any("still-metadata-2463.json" in error for error in result["errors"]))

    def test_unrelated_missing_module_does_not_block_style_retrieval(self):
        (self.root / query_tool.FILES["stills"]).unlink()
        (self.root / query_tool.FILES["films"]).unlink()
        result = query_tool.Library(self.root).search("styles", identifier="movie-01")
        self.assertEqual("movie-01", result["results"][0]["id"])

    def test_portrait_field_count_and_options_checked(self):
        def corrupt(data):
            data["taxonomy"]["肖像大师"]["groups"][0]["options"].pop()
        self.assert_invalid("assets-portraits", corrupt, "肖像927选项覆盖不完整")

    def test_movie_media_counts_checked(self):
        def corrupt(rows):
            next(row for row in rows if row["category"] == "电影风格" and row["media_kind"] == "video")["media_kind"] = "image"
        self.assert_invalid("sources", corrupt, "电影图片/视频必须为250/129")

    def test_still_count_checked(self):
        self.assert_invalid("stills", lambda data: data["records"].pop(), "127/2463")

    def test_film_frame_relationship_checked(self):
        self.assert_invalid("films", lambda rows: rows[0].update(frame_count=rows[0]["frame_count"] + 1), "frame_count不匹配")

    def test_local_technique_mapping_checked(self):
        def corrupt(data):
            data["complete_term_index"][-1]["concept_ids"] = ["missing-technique"]
        self.assert_invalid("cinematic-technique", corrupt, "技术局部映射无效")

    def test_combination_atom_wrong_family_rejected(self):
        self.assert_invalid("aesthetics", lambda data: data["combinator_atoms"][0].update(inherit_group_card="movie-01"),
                            "组合原子所属卡无效")

    def test_combination_atom_executable_text_missing_rejected(self):
        self.assert_invalid("aesthetics", lambda data: data["combinator_atoms"][0].update(translated_use=""),
                            "组合原子执行内容无效")

    def test_malformed_json_cli_fails_without_dump(self):
        (self.root / query_tool.FILES["aesthetics"]).write_text("{broken", encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = query_tool.main(["--data-dir", str(self.root), "--id", "movie-01"])
        self.assertEqual(2, code)
        self.assertEqual("", output.getvalue())
        self.assertIn("aesthetics.json", json.loads(errors.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()

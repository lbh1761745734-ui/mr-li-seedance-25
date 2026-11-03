#!/usr/bin/env python3
"""Retrieve complete distilled cards; verify library structure, never media quality."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "references/cinematique-data"
FILES = {
    "aesthetics": "aesthetics.json", "cinematic-technique": "cinematic-technique.json",
    "assets-portraits": "assets-portraits.json", "sources": "source-index-2733.json",
    "films": "film-index-127.json", "stills": "still-metadata-2463.json",
}
MODULES = ("styles", "techniques", "portraits", "assets", "films", "sources")
TARGET_MODULES = {"aesthetics": "styles", "cinematic-technique": "techniques"}
EXPECTED_COUNTS = {
    "美术资产": 47, "摄影机运动": 330, "灯光": 38, "构图": 21, "剪辑": 17,
    "叙事": 12, "视觉特效": 8, "类型风格": 82, "胶片": 200, "相机机型": 21,
    "镜头特性": 16, "美学修饰": 12, "环境参数": 3, "电影感组合器": 228,
    "艺术风格大师": 382, "肖像大师": 927, "数字人创作": 10, "电影风格": 379,
}
BOUNDARY = (
    "来源文本蒸馏与元数据，仅供检索、推荐候选及可执行特征选择；"
    "不证明真实作品归属、器材物理复现、制作署名或生成效果。"
    "剧照这里只含元数据，未逐图审阅；正式执行仍由当前李先生规则、"
    "权威剧本、已确认基调、范围、声音及画幅决定。"
)


class DataError(ValueError):
    """Missing, malformed or internally inconsistent library data."""


MISSING_HINT = ("开源版未附带 references/cinematique-data/ 数据文件（来源 MOKE Cinematique，"
                "需获得授权后自行放入）。没有数据时，风格推荐仍按剧本和视觉基调规则进行。")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def matches(value, query):
    haystack = "\n".join(strings(value)).casefold()
    return all(term.casefold() in haystack for term in query.split())


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


class Library:
    def __init__(self, directory=DEFAULT_DATA):
        self.directory = Path(directory)
        self._data = {}
        self._registries = {}
        self._details = {}

    def details(self, module):
        """Keep executable atoms attached to their source-backed family cards."""
        if module not in self._details:
            grouped = defaultdict(list)
            if module == "styles":
                for atom in self.load("aesthetics")["combinator_atoms"]:
                    grouped[atom["inherit_group_card"]].append(atom)
            elif module == "techniques":
                for term in self.load("cinematic-technique")["complete_term_index"]:
                    for identifier in term["concept_ids"]:
                        grouped[identifier].append(term)
            self._details[module] = grouped
        return self._details[module]

    def matched_details(self, module, card_id, query=None, identifier=None,
                        source_keys=()):
        details = self.details(module).get(card_id, [])
        if source_keys:
            details = [row for row in details if row.get("source_key") in source_keys]
        elif identifier and identifier != card_id:
            details = [row for row in details if identifier in
                       (row.get("source_key"), row.get("source_id"),
                        row.get("source_metadata_id"))]
        if query:
            details = [row for row in details if matches(row, query)]
        return details

    def load(self, name):
        if name not in self._data:
            path = self.directory / FILES[name]
            try:
                self._data[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise DataError(f"不能读取 {path.name}: {exc}") from exc
        return self._data[name]

    def registry(self, module):
        if module in self._registries:
            return self._registries[module]
        records = []

        def add(identifier, kind, card, keys=()):
            if not nonempty(identifier) or not isinstance(card, dict):
                raise DataError(f"{module}: 无效卡片身份")
            records.append({"id": identifier, "kind": kind, "card": card,
                            "source_keys": list(keys)})

        try:
            if module == "styles":
                data = self.load("aesthetics")
                for card in data["style_family_cards"]:
                    add(card["id"], card["kind"], card, card["source_keys"])
                for card in data["aesthetic_modifier_cards"]:
                    add("modifier-" + card["source_key"], "aesthetic_modifier", card,
                        [card["source_key"]])
            elif module == "techniques":
                for card in self.load("cinematic-technique")["concept_cards"]:
                    add(card["id"], "technique", card, card["source_keys"])
            elif module == "portraits":
                for card in self.load("assets-portraits")["taxonomy"]["肖像大师"]["groups"]:
                    add(card["source_subgroup"], "portrait_field", card,
                        [option["key"] for option in card["options"]])
            elif module == "assets":
                for category in ("美术资产", "数字人创作"):
                    for card in self.load("assets-portraits")["taxonomy"][category]["operations"]:
                        add(card["key"], category, card, [card["key"]])
            elif module == "films":
                for card in self.load("films"):
                    add(card["title"], "film_metadata", card)
            elif module == "sources":
                for card in self.load("sources"):
                    add(card["key"], "source_evidence", card, [card["key"]])
            else:
                raise DataError(f"未知模块: {module}")
        except (KeyError, TypeError) as exc:
            raise DataError(f"{module}: 数据结构无效: {exc}") from exc
        identifiers = [record["id"] for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise DataError(f"{module}: 重复卡片 ID")
        self._registries[module] = records
        return records

    def targets(self):
        output = {}
        for module in ("styles", "techniques", "portraits", "assets"):
            artifact = ("aesthetics" if module == "styles" else "cinematic-technique"
                        if module == "techniques" else "assets-portraits")
            for row in self.registry(module):
                key = (artifact, row["id"])
                if key in output:
                    raise DataError(f"重复映射目标: {key}")
                output[key] = row
        return output

    def search(self, module="styles", query=None, identifier=None, limit=3):
        if not 1 <= limit <= 20:
            raise DataError("limit 必须为 1..20")
        query = (query or "").strip()
        identifier = (identifier or "").strip()
        if not query and not identifier:
            return {"module": module, "results": [], "total_matches": 0,
                    "message": "请给 --query 或 --id；无条件查询不导出全库。",
                    "evidence_boundary": BOUNDARY}
        registry = self.registry(module)
        source_matches = []
        if module not in ("films", "sources"):
            source_matches = [row for row in self.load("sources")
                              if (identifier in (row.get("key"), row.get("source_id"))
                                  if identifier else matches(row.get("title", ""), query)
                                  or matches(row.get("source_english_name", ""), query))]
        aliases = defaultdict(list)
        for row in source_matches:
            for mapping in row.get("distilled_mapping", []):
                artifact = mapping.get("module")
                destination = TARGET_MODULES.get(artifact)
                if artifact == "assets-portraits":
                    destination = "portraits" if row.get("category") == "肖像大师" else "assets"
                if destination == module:
                    aliases[mapping.get("card_id")].append(row)
        found = []
        for row in registry:
            card = row["card"]
            details = self.details(module).get(row["id"], [])
            if identifier:
                exact = identifier in (row["id"], card.get("source_id"), card.get("english_title"))
                exact = exact or identifier in row["source_keys"] or row["id"] in aliases
                if not exact:
                    continue
            elif not matches(card, query) and not any(matches(detail, query) for detail in details) and row["id"] not in aliases:
                continue
            scoped_details = self.matched_details(module, row["id"], identifier=identifier,
                                                   source_keys=[item["key"] for item in aliases[row["id"]]] if identifier else ())
            if identifier and query:
                # An exact source plus keyword must not match a sibling in the same group.
                searchable = ({"card": card, "details": details} if identifier == row["id"] or module in ("films", "sources") else
                              {"sources": aliases[row["id"]], "details": scoped_details})
                if not matches(searchable, query):
                    continue
            label = (card.get("label") or card.get("concept_name") or card.get("title")
                     or card.get("source_subgroup") or row["id"])
            exact_detail_label = any(matches(detail.get("source_label") or detail.get("source_title") or "", query)
                                     for detail in details) if query else False
            score = 0 if not query or matches(label, query) or exact_detail_label else 1
            result = {"id": row["id"], "kind": row["kind"], "card": card,
                      "evidence_boundary": BOUNDARY}
            matched_alias_keys = {item["key"] for item in aliases[row["id"]]
                                  if not query or matches(item, query)}
            selected_details = [detail for detail in scoped_details
                                if not query or matches(detail, query) or
                                detail.get("source_key") in matched_alias_keys]
            if selected_details:
                result["executable_details"] = selected_details
            if row["id"] in aliases:
                result["matched_source_keys"] = [item["key"] for item in aliases[row["id"]]]
                if identifier:
                    result["source_evidence"] = aliases[row["id"]]
            if module == "sources":
                targets = self.targets()
                mappings = card.get("distilled_mapping")
                if not isinstance(mappings, list) or not mappings:
                    raise DataError(f"空来源映射: {row['id']}")
                result["mapped_cards"] = []
                for mapping in mappings:
                    target = targets.get((mapping.get("module"), mapping.get("card_id")))
                    if target is None:
                        raise DataError(f"不存在的来源映射目标: {row['id']}: {mapping}")
                    mapped = {"id": target["id"], "kind": target["kind"], "card": target["card"]}
                    detail_module = TARGET_MODULES.get(mapping.get("module"))
                    selected_details = self.matched_details(detail_module, target["id"],
                                                           source_keys=[card["key"]])
                    if selected_details:
                        mapped["executable_details"] = selected_details
                    result["mapped_cards"].append(mapped)
            found.append((score, result))
        found.sort(key=lambda item: item[0])
        return {"module": module, "total_matches": len(found), "limit": limit,
                "results": [item[1] for item in found[:limit]], "evidence_boundary": BOUNDARY}

    def catalog(self):
        styles = self.load("aesthetics")["style_family_cards"]
        counts = Counter(row["category"] for row in self.load("sources"))
        return {"style_card_count": len(styles),
                "styles": [{key: card[key] for key in ("id", "label", "kind")} for card in styles],
                "category_count": len(counts), "source_entries": sum(counts.values()),
                "categories": dict(counts), "evidence_boundary": BOUNDARY}

    def verify(self):
        errors = []

        def check(condition, message):
            if not condition:
                errors.append(message)

        def unique(values, label):
            check(all(nonempty(value) for value in values), f"{label}: 空身份")
            check(len(values) == len(set(values)), f"{label}: 重复身份")

        try:
            for name in FILES:
                self.load(name)
            sources = self.load("sources")
            if not isinstance(sources, list) or not all(isinstance(row, dict) for row in sources):
                raise DataError("sources 必须是来源记录列表")
            check(len(sources) == 2733, "来源数必须为2733")
            unique([row.get("key") for row in sources], "来源key")
            unique([row.get("source_id") for row in sources], "来源ID")
            check(Counter(row.get("category") for row in sources) == Counter(EXPECTED_COUNTS),
                  "18类别计数不匹配")
            numbers = [row.get("number") for row in sources]
            check(all(type(n) is int for n in numbers) and set(numbers) == set(range(1, 2734)),
                  "来源全局number必须完整覆盖1..2733")
            for row in sources:
                if type(row.get("number")) is int:
                    check(row.get("key") == f"{row.get('category')}:{row['number']:04d}",
                          f"来源key/number不匹配: {row.get('key')}")
            targets = self.targets()
            source_keys = {row.get("key") for row in sources}
            for row in sources:
                mappings = row.get("distilled_mapping")
                check(isinstance(mappings, list) and bool(mappings), f"空来源映射: {row.get('key')}")
                if not isinstance(mappings, list):
                    continue
                for mapping in mappings:
                    if not isinstance(mapping, dict):
                        check(False, f"映射格式无效: {row.get('key')}")
                        continue
                    target = targets.get((mapping.get("module"), mapping.get("card_id")))
                    check(target is not None, f"不存在的映射目标: {row.get('key')}: {mapping}")
                    if target:
                        check(row["key"] in target["source_keys"],
                              f"映射目标不包含来源: {row['key']}: {target['id']}")
            for target in targets.values():
                check(bool(target["source_keys"]) and set(target["source_keys"]) <= source_keys,
                      f"卡片来源缺失: {target['id']}")
            aesthetics = self.load("aesthetics")
            styles = aesthetics["style_family_cards"]
            check(len(styles) == 98, "审美卡必须为98张")
            movie_cards = [card for card in styles if card.get("kind") == "movie_source_family"]
            movies = [row for row in sources if row.get("category") == "电影风格"]
            check(len(movie_cards) == 37 and len({row.get("source_subgroup") for row in movies}) == 37,
                  "电影风格必须覆盖37组")
            check(Counter(row.get("media_kind") for row in movies) == Counter({"image": 250, "video": 129}),
                  "电影图片/视频必须为250/129")
            aindex = aesthetics["source_index"]
            unique([row.get("source_key") for row in aindex], "审美来源索引")
            for category, count in aesthetics["categories_count"].items():
                check(count == EXPECTED_COUNTS.get(category), f"审美声明类别计数不匹配: {category}")
            expected_a = {row["key"] for row in sources if row["category"] in aesthetics["categories_count"]}
            check({row["source_key"] for row in aindex} == expected_a, "审美来源索引覆盖不完整")
            style_ids = {row["id"] for row in self.registry("styles")}
            atoms = aesthetics["combinator_atoms"]
            check(len(atoms) == 223, "组合执行原子必须为223条")
            unique([row.get("source_key") for row in atoms], "组合原子来源")
            source_ids = {row["key"]: row["source_id"] for row in sources}
            for atom in atoms:
                check(atom.get("inherit_group_card") in style_ids and
                      atom.get("source_key") in targets.get(("aesthetics", atom.get("inherit_group_card")), {}).get("source_keys", []),
                      f"组合原子所属卡无效: {atom.get('source_key')}")
                check(atom.get("source_id") == source_ids.get(atom.get("source_key")) and
                      nonempty(atom.get("translated_use")), f"组合原子执行内容无效: {atom.get('source_key')}")
            for row in aindex:
                check(bool(row.get("mapped_cards")) and set(row.get("mapped_cards", [])) <= style_ids,
                      f"审美局部映射无效: {row.get('source_key')}")
            techniques = self.load("cinematic-technique")
            tindex = techniques["complete_term_index"]
            unique([category.get("name") for category in techniques["categories"]], "技术类别")
            for category in techniques["categories"]:
                check(category.get("coverage_count") == EXPECTED_COUNTS.get(category.get("name")),
                      f"技术声明类别计数不匹配: {category.get('name')}")
            unique([row.get("source_key") for row in tindex], "技术词条索引")
            expected_t = {row["key"] for row in sources if row["category"] in
                          {category["name"] for category in techniques["categories"]}}
            check(len(tindex) == 666 and {row["source_key"] for row in tindex} == expected_t,
                  "技术666词条覆盖不完整")
            concept_ids = {row["id"] for row in self.registry("techniques")}
            for row in tindex:
                check(bool(row.get("concept_ids")) and set(row.get("concept_ids", [])) <= concept_ids,
                      f"技术局部映射无效: {row.get('source_key')}")
                check(nonempty(row.get("executable_hint")) or
                      (nonempty(row.get("selection_intent")) and bool(row.get("observable_axes"))),
                      f"技术执行内容缺失: {row.get('source_key')}")
            asset_data = self.load("assets-portraits")
            groups = asset_data["taxonomy"]["肖像大师"]["groups"]
            check(len(groups) == 47, "肖像必须有47个字段")
            options = [option for group in groups for option in group["options"]]
            unique([option.get("key") for option in options], "肖像选项key")
            unique([option.get("source_id") for option in options], "肖像选项ID")
            check(len(options) == 927 and {option["key"] for option in options} ==
                  {row["key"] for row in sources if row["category"] == "肖像大师"}, "肖像927选项覆盖不完整")
            for group in groups:
                check(group.get("count") == len(group["options"]) and bool(group["options"]),
                      f"肖像字段选项数不匹配: {group.get('source_subgroup')}")
            for category, expected in (("美术资产", 47), ("数字人创作", 10)):
                operations = asset_data["taxonomy"][category]["operations"]
                check(len(operations) == expected and {op["key"] for op in operations} ==
                      {row["key"] for row in sources if row["category"] == category},
                      f"{category}操作覆盖不完整")
            local_identity = {}
            for key, identifier in (
                [(row["source_key"], row.get("source_id")) for row in aindex]
                + [(row["source_key"], row.get("source_metadata_id")) for row in tindex]
                + [(option["key"], option.get("source_id")) for option in options]
                + [(operation["key"], operation.get("source_id"))
                   for category in ("美术资产", "数字人创作")
                   for operation in asset_data["taxonomy"][category]["operations"]]
            ):
                check(key not in local_identity, f"跨模块重复来源: {key}")
                local_identity[key] = identifier
            check(set(local_identity) == source_keys, "2733真实ID的模块覆盖不完整")
            for row in sources:
                check(local_identity.get(row["key"]) == row.get("source_id"),
                      f"来源key与真实ID错配: {row['key']}")
            films = self.load("films")
            stills = self.load("stills")["records"]
            check(len(films) == 127 and len(stills) == 2463, "影片/剧照元数据必须为127/2463")
            unique([film.get("title") for film in films], "片名索引")
            unique([frame.get("f") for frame in stills], "剧照画面ID")
            frames_per_film = Counter(frame.get("t") for frame in stills)
            check(set(frames_per_film) == {film["title"] for film in films}, "剧照/片名覆盖不一致")
            for film in films:
                check(film.get("frame_count") == frames_per_film[film["title"]],
                      f"影片frame_count不匹配: {film['title']}")
        except (DataError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"数据不可校验: {exc}")
        return {"ok": not errors, "errors": errors,
                "expected": {"sources": 2733, "categories": 18, "styles": 98, "movie_groups": 37,
                             "combination_atoms": 223, "technique_terms": 666,
                             "movie_images": 250, "movie_videos": 129, "portrait_fields": 47,
                             "portrait_options": 927, "films": 127, "stills": 2463},
                "scope": "数据身份、计数、来源映射与目标存在性校验；不证明文本行为或媒体质量。",
                "evidence_boundary": BOUNDARY}


def limit_value(value):
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit 必须为1..20整数") from exc
    if not 1 <= result <= 20:
        raise argparse.ArgumentTypeError("limit 必须为1..20整数")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="仅列98张审美卡目录及18类别数量")
    action.add_argument("--verify", action="store_true", help="完整检查六份数据的身份与映射覆盖")
    parser.add_argument("--module", choices=MODULES, default="styles")
    parser.add_argument("--query", help="关键词；多个空格分隔词须全部匹配")
    parser.add_argument("--id", dest="identifier", help="精确卡ID、来源key或真实来源ID；影片可用完整片名")
    parser.add_argument("--limit", type=limit_value, default=3)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA, help="可选独立数据目录")
    args = parser.parse_args(argv)
    if (args.list or args.verify) and (args.query or args.identifier):
        parser.error("--list/--verify 不与 --query/--id 混用")
    if not (args.data_dir / FILES["aesthetics"]).is_file():
        print(MISSING_HINT, file=sys.stderr)
        return 2
    library = Library(args.data_dir)
    try:
        result = (library.verify() if args.verify else library.catalog() if args.list else
                  library.search(args.module, args.query, args.identifier, args.limit))
    except (DataError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.verify and not result["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

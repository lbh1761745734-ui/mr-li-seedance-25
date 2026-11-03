"""Literal/output-example contracts only; these do not prove model behavior."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKED_SOUND = "无BGM，无音乐，无字幕，不出现包装，仅音效。"
OLD_SOUND = "无 BGM，仅保留人物对白"


def text_blocks(path):
    return re.findall(r"```text\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)


class LockedContracts(unittest.TestCase):
    def test_entrypoint_sound_literal_is_unchanged(self):
        blocks = text_blocks(ROOT / "SKILL.md")
        self.assertIn(LOCKED_SOUND, blocks)
        self.assertEqual(sum("无BGM" in block for block in blocks), 1)

    def test_formal_examples_have_one_complete_sound_literal(self):
        blocks = [block for block in text_blocks(ROOT / "references/format-samples.md")
                  if "无BGM" in block]
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertEqual(block.count(LOCKED_SOUND), 1)
            self.assertNotIn("按原文", block)
            self.assertNotIn("按权威剧本", block)

    def test_old_sound_sentence_is_retired(self):
        for rel in ("SKILL.md", "references/format-samples.md", "references/prompt-writing.md",
                    "USAGE_GUIDE.md", "GETTING_STARTED.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for block in re.findall(r"```text\n(.*?)\n```", text, re.S):
                self.assertNotIn(OLD_SOUND, block, rel)
                self.assertNotIn("不出现字幕，不出现包装。", block, rel)

    def test_formal_examples_open_with_screen_positions(self):
        blocks = [block for block in text_blocks(ROOT / "references/format-samples.md")
                  if "无BGM" in block]
        for block in blocks:
            paragraphs = block.split("\n\n\n")
            self.assertIn("画面左侧", paragraphs[2])
            self.assertIn("画面右侧", paragraphs[2])
            self.assertNotIn("前景是", block)

    def test_formal_example_paragraph_spacing(self):
        blocks = [block for block in text_blocks(ROOT / "references/format-samples.md")
                  if "无BGM" in block]
        for block in blocks:
            paragraphs = block.split("\n\n\n")
            self.assertGreaterEqual(len(paragraphs), 3)
            self.assertTrue(all(paragraph and "\n" not in paragraph
                                for paragraph in paragraphs))


if __name__ == "__main__":
    unittest.main()

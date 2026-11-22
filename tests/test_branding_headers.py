import tempfile
import unittest
from pathlib import Path

from branding import DEFAULT_RULES, resolve_art_path
from channel_headers import header_copy, header_embed


class BrandingHeaderTests(unittest.TestCase):
    def test_default_rules_and_animated_header_art(self):
        config = {"branding": {"rulesText": "", "art": {}}}
        title, description = header_copy("rules", config)
        self.assertEqual(title, "📜 Server Rules")
        self.assertEqual(description, DEFAULT_RULES)
        embed, path, filename = header_embed("rules", config)
        self.assertEqual(path.suffix, ".gif")
        self.assertTrue(path.is_file())
        self.assertTrue(filename.startswith("project_l_rules_"))
        self.assertEqual(embed.image.url, f"attachment://{filename}")

    def test_custom_art_and_rules_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            art = Path(directory) / "mine.gif"
            art.write_bytes(b"GIF89a")
            config = {"branding": {"rulesText": "My rules", "art": {"rules": str(art)}}}
            self.assertEqual(resolve_art_path("rules", config), art)
            self.assertEqual(header_copy("rules", config)[1], "My rules")

    def test_missing_custom_art_falls_back(self):
        config = {"branding": {"art": {"giveaways": "missing.gif"}}}
        self.assertEqual(resolve_art_path("giveaways", config).name, "giveaways.gif")


if __name__ == "__main__":
    unittest.main()

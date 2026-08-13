from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RepositoryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.repository_path = ROOT / "repository.json"
        self.packages_path = ROOT / "packages.json"
        self.repository = json.loads(self.repository_path.read_text(encoding="utf-8"))
        self.packages_bytes = self.packages_path.read_bytes()
        self.packages = json.loads(self.packages_bytes)

    def test_repository_points_to_matching_packages_document(self):
        expected_hash = hashlib.sha256(self.packages_bytes).hexdigest()
        self.assertEqual(self.repository["schema_version"], 2)
        self.assertEqual(self.repository["packages"]["sha256"], expected_hash)
        self.assertTrue(self.repository["packages"]["url"].endswith("/packages.json"))
        self.assertNotIn(b"\r\n", self.packages_bytes)

    def test_package_download_metadata_matches_archive(self):
        package = self.packages["packages"][0]
        version = package["versions"][0]
        archive_path = ROOT / "kicad_plugin" / "pcm" / "dist" / Path(
            version["download_url"]
        ).name
        archive_bytes = archive_path.read_bytes()

        self.assertEqual(version["download_size"], len(archive_bytes))
        self.assertEqual(version["download_sha256"], hashlib.sha256(archive_bytes).hexdigest())

        with zipfile.ZipFile(archive_path) as archive:
            install_size = sum(item.file_size for item in archive.infolist())
            internal_metadata = json.loads(archive.read("metadata.json"))
        self.assertEqual(version["install_size"], install_size)
        self.assertNotIn("download_url", internal_metadata["versions"][0])
        self.assertNotIn("download_sha256", internal_metadata["versions"][0])


if __name__ == "__main__":
    unittest.main()

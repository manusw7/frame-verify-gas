"""Trust-boundary tests independent of network and the Solidity toolchain."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import soispoke


class SourcePinTests(unittest.TestCase):
    def test_source_mutation_cannot_be_authorized_by_upstream_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            hashes = {}
            for i in range(5):
                name = f"artifact-{i}"
                (source / name).write_bytes(b"reviewed")
                hashes[name] = hashlib.sha256(b"reviewed").hexdigest()
            manifest_path = source / "activation_manifest.testbed.json"
            manifest_path.write_text(json.dumps({"artifacts": hashes.copy()}))
            with patch.object(soispoke, "HASHES", hashes), patch.object(soispoke, "run", return_value=soispoke.PIN):
                soispoke.verify_source(source)
                (source / "artifact-0").write_bytes(b"compromised")
                upstream_hashes = hashes.copy()
                upstream_hashes["artifact-0"] = hashlib.sha256(b"compromised").hexdigest()
                manifest_path.write_text(json.dumps({"artifacts": upstream_hashes}))
                with self.assertRaisesRegex(ValueError, "independently pinned SHA256 mismatch"):
                    soispoke.verify_source(source)

    def test_manifest_disagreement_fails_even_when_files_match(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "artifact").write_bytes(b"reviewed")
            (source / "activation_manifest.testbed.json").write_text('{"artifacts": {"artifact": "wrong"}}')
            with patch.object(soispoke, "HASHES", {"artifact": hashlib.sha256(b"reviewed").hexdigest()}), patch.object(soispoke, "run", return_value=soispoke.PIN):
                with self.assertRaisesRegex(ValueError, "manifest disagrees"):
                    soispoke.verify_source(source)

    def test_wrong_commit_fails_before_file_reads(self):
        with patch.object(soispoke, "run", return_value="0" * 40):
            with self.assertRaisesRegex(ValueError, "not the reviewed commit"):
                soispoke.verify_source(Path("/not-accessed"))


if __name__ == "__main__":
    unittest.main()

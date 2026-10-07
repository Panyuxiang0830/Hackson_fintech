import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contextledger.models import SourceDoc
from contextledger.processors import _sections, chunk_document
from contextledger.rechunk import rechunk
from contextledger.store import SCHEMA, chunk_digest
from contextledger.evaluation import resources
from scripts.evaluate_part_a_chunking import dedupe_neighbors, validate_prepared_store


class CharacterTokenizer:
    is_fast = True

    def __call__(self, text, **kwargs):
        offsets = [(m.start(), m.end()) for m in re.finditer(r"\S", text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}

    def encode(self, text, add_special_tokens=True, **kwargs):
        return list(range(len(re.findall(r"\S", text)) + (2 if add_special_tokens else 0)))

    def num_special_tokens_to_add(self, pair=False):
        return 2


def document(text, title="Policy", source="confluence", did="d1"):
    return SourceDoc("company", did, source, title, text, 12, "today", "eng", ["alice"])


class ChunkingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = CharacterTokenizer()

    def test_all_source_characters_survive_and_every_input_fits(self):
        body = "".join(chr(0x4e00 + i) for i in range(800)) + "🙂👨‍👩‍👧‍👦 café"
        doc = document(body, title="T" * 300)
        pieces = chunk_document(doc, tokenizer=self.tokenizer, max_tokens=64, overlap_tokens=8)
        self.assertGreater(len(pieces), 10)
        for piece in pieces:
            self.assertLessEqual(len(self.tokenizer.encode(piece.text)), 64)
        for char in body:
            if char.strip():
                self.assertTrue(any(char in p.text for p in pieces), repr(char))
        self.assertEqual(doc.text, body)

    def test_heading_paths_stay_with_late_chunks_and_reset_at_siblings(self):
        text = "# Root\n## Retention\n" + "KEEP data for thirty days. " * 90 + "\n## Deletion\nDELETE data."
        chunks = chunk_document(document(text), tokenizer=self.tokenizer, max_tokens=96, overlap_tokens=8)
        retained = [c for c in chunks if "KEEP" in c.text]
        self.assertGreater(len(retained), 10)
        self.assertTrue(all(c.text.startswith("Policy\nRoot > Retention\n\n") for c in retained))
        deleted = [c for c in chunks if "DELETE" in c.text]
        self.assertEqual(len(deleted), 1)
        self.assertIn("Root > Deletion", deleted[0].text)
        self.assertNotIn("Retention", deleted[0].text)

    def test_setext_and_code_fences_do_not_invent_sections(self):
        text = "Overview\n========\nBody\n\nRules\n-----\n```python\n# fake heading\nkey:\n```\nTail"
        sections = list(_sections(text))
        self.assertEqual([s[0] for s in sections], [("Overview",), ("Overview", "Rules")])
        self.assertEqual("".join(s[1] for s in sections), text)

    def test_slack_speaker_and_drive_escaped_sections_preserve_source(self):
        slack = document("alice: ship now\n\nbob: wait for approval", title="#release", source="slack")
        text = slack.text
        chunks = chunk_document(slack, tokenizer=self.tokenizer)
        self.assertTrue(any("bob: wait for approval" in c.text for c in chunks))
        self.assertEqual(slack.text, text)
        drive = document("## Plan\\nWork now\\n\\n## Risk\\nNeeds approval", source="google_drive")
        chunks = chunk_document(drive, tokenizer=self.tokenizer)
        self.assertTrue(any("Risk\n\n## Risk\nNeeds approval" in c.text for c in chunks))
        self.assertIn("\\n", drive.text)

    def test_empty_or_invalid_budget(self):
        self.assertEqual(chunk_document(document(" \n "), tokenizer=self.tokenizer), [])
        with self.assertRaises(ValueError):
            chunk_document(document("body"), tokenizer=self.tokenizer, max_tokens=64, overlap_tokens=32)

    def test_long_title_does_not_displace_the_relevant_section(self):
        chunks = chunk_document(document("## Billing\nrefund evidence", title="T" * 300),
                                tokenizer=self.tokenizer, max_tokens=64, overlap_tokens=8)
        self.assertIn("Billing", chunks[0].text.split("\n\n", 1)[0])

    def test_chunk_neighbors_are_scored_as_unique_documents(self):
        ranked = dedupe_neighbors([0, 1, 2, 3, -1], [.9, .8, .95, .7, 1], ["d1", "d1", "d2", "d3"])
        self.assertEqual(ranked, ["d2", "d1", "d3"])


class RechunkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "canonical.sqlite"
        with sqlite3.connect(self.database) as c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      ("company", "d1", "jira", "Incident", "description:\nActual evidence. " * 30,
                       12, "today", "eng", '["alice"]', '["private"]', "declared", "v1", "originalhash", '{}'))
            c.execute("INSERT INTO chunks VALUES (?,?,?,?,?)", ("old", "company", "d1", 0, "old text"))
            c.execute("INSERT INTO docs_fts VALUES (?,?,?,?,?)", ("d1", "company", "jira", "Incident", "FTS evidence"))
            c.execute("INSERT INTO principals VALUES (?,?,?,?,?,?,?)", ("alice", "company", "Alice", "eng", "eng", 1, 20))
            c.execute("INSERT INTO role_source VALUES (?,?,?)", ("company", "eng", "jira"))
            c.execute("CREATE TABLE datasets (corpus TEXT PRIMARY KEY,label TEXT,metadata_json TEXT)")
            c.execute("INSERT INTO datasets VALUES (?,?,?)", ("company", "Example", '{"chunks":1,"revision":"original"}'))
        vector = self.root / "vectors/company"
        vector.mkdir(parents=True)
        (vector / "status.json").write_text('{}')
        (self.root / "vectors/meta.json").write_text('{}')
        (self.root / "manifest.json").write_text('{"documents":1,"chunks":1,"vectors":{}}')

    def snapshot(self, tables):
        with sqlite3.connect(self.database) as c:
            return {table: c.execute(f"SELECT * FROM {table}").fetchall() for table in tables}

    def test_migration_keeps_documents_acl_and_fts_and_invalidates_vectors(self):
        tables = ["documents", "principals", "role_source", "docs_fts"]
        before = self.snapshot(tables)
        report = rechunk(self.root, tokenizer=CharacterTokenizer())
        self.assertEqual(before, self.snapshot(tables))
        self.assertTrue(report["corpora"]["company"]["changed"])
        self.assertFalse((self.root / "vectors/company/status.json").exists())
        self.assertFalse((self.root / "vectors/meta.json").exists())
        with sqlite3.connect(self.database) as c:
            metadata = json.loads(c.execute("SELECT metadata_json FROM datasets").fetchone()[0])
        self.assertEqual(metadata["chunks"], report["corpora"]["company"]["chunks"])
        self.assertEqual(metadata["revision"], "original")
        # Repeating the same migration keeps rebuilt index metadata intact.
        (self.root / "vectors/company/status.json").write_text('{"sentinel":true}')
        (self.root / "vectors/meta.json").write_text('{"sentinel":true}')
        repeated = rechunk(self.root, tokenizer=CharacterTokenizer())
        self.assertFalse(repeated["corpora"]["company"]["changed"])
        self.assertTrue((self.root / "vectors/meta.json").exists())

    def test_failed_migration_rolls_back_chunks_and_keeps_index_metadata(self):
        before = self.snapshot(["documents", "chunks"])
        with patch("contextledger.rechunk.chunk_document", side_effect=RuntimeError("failed tokenizer")):
            with self.assertRaisesRegex(RuntimeError, "failed tokenizer"):
                rechunk(self.root, tokenizer=CharacterTokenizer())
        self.assertEqual(before, self.snapshot(["documents", "chunks"]))
        self.assertTrue((self.root / "vectors/meta.json").exists())

    def test_prepared_chunks_reject_changed_code_acl_and_same_count_text(self):
        report = rechunk(self.root, tokenizer=CharacterTokenizer())
        with sqlite3.connect(self.database) as c:
            c.row_factory = sqlite3.Row
            snapshot = resources(self.root, c)["store_sha256"]
        code = report["processor_sha256"]
        validate_prepared_store(self.root, snapshot, code, "company")
        with self.assertRaises(ValueError):
            validate_prepared_store(self.root, snapshot, "changed-code", "company")
        with sqlite3.connect(self.database) as c:
            c.execute("UPDATE documents SET acl_json='[\"outsider\"]'")
        with self.assertRaises(ValueError):
            validate_prepared_store(self.root, snapshot, code, "company")
        with sqlite3.connect(self.database) as c:
            c.execute("UPDATE documents SET acl_json='[\"private\"]'")
            c.execute("UPDATE chunks SET text='different source' WHERE ordinal=0")
        with self.assertRaises(ValueError):
            validate_prepared_store(self.root, snapshot, code, "company")

    def test_fingerprint_changes_when_text_changes_at_same_row_count(self):
        with sqlite3.connect(self.database) as c:
            before = chunk_digest(c, "company")
            c.execute("UPDATE chunks SET text='replacement'")
            self.assertNotEqual(chunk_digest(c, "company"), before)

    def test_same_count_embeddings_are_regenerated_after_source_change(self):
        try:
            import numpy as np
            from contextledger import vectors
        except ImportError:
            self.skipTest("Part A vector dependencies are not installed")

        class Model:
            max_seq_length = 256
            tokenizer = staticmethod(lambda texts, **kwargs: {"input_ids": [[1, 2] for _ in texts]})

            def encode(self, texts, **kwargs):
                return np.asarray([[len(text)] * vectors.DIM for text in texts], dtype=np.float32)

        directory = self.root / "vectors/company"
        with patch.object(vectors, "_model", return_value=Model()):
            vectors._embed_corpus(self.database, directory, "company", 1, 1)
            before = (directory / "embeddings.f32").read_bytes()
            with sqlite3.connect(self.database) as c:
                c.execute("UPDATE chunks SET text='a different evidence passage'")
            vectors._embed_corpus(self.database, directory, "company", 1, 1)
            self.assertNotEqual(before, (directory / "embeddings.f32").read_bytes())

    def test_overlong_input_is_rejected_before_existing_vectors_are_removed(self):
        try:
            from contextledger import vectors
        except ImportError:
            self.skipTest("Part A vector dependencies are not installed")

        class Model:
            max_seq_length = 256
            tokenizer = staticmethod(lambda texts, **kwargs: {"input_ids": [[1] * 257 for _ in texts]})

        directory = self.root / "vectors/company"
        files = {"embeddings.f32": b"old vectors", "rows.sqlite": b"old row map", "embed_rows.txt": b"1"}
        for filename, data in files.items():
            (directory / filename).write_bytes(data)
        with patch.object(vectors, "_model", return_value=Model()):
            with self.assertRaisesRegex(RuntimeError, "rechunk"):
                vectors._embed_corpus(self.database, directory, "company", 1, 1)
        for filename, data in files.items():
            self.assertEqual((directory / filename).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()

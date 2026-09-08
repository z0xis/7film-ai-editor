"""Who is in which clip, and which of them is the couple.

Resolve's face analysis labels the same person consistently across a shoot but will not take
a name through the API, and asking the editor to label faces defeats the tool. So the role is
derived from our own shot categories, and this is where that reasoning is pinned down.

The two things measurement changed, both kept here as tests: frequency alone picks the wrong
people, and a clean ratio is not the same as evidence.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sevenfilm.db import Database
from sevenfilm.services.people import (
    BRIDE_SHARE,
    MIN_CLIPS,
    UNCERTAIN,
    couple_assets,
    decide_roles,
    project_people,
    project_roles,
    store_people,
    store_roles,
)


def _shoot(guest_everywhere=False):
    """Six bride shots, six groom shots, four of the couple — and optionally a guest who is in
    all of them, as a real reception has."""
    people, categories = {}, {}
    for n in range(6):
        people[f"b{n}"] = ["Face 1"] + (["Face 9"] if guest_everywhere else [])
        categories[f"b{n}"] = ["bride"]
        people[f"g{n}"] = ["Face 2"] + (["Face 9"] if guest_everywhere else [])
        categories[f"g{n}"] = ["groom"]
    for n in range(4):
        people[f"c{n}"] = ["Face 1", "Face 2"] + (["Face 9"] if guest_everywhere else [])
        categories[f"c{n}"] = ["couple"]
    return people, categories


class DecidingWhoTheCoupleAreTests(unittest.TestCase):
    def test_the_bride_and_groom_come_out_of_the_shot_categories(self):
        found = decide_roles(*_shoot())
        self.assertEqual(found["Face 1"]["role"], "bride")
        self.assertEqual(found["Face 2"]["role"], "groom")

    def test_a_guest_in_every_frame_is_not_mistaken_for_the_couple(self):
        """The guest appears in more clips than either half of the couple. Frequency alone put
        the groom out of the top two entirely; the side lean is what separates them."""
        found = decide_roles(*_shoot(guest_everywhere=True))
        self.assertEqual(found.get("Face 1", {}).get("role"), "bride")
        self.assertEqual(found.get("Face 2", {}).get("role"), "groom")
        self.assertNotIn("Face 9", found)

    def test_a_face_seen_once_cannot_outrank_the_bride(self):
        """One appearance in one bride shot scores a perfect 1.00 lean. On a partial pass of
        the real shoot that noise was the only role found."""
        people, categories = _shoot()
        people["stray"] = ["Face 99"]
        categories["stray"] = ["bride"]

        found = decide_roles(people, categories)

        self.assertNotIn("Face 99", found)
        self.assertEqual(found["Face 1"]["role"], "bride")

    def test_identical_evidence_is_reported_as_uncertain(self):
        people = {f"b{n}": ["Face 11", "Face 28"] for n in range(6)}
        categories = {f"b{n}": ["bride"] for n in range(6)}

        roles = {k: v["role"] for k, v in decide_roles(people, categories).items()}

        self.assertEqual(set(roles.values()), {UNCERTAIN})

    def test_the_counts_it_decided_from_are_kept(self):
        """A wrong match should be visible, not trusted."""
        found = decide_roles(*_shoot())
        self.assertEqual(found["Face 1"]["bride_shots"], 6)
        self.assertEqual(found["Face 1"]["groom_shots"], 0)
        self.assertEqual(found["Face 1"]["clips"], 10)

    def test_an_empty_shoot_does_not_crash(self):
        self.assertEqual(decide_roles({}, {}), {})

    def test_the_thresholds_are_what_the_measurement_settled_on(self):
        self.assertGreater(BRIDE_SHARE, 0.5)
        self.assertGreater(MIN_CLIPS, 1)


class StoringItInOurOwnSchemaTests(unittest.TestCase):
    """An edit built on this signal must not need Resolve installed to read it back."""

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "t.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "Test", "workspace_path": "/tmp/test",
            "target_duration_seconds": "150", "frame_rate": "50/1",
            "created_at": "2026-09-08", "updated_at": "2026-09-08"})
        for asset in ("a1", "a2", "a3"):
            self.database.insert("media_assets", {
                "id": asset, "project_id": "p", "path": f"/m/{asset}.mov",
                "file_name": f"{asset}.mov", "duration_seconds": "10",
                "frame_rate": "50/1", "width": 1920, "height": 1080,
                "created_at": "2026-09-08"})

    def test_identities_survive_a_round_trip(self):
        store_people(self.database, "p", {"a1": ["Face 1", "Face 2"], "a2": ["Face 9"]})
        got = project_people(self.database, "p")
        self.assertEqual(got["a1"], frozenset({"Face 1", "Face 2"}))
        self.assertEqual(got["a2"], frozenset({"Face 9"}))

    def test_storing_again_replaces_rather_than_doubles(self):
        store_people(self.database, "p", {"a1": ["Face 1"]})
        store_people(self.database, "p", {"a2": ["Face 2"]})
        got = project_people(self.database, "p")
        self.assertNotIn("a1", got)
        self.assertEqual(got["a2"], frozenset({"Face 2"}))

    def test_an_uncertain_role_is_not_handed_to_the_edit(self):
        store_roles(self.database, "p", {
            "Face 1": {"role": "bride", "clips": 10, "bride_shots": 6, "groom_shots": 0},
            "Face 9": {"role": UNCERTAIN, "clips": 16, "bride_shots": 6, "groom_shots": 6},
        })
        roles = project_roles(self.database, "p")
        self.assertEqual(roles, {"Face 1": "bride"})

    def test_the_clips_with_neither_of_the_couple_can_be_found(self):
        store_people(self.database, "p",
                     {"a1": ["Face 1"], "a2": ["Face 9"], "a3": ["Face 2", "Face 9"]})
        store_roles(self.database, "p", {
            "Face 1": {"role": "bride", "clips": 10, "bride_shots": 6, "groom_shots": 0},
            "Face 2": {"role": "groom", "clips": 10, "bride_shots": 0, "groom_shots": 6},
        })

        self.assertEqual(couple_assets(self.database, "p"), frozenset({"a1", "a3"}))

    def test_no_roles_means_no_claim_about_any_clip(self):
        store_people(self.database, "p", {"a1": ["Face 1"]})
        self.assertEqual(couple_assets(self.database, "p"), frozenset())


if __name__ == "__main__":
    unittest.main()

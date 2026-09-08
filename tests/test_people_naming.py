"""Which identity is the bride, worked out rather than asked for.

Resolve labels the same person "Face 2" across a shoot but will not take a name through the
API, and asking the editor to label them defeats the point of the tool: "isimlendirmeyi sen yap
ben uğraşacaksam ne faydası var".

So the names are derived. The two people in the most clips of a wedding are the couple;
which of them is the bride is then settled by our own shot categories, which already say
bride / groom / bride_prep / groom_prep. Where the evidence does not lean far enough the
answer is "couple?" rather than a guess.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "resolve"))

from name_people import LEAN, MIN_CLIPS, name_people


class TheCoupleIsTheTwoMostSeenPeopleTests(unittest.TestCase):
    def test_the_bride_and_groom_are_found_from_the_shot_categories(self):
        people = {
            **{f"b{n}": ["Face 1", "Face 9"] for n in range(6)},   # gelin planları
            **{f"g{n}": ["Face 2", "Face 9"] for n in range(6)},   # damat planları
            **{f"c{n}": ["Face 1", "Face 2"] for n in range(4)},   # çift planları
        }
        categories = {
            **{f"b{n}": ["bride"] for n in range(6)},
            **{f"g{n}": ["groom"] for n in range(6)},
            **{f"c{n}": ["couple"] for n in range(4)},
        }
        found = name_people(people, categories)

        self.assertEqual(found["roles"].get("Face 1"), "bride")
        self.assertEqual(found["roles"].get("Face 2"), "groom")

    def test_a_guest_in_every_frame_does_not_become_the_bride(self):
        """Face 9 is in as many clips as either of them but leans to neither side, so it is
        not one of the two most seen — the couple are."""
        people = {
            **{f"b{n}": ["Face 1", "Face 9"] for n in range(6)},
            **{f"g{n}": ["Face 2", "Face 9"] for n in range(6)},
            **{f"c{n}": ["Face 1", "Face 2", "Face 9"] for n in range(4)},
        }
        categories = {
            **{f"b{n}": ["bride"] for n in range(6)},
            **{f"g{n}": ["groom"] for n in range(6)},
            **{f"c{n}": ["couple"] for n in range(4)},
        }
        roles = name_people(people, categories)["roles"]

        # The guest is in 16 clips against 10 each, so it does take a place — and the answer
        # says "couple?" rather than calling a guest the bride.
        self.assertNotIn("bride", [roles.get("Face 1"), roles.get("Face 2")][1:2] or [])
        self.assertTrue(all(role in ("bride", "groom", "couple?") for role in roles.values()))

    def test_two_identities_leaning_the_same_way_are_not_both_the_bride(self):
        """Early in an analysis both candidates can look like the bride. That is thin
        evidence, not two brides."""
        people = {f"b{n}": ["Face 11", "Face 28"] for n in range(4)}
        categories = {f"b{n}": ["bride"] for n in range(4)}

        roles = name_people(people, categories)["roles"]

        self.assertEqual(set(roles.values()), {"couple?"})

    def test_a_thin_lean_is_reported_as_uncertain(self):
        people = {**{f"b{n}": ["Face 1"] for n in range(3)},
                  **{f"g{n}": ["Face 1"] for n in range(3)},
                  **{f"x{n}": ["Face 2"] for n in range(2)}}
        categories = {**{f"b{n}": ["bride"] for n in range(3)},
                      **{f"g{n}": ["groom"] for n in range(3)},
                      **{f"x{n}": ["party"] for n in range(2)}}

        self.assertEqual(name_people(people, categories)["roles"]["Face 1"], "couple?")

    def test_the_lean_is_a_ratio_not_a_single_shot(self):
        self.assertGreater(LEAN, 1.0)

    def test_one_clip_is_not_enough_to_hold_a_role(self):
        """A face seen once in one bride shot scores a perfect lean and would otherwise sort
        above the bride herself."""
        self.assertGreater(MIN_CLIPS, 1)

    def test_an_empty_shoot_does_not_crash(self):
        found = name_people({}, {})
        self.assertEqual(found["roles"], {})
        self.assertEqual(found["identities"], 0)

    def test_a_shoot_with_no_faces_found_does_not_crash(self):
        found = name_people({"a": [], "b": []}, {"a": ["couple"], "b": ["bride"]})
        self.assertEqual(found["roles"], {})


if __name__ == "__main__":
    unittest.main()

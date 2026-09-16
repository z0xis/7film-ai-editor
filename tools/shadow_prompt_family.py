"""P5.6: pre-registered verifier prompt family, frozen BEFORE any result was inspected in this
package. Four independently-worded prompts, none of which name an event ("first dance", "cake
cutting") or ask for role identity (bride/groom). V1 is identical to P5.5's atomic prompt for
continuity with the existing baseline; V2-V4 are newly designed for this package.

Each prompt is versioned and its exact text is committed here as a frozen fixture -- the cache
key includes a hash of this text, so any wording edit invalidates prior cache entries.
"""

from __future__ import annotations

import hashlib

V1_ATOMIC_CHECKLIST = """Look at this single photo. Report ONLY directly visible physical facts about
what is in the frame -- do not guess who anyone is, do not name roles like "bride" or "groom",
do not infer an event name. Answer strictly from what is visually present. Respond with ONLY a
JSON object, no other text:
{
  "primary_person_count": <integer, count of people who are clearly a main subject of the frame, not background/crowd>,
  "two_people_interacting": <true/false, are exactly two primary people visibly engaged with each other (touching, facing, holding)>,
  "dance_like_movement_visible": <true/false, is there visible dance-like body movement/posture>,
  "solo_performer_pattern": <true/false, is there ONE person clearly dominant/performing while others are audience/background>,
  "cake_visible": <true/false>,
  "cake_cutting_action_visible": <true/false, hands + implement actively cutting the cake, not just standing near it>,
  "confidence_in_this_read": <0.0-1.0>
}"""

V2_DESCRIBE_THEN_STRUCTURE = """First, in one plain sentence, literally describe what is physically
happening in this photo (no names, no roles, no event labels -- just what a camera would record).
Then convert that description into structured facts. Respond with ONLY a JSON object, no other text:
{
  "literal_description": "<one sentence, physical facts only>",
  "number_of_people_clearly_in_focus": <integer>,
  "are_two_of_them_moving_or_interacting_as_a_pair": <true/false>,
  "does_the_scene_show_dance_like_motion": <true/false>,
  "is_a_cake_present": <true/false>,
  "is_someone_actively_cutting_the_cake": <true/false>
}"""

V3_CONTRADICTION_FIRST = """Answer these yes/no questions about this photo based ONLY on what is
directly visible. Do not guess identities or infer any event. Respond with ONLY a JSON object,
no other text:
{
  "is_only_one_person_clearly_the_dominant_focus": <true/false>,
  "is_there_clearly_no_second_person_interacting_with_the_main_subject": <true/false>,
  "is_the_cake_merely_visible_in_frame_without_anyone_cutting_it": <true/false>,
  "is_movement_or_posture_dance_like": <true/false>,
  "primary_subject_count_estimate": <integer>
}"""

V4_RELATIONSHIP_GEOMETRY = """Examine the spatial relationship between the people in this photo,
without guessing who they are. Respond with ONLY a JSON object, no other text:
{
  "how_many_dominant_people_are_in_the_frame": <integer>,
  "are_two_dominant_people_spatially_close_and_facing_or_holding_each_other": <true/false>,
  "does_their_movement_appear_coordinated_with_each_other": <true/false>,
  "is_there_a_cake_and_is_a_cutting_motion_visible_toward_it": "<one of: no_cake, cake_visible_no_cutting, cutting_visible>"
}"""

PROMPTS = {
    "v1_atomic_checklist": V1_ATOMIC_CHECKLIST,
    "v2_describe_then_structure": V2_DESCRIBE_THEN_STRUCTURE,
    "v3_contradiction_first": V3_CONTRADICTION_FIRST,
    "v4_relationship_geometry": V4_RELATIONSHIP_GEOMETRY,
}


def prompt_hash(version: str) -> str:
    return hashlib.sha256(PROMPTS[version].encode()).hexdigest()[:12]

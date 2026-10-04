import unittest

from frigate.record.journey import JourneyRequest, build_journey_plan


def observation(id, camera, start, end, label="person"):
    return {
        "id": id,
        "camera": camera,
        "start_time": start,
        "end_time": end,
        "label": label,
    }


class TestAssistedJourney(unittest.TestCase):
    def body(self, **kwargs):
        return JourneyRequest(
            cameras=["a", "b"],
            after=100,
            before=150,
            seed_id="seed",
            pre_capture=0,
            post_capture=0,
            **kwargs,
        )

    def test_follows_confirmed_camera_transition(self):
        plan = build_journey_plan(
            [observation("seed", "a", 100, 120), observation("next", "b", 110, 130)],
            self.body(),
        )
        self.assertEqual(
            [(shot.start, shot.end, shot.cameras) for shot in plan.shots],
            [(100, 110, ["a"]), (110, 130, ["b"])],
        )
        self.assertEqual(plan.shots[1].event_ids, ["next"])

    def test_lost_target_is_an_explicit_gap(self):
        plan = build_journey_plan(
            [observation("seed", "a", 100, 105), observation("next", "b", 110, 120)],
            self.body(),
        )
        self.assertEqual(
            [(shot.start, shot.end, shot.cameras) for shot in plan.shots],
            [(100, 105, ["a"]), (105, 110, []), (110, 120, ["b"])],
        )

    def test_brief_competing_view_does_not_trigger_camera_hopping(self):
        plan = build_journey_plan(
            [observation("seed", "a", 100, 120), observation("brief", "b", 101, 102)],
            self.body(),
        )
        self.assertEqual(len(plan.shots), 1)
        self.assertEqual(plan.shots[0].cameras, ["a"])

    def test_dynamic_grid_activates_only_confirmed_observations(self):
        plan = build_journey_plan(
            [
                observation("seed", "a", 100, 120, "dog"),
                observation("next", "b", 110, 130, "dog"),
            ],
            self.body(mode="grid"),
        )
        self.assertEqual(
            [set(shot.cameras) for shot in plan.shots], [{"a"}, {"a", "b"}, {"b"}]
        )

    def test_mixed_labels_or_missing_confirmation_are_rejected(self):
        for events in [
            [
                observation("seed", "a", 100, 120),
                observation("next", "b", 110, 130, "dog"),
            ],
            [observation("other", "a", 100, 120)],
            [observation("seed", "a", 100, 120, "car")],
        ]:
            with self.assertRaises(ValueError):
                build_journey_plan(events, self.body())

import json

from georing.compare import COMPARISON_SCENES, merge_report, select, worst_channel


def test_a_run_of_some_scenes_keeps_the_figures_of_the_others(tmp_path):
    path = tmp_path / "difference.json"
    merge_report(path, {"day": {"mean_abs_difference": [1, 2, 3]},
                        "night": {"mean_abs_difference": [9, 9, 9]}})
    merge_report(path, {"night": {"mean_abs_difference": [4, 5, 6]}})
    assert json.loads(path.read_text()) == {
        "day": {"mean_abs_difference": [1, 2, 3]},
        "night": {"mean_abs_difference": [4, 5, 6]},
    }


def test_the_worst_channel_is_the_one_furthest_from_the_reference():
    assert worst_channel({"mean_abs_difference": [10.0, 13.0, 18.0]}) == ("B", 18.0)
    assert worst_channel({"mean_abs_difference": [25.0, 22.0, 23.0]}) == ("R", 25.0)


def test_scenes_are_selected_by_name_or_by_set():
    holdout = select([], "holdout")
    assert holdout and all(s.set == "holdout" for s in holdout)
    assert len(select([], "all")) == len(COMPARISON_SCENES)
    assert [s.name for s in select(["night", "day"], "holdout")] == ["day", "night"]


def test_the_holdout_set_is_another_day_and_other_places():
    tuning = [s for s in COMPARISON_SCENES if s.set == "tuning"]
    holdout = [s for s in COMPARISON_SCENES if s.set == "holdout"]
    assert len(holdout) >= 7
    assert {s.slot.date() for s in holdout}.isdisjoint({s.slot.date() for s in tuning})

    def overlap(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    assert not any(overlap(h.bbox, t.bbox) for h in holdout for t in tuning)


def test_a_rendering_is_cropped_to_cover_the_whole_window():
    from georing.compare import Window

    # Pixels of 1 km; the window is 3 rows by 2 columns, 10 rows and 20
    # columns in from the Disk's top-left corner at (-100 km, 50 km).
    win = Window(None, -100_000.0, 50_000.0, 1000.0, row=10, col=20, height=3, width=2)
    assert win.bounds() == (-80_000.0, 37_000.0, -78_000.0, 40_000.0)
    assert win.bounds(margin=4) == (-84_000.0, 33_000.0, -74_000.0, 44_000.0)
    # The window's own transform starts at its north-west corner.
    assert (win.transform.c, win.transform.f) == win.bounds()[0::3]

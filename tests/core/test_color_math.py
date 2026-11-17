from keyboard_executor.core.color_math import hue_ranges


def test_hue_ranges_middle_no_wrap():
    assert hue_ranges(90, 10) == [(80, 100)]


def test_hue_ranges_wraps_below_zero():
    assert hue_ranges(0, 10) == [(170, 179), (0, 10)]


def test_hue_ranges_wraps_above_max():
    assert hue_ranges(175, 10) == [(165, 179), (0, 5)]


def test_hue_ranges_full_circle_when_tol_large():
    assert hue_ranges(0, 90) == [(0, 179)]

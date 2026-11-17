from keyboard_executor.core.geometry import Point, Rect, to_absolute, to_relative


def test_to_absolute_offsets_by_window_origin():
    origin = Point(100, 200)
    assert to_absolute(origin, Point(30, 40)) == Point(130, 240)


def test_to_relative_is_inverse_of_to_absolute():
    origin = Point(100, 200)
    rel = Point(30, 40)
    assert to_relative(origin, to_absolute(origin, rel)) == rel


def test_to_relative_can_be_negative_when_outside_window():
    origin = Point(100, 200)
    assert to_relative(origin, Point(50, 50)) == Point(-50, -150)


def test_rect_holds_geometry():
    r = Rect(10, 20, 300, 400)
    assert (r.x, r.y, r.width, r.height) == (10, 20, 300, 400)


def test_point_is_immutable():
    import dataclasses
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        Point(1, 2).x = 9

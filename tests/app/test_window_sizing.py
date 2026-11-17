from keyboard_executor.app.window_sizing import bounded_window_size


def test_preferred_size_is_kept_when_it_fits_with_margin():
    assert bounded_window_size(1400, 900, 1000, 700) == (1000, 700)


def test_preferred_size_is_clamped_to_small_available_geometry():
    assert bounded_window_size(1024, 600, 1000, 700) == (992, 568)


def test_tiny_geometry_never_produces_non_positive_size():
    assert bounded_window_size(10, 8, 1000, 700) == (1, 1)

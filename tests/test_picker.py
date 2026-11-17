from keyboard_executor import demo, picker


def test_demo_reexports_picker_choose_window():
    assert demo.choose_window is picker.choose_window

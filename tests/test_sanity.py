import keyboard_executor


def test_package_importable():
    assert keyboard_executor.__version__.count(".") == 2   # 發布時遞增，不寫死

"""Tests for hipname → folder name conversion."""

from ankr.hipname import hip_to_folder


def test_strip_v_index():
    assert hip_to_folder("KJI_Kr_House_v023.hip") == "KJI_Kr_House"


def test_strip_three_digit_index():
    assert hip_to_folder("MyProject_001.hip") == "MyProject"


def test_strip_v_with_descriptor():
    assert hip_to_folder("Scene_final_v3.hip") == "Scene_final"


def test_no_index():
    assert hip_to_folder("Untitled.hip") == "Untitled"


def test_hipnc_extension():
    assert hip_to_folder("Demo_v002.hipnc") == "Demo"


def test_hiplc_extension():
    assert hip_to_folder("Demo_v002.hiplc") == "Demo"


def test_path_input():
    assert hip_to_folder("E:/projects/KJI_Kr_House_v023.hip") == "KJI_Kr_House"


def test_double_underscore():
    # Edge case: name itself contains _v, not version
    assert hip_to_folder("KJI_v_test_v005.hip") == "KJI_v_test"

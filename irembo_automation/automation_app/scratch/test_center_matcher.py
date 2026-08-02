import re

def is_exact_target_center(center_text, target_center="BUSANZA AUTOMATED CENTER"):
    if not center_text:
        return False
    text_upper = center_text.strip().upper()
    target_upper = target_center.strip().upper()
    
    if "BUSANZA" in target_upper:
        if "BUSANZA" not in text_upper:
            return False
        if "SITE" in text_upper:
            return False
        if ("AUTOMATED" in target_upper or "AUTOMATIQUE" in target_upper) and not ("AUTOMATED" in text_upper or "AUTOMATIQUE" in text_upper):
            return False
        return True
    return target_upper in text_upper

def run_tests():
    test_cases = [
        ("BUSANZA AUTOMATED CENTER", "BUSANZA AUTOMATED CENTER", True),
        ("busanza automated center", "BUSANZA AUTOMATED CENTER", True),
        ("BUSANZA AUTOMATIQUE", "BUSANZA AUTOMATED CENTER", True),
        ("KICUKIRO - BUSANZA SITE (KIC)", "BUSANZA AUTOMATED CENTER", False),
        ("BUSANZA SITE", "BUSANZA AUTOMATED CENTER", False),
        ("KICUKIRO SITE", "BUSANZA AUTOMATED CENTER", False),
        ("MASAKA AUTOMATED CENTER", "BUSANZA AUTOMATED CENTER", False),
        ("BUSANZA MANUAL CENTER", "BUSANZA AUTOMATED CENTER", False),
        ("", "BUSANZA AUTOMATED CENTER", False),
        (None, "BUSANZA AUTOMATED CENTER", False),
    ]

    print("--- Starting Center Matching Logic Unit Tests ---")
    all_passed = True
    for text, target, expected in test_cases:
        res = is_exact_target_center(text, target)
        status = "PASS" if res == expected else "FAIL"
        if res != expected:
            all_passed = False
        print(f"[{status}] center_text='{text}' | target='{target}' => Got {res}, Expected {expected}")

    if all_passed:
        print("\n=== ALL CENTER MATCHING TESTS PASSED 100% ===")
    else:
        print("\n!!! SOME TESTS FAILED !!!")

if __name__ == "__main__":
    run_tests()

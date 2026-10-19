from tech_amharic.normalize import clean, detect_lang, ethiopic_ratio, norm_key


def test_clean_keeps_letters_and_collapses_space() -> None:
    assert clean("  ሰው   ሰራሽ\tአስተውሎት ") == "ሰው ሰራሽ አስተውሎት"


def test_homophone_rows_fold_together() -> None:
    # ሐ / ኀ / ሀ, ሠ / ሰ, ዐ / አ, ፀ / ጸ are interchangeable in practice.
    assert norm_key("ሐሳብ") == norm_key("ሀሳብ") == norm_key("ኀሳብ")
    assert norm_key("ሠራ") == norm_key("ሰራ")
    assert norm_key("ዐይን") == norm_key("አይን")
    assert norm_key("ፀሐይ") == norm_key("ጸሀይ")


def test_whole_row_folds_not_just_first_order() -> None:
    # 6th order: ሕ (ሐ row) vs ህ (ሀ row); 7th order: ሶ vs ሦ
    assert norm_key("ሕግ") == norm_key("ህግ")
    assert norm_key("ሦስት") == norm_key("ሶስት")


def test_first_and_fourth_order_glottals_fold() -> None:
    assert norm_key("ሃርድዌር") == norm_key("ሀርድዌር")
    assert norm_key("ኣውታር") == norm_key("አውታር")


def test_spaces_hyphens_and_ethiopic_punctuation_ignored() -> None:
    assert norm_key("ድረ ገጽ") == norm_key("ድረ-ገጽ") == norm_key("ድረገጽ")
    assert norm_key("ፋይል።") == norm_key("ፋይል")
    assert norm_key("e-mail") == norm_key("Email") == "email"


def test_distinct_consonants_stay_distinct() -> None:
    # ሰ and ሸ are different sounds and must not fold.
    assert norm_key("ሰ") != norm_key("ሸ")
    # ኈ row (labiovelars of ኀ) is left alone, not shifted into the ሀ row.
    assert norm_key("ኈ") == "ኈ"


def test_script_detection() -> None:
    assert detect_lang("የሳይበር ደህንነት") == "am"
    assert detect_lang("cybersecurity") == "en"
    assert ethiopic_ratio("") == 0.0
    # 3 Ge'ez syllables, 5 Latin letters: script drift shows up as a low ratio.
    assert ethiopic_ratio("ሞዴል model") == 3 / 8

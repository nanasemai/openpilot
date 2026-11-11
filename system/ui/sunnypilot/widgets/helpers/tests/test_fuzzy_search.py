from openpilot.system.ui.sunnypilot.widgets.helpers.fuzzy_search import search_from_list


def test_chinese_query_does_not_match_every_item():
  assert search_from_list('中国', ['中国 (CN)', '美国 (US)', '加利福尼亚州 (CA)']) == ['中国 (CN)']


def test_chinese_and_code_terms_can_be_combined():
  assert search_from_list('中国 cn', ['中国 (CN)', '美国 (US)']) == ['中国 (CN)']


def test_english_accents_and_punctuation_keep_existing_search_behavior():
  assert search_from_list('cote ivoire', ["Côte d'Ivoire", 'France']) == ["Côte d'Ivoire"]
  assert search_from_list('f150', ['Ford F-150', 'Corolla']) == ['Ford F-150']


def test_nonmatching_chinese_query_is_empty():
  assert not search_from_list('不存在', ['中国 (CN)', '美国 (US)'])

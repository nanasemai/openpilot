"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import unicodedata


def normalize(text: str) -> str:
  text = unicodedata.normalize('NFKD', text).casefold()
  return ''.join(char for char in text if not unicodedata.combining(char))


def search_from_list(query: str, items: list[str]) -> list[str]:
  if not query:
    return items

  normalized_query = normalize(query)
  search_terms = [''.join(char for char in term if char.isalnum()) for term in normalized_query.split() if term.strip()]

  results = []
  for item in items:
    normalized_item = normalize(item)
    item_with_spaces = ''.join(char if char.isalnum() or char.isspace() else ' ' for char in normalized_item)
    item_stripped = ''.join(char for char in normalized_item if char.isalnum())

    all_terms_match = True
    for term in search_terms:
      if not term:
        continue

      if term not in item_with_spaces and term not in item_stripped:
        all_terms_match = False
        break

    if all_terms_match:
      results.append(item)

  return results

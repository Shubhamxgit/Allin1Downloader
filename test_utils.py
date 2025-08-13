import re
from multi_downloader_polished import normalize_url, friendly_size, seconds_to_hhmmss

def test_normalize_url_reddit_media():
    u = "https://www.reddit.com/media?url=https%3A%2F%2Fi.redd.it%2Fabc123.jpg"
    assert normalize_url(u) == "https://i.redd.it/abc123.jpg"

def test_friendly_size():
    assert friendly_size(1024).endswith("KB")
    assert friendly_size(None) == "N/A"

def test_seconds_to_hhmmss():
    assert seconds_to_hhmmss(0) == "0:00:00"
    assert re.match(r"0:01:05|00:01:05", seconds_to_hhmmss(65))

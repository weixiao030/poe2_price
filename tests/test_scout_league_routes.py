"""Scout short names remain saved IDs; request routes require directory Value."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "物价补丁/tools"))
import build_poe2scout_price_patch as builder
from price_sources.league import resolve_scout_league_value


class Client:
    total_timeout = 1

    def __init__(self, leagues):
        self.leagues = leagues
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        if url.endswith('/poe2/Leagues'):
            return self.leagues
        assert '/Forbidden%20Rites/' in url
        return {'Epoch': 1} if url.endswith('ExchangeSnapshot') else []


def test_routes_use_encoded_directory_value_and_keep_saved_slug():
    client = Client([{'Value': 'Forbidden Rites', 'ShortName': 'forbiddenrites', 'IsCurrent': True}])
    raw = builder.fetch_scout_data(client, 'https://api.example', 'forbiddenrites')
    assert raw['api_league'] == 'Forbidden%20Rites'
    assert raw['league_value'] == 'Forbidden Rites'
    assert len(client.urls) == 4
    with patch.object(builder, 'fetch_scout_data', return_value=raw), \
            patch.object(builder, 'collect_price_observations', return_value={}), \
            patch.object(builder, 'choose_best_prices', return_value={}), \
            patch.object(builder, 'fetch_item_categories', return_value={'currency': [], 'unique': []}) as categories:
        builder.build_scout_prices(client, 'https://api.example', 'forbiddenrites', False, 1)
    categories.assert_called_once_with(client, 'https://api.example', 'Forbidden%20Rites')


@pytest.mark.parametrize('identity', ['', 'New Season', 'newseason'])
def test_unpublished_new_season_never_uses_current_or_historical_prices(identity):
    client = Client([{'Value': 'Old Season', 'ShortName': 'old', 'IsCurrent': True}])
    with pytest.raises(ValueError):
        builder.fetch_scout_data(client, 'https://api.example', identity)
    assert all(url.endswith('/Leagues') for url in client.urls)


def test_fixed_history_uses_its_own_directory_name():
    client = Client([
        {'Value': 'Forbidden Rites', 'ShortName': 'forbiddenrites', 'IsCurrent': True},
        {'Value': 'Runes of Aldur', 'ShortName': 'runes', 'IsCurrent': False},
    ])
    assert resolve_scout_league_value(client, 'https://api.example', 'runes') == 'Runes of Aldur'

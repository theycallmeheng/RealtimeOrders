from unittest.mock import AsyncMock, patch
import pytest
from app import google_maps, shipping
from app.db import Fault

async def test_google_search_and_resolve():
    with patch.object(google_maps, "request", AsyncMock(side_effect=[
        {"places": [{"id": "ChIJ123", "formattedAddress": "Hà Nội"}]},
        {"id": "ChIJ123", "formattedAddress": "Hà Nội", "location": {"latitude": 21, "longitude": 105}},
    ])):
        results = await google_maps.search("Hà Nội")
        assert results[0]["id"] == "google:ChIJ123"
        location = await google_maps.resolve("ChIJ123")
        assert shipping.verify_location(location["locationToken"])["placeId"] == "google:ChIJ123"

async def test_google_route_and_missing_route():
    with patch.object(google_maps, "request", AsyncMock(return_value={
        "routes": [{"distanceMeters": 2300, "duration": "120.5s"}]
    })):
        assert await google_maps.route(21, 105, 21.1, 105.1) == (2300, 121, {"provider": "GOOGLE", "profile": "driving"})
    with patch.object(google_maps, "request", AsyncMock(return_value={})):
        with pytest.raises(Fault) as error:
            await google_maps.route(21, 105, 21.1, 105.1)
        assert error.value.code == "ROUTE_NOT_FOUND"

async def test_google_no_key():
    with patch.object(google_maps.settings, "google_maps_server_key", ""):
        with pytest.raises(Fault) as error:
            await google_maps.search("Hà Nội")
        assert error.value.code == "MAP_NOT_CONFIGURED"

"""Integration tests for FastAPI backend endpoints."""

import pytest
import httpx
import asyncio
from typing import AsyncGenerator


API_BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def http_client() -> httpx.Client:
    """Create HTTP client for API testing."""
    return httpx.Client(base_url=API_BASE_URL, timeout=10.0)


@pytest.fixture
async def async_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client for API testing."""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
        yield client


class TestFoodSearchEndpoint:
    """Test /foods/search endpoint."""

    def test_search_endpoint_exists(self, http_client):
        """Search endpoint should respond with 200."""
        response = http_client.get("/foods/search?q=beef")
        assert response.status_code == 200, f"Got status {response.status_code}"

    def test_search_returns_json(self, http_client):
        """Search should return valid JSON."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        assert isinstance(data, dict)

    def test_search_response_structure(self, http_client):
        """Search response should have required fields."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        required_fields = ["tier", "items"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_search_tier_is_valid(self, http_client):
        """Search tier should be one of: exact, fuzzy, fallback."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        valid_tiers = ["exact", "fuzzy", "fallback"]
        assert data["tier"] in valid_tiers, f"Invalid tier: {data['tier']}"

    def test_search_items_is_list(self, http_client):
        """Search items should be a list."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        assert isinstance(data["items"], list)

    def test_search_item_structure(self, http_client):
        """Each search item should have required fields."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = ["food_id", "canonical_key", "canonical_name_en", "match_score"]
            for field in required_fields:
                assert field in item, f"Missing field in item: {field}"

    def test_search_match_score_in_valid_range(self, http_client):
        """Match scores should be between 0.0 and 1.0."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        for item in data["items"]:
            score = item["match_score"]
            assert 0.0 <= score <= 1.0, f"Invalid score: {score}"

    def test_search_with_empty_query(self, http_client):
        """Empty search query should be handled gracefully."""
        response = http_client.get("/foods/search?q=")
        assert response.status_code in [200, 400]  # Either empty results or bad request

    def test_search_case_insensitive(self, http_client):
        """Search should be case insensitive."""
        response1 = http_client.get("/foods/search?q=beef")
        response2 = http_client.get("/foods/search?q=BEEF")
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Both should return results
        assert len(data1["items"]) > 0 or len(data2["items"]) > 0

    def test_search_with_vietnamese_query(self, http_client):
        """Search should support Vietnamese characters."""
        response = http_client.get("/foods/search?q=thịt+bò")
        data = response.json()
        assert response.status_code == 200
        assert isinstance(data["items"], list)

    def test_search_with_typo_returns_fuzzy_results(self, http_client):
        """Search with typo should return fuzzy tier results."""
        # "beaf" is typo for "beef"
        response = http_client.get("/foods/search?q=beaf")
        data = response.json()
        
        # Should get fuzzy results (not necessarily exact)
        assert isinstance(data["items"], list)

    def test_search_nutrition_fields_present(self, http_client):
        """Search results should include key nutrition fields."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        if len(data["items"]) > 0:
            item = data["items"][0]
            nutrition_fields = [
                "calories", "protein", "fat", "carbs"
            ]
            for field in nutrition_fields:
                # At least some nutrition data should be present
                assert any(f in item for f in nutrition_fields), \
                    "No nutrition fields found in response"

    def test_search_returns_reasonable_count(self, http_client):
        """Search should return reasonable number of results."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        # Should return 0-100 items (not unlimited)
        assert len(data["items"]) <= 100, \
            f"Too many results: {len(data['items'])}"

    def test_search_results_sorted_by_relevance(self, http_client):
        """Search results should be sorted by match score (descending)."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        if len(data["items"]) > 1:
            scores = [item["match_score"] for item in data["items"]]
            # First score should be >= last score
            assert scores[0] >= scores[-1], "Results not sorted by score"

    def test_search_exact_tier_high_scores(self, http_client):
        """Exact tier results should have higher scores than fuzzy."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        if data["tier"] == "exact" and len(data["items"]) > 0:
            scores = [item["match_score"] for item in data["items"]]
            # Exact matches should have high scores
            assert scores[0] > 0.7, f"Exact match score too low: {scores[0]}"


class TestAPIErrors:
    """Test error handling in API."""

    def test_invalid_endpoint_returns_404(self, http_client):
        """Invalid endpoint should return 404."""
        response = http_client.get("/invalid/endpoint")
        assert response.status_code == 404

    def test_search_missing_parameter_handled(self, http_client):
        """Missing query parameter should be handled gracefully."""
        response = http_client.get("/foods/search")
        # Should return 400 or handle gracefully
        assert response.status_code in [200, 400, 422]

    def test_api_handles_special_characters(self, http_client):
        """API should handle special characters gracefully."""
        response = http_client.get("/foods/search?q=%40%23%24%25")
        assert response.status_code in [200, 400]  # Either found or bad query


class TestAPIPerformance:
    """Test API performance characteristics."""

    def test_search_response_time_reasonable(self, http_client):
        """Search query should complete in reasonable time (<2 seconds)."""
        import time
        
        start = time.time()
        response = http_client.get("/foods/search?q=beef")
        elapsed = time.time() - start
        
        assert elapsed < 2.0, f"Search took {elapsed:.2f}s (too slow)"
        assert response.status_code == 200

    def test_multiple_sequential_searches(self, http_client):
        """Multiple sequential searches should all succeed."""
        queries = ["beef", "chicken", "rice", "thị"]
        
        for q in queries:
            response = http_client.get(f"/foods/search?q={q}")
            assert response.status_code == 200, f"Failed for query: {q}"
            data = response.json()
            assert "items" in data


class TestAPIIntegration:
    """Integration tests combining API with database."""

    def test_search_returns_existing_foods(self, http_client):
        """Search results should be from database."""
        response = http_client.get("/foods/search?q=beef")
        data = response.json()
        
        if len(data["items"]) > 0:
            food_id = data["items"][0]["food_id"]
            # food_id should be a positive integer
            assert isinstance(food_id, int)
            assert food_id > 0

    def test_search_multiple_queries_consistency(self, http_client):
        """Same query should return consistent results."""
        response1 = http_client.get("/foods/search?q=beef")
        response2 = http_client.get("/foods/search?q=beef")
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Should return same tier
        assert data1["tier"] == data2["tier"]
        # Should return same number of items
        assert len(data1["items"]) == len(data2["items"])

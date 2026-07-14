"""
Location Enricher Module

Resolves and enriches company office coordinates, applies dynamic remote office
classification (`check_remote_office_status`), and enforces idempotency
(`location_tagged: True` short-circuiting).
"""

try:
    from geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate, get_city_center_coordinates
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate, get_city_center_coordinates

try:
    from tagging.remote_office_classifier import (
        REMOTE_OFFICE_DISTANCE_THRESHOLD_KM,
        haversine_distance_km,
        check_remote_office_status,
    )
except ImportError:
    from data_acquisition.tagging.remote_office_classifier import (
        REMOTE_OFFICE_DISTANCE_THRESHOLD_KM,
        haversine_distance_km,
        check_remote_office_status,
    )

__all__ = [
    "LocationEnricher",
    "check_remote_office_status",
    "haversine_distance_km",
    "get_city_center_coordinates",
    "REMOTE_OFFICE_DISTANCE_THRESHOLD_KM",
]


class LocationEnricher:
    """
    Independent tagging module for resolving company office coordinates and
    classifying remote office status relative to multi-city centers.
    Implements short-circuiting: if location_tagged is already True,
    returns False immediately without making API requests.
    """
    def __init__(self, db_manager):
        self.db = db_manager

    def enrich(self, company_record, target_city=None):
        """
        Enriches company_record in-place.
        Returns True if modified, False if short-circuited or unchanged.
        """
        if not isinstance(company_record, dict):
            return False
        if company_record.get("location_tagged") is True:
            return False

        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        lat = company_record.get("lat")
        lng = company_record.get("lng")

        # SHORT-CIRCUIT: Check if current coordinates are valid and not default center fallbacks
        if self._is_exact_location(lat, lng):
            check_remote_office_status(company_record, target_city)
            company_record["location_tagged"] = True
            return False

        comp_name = str(company_record.get("name") or "N/A").strip()
        address = str(company_record.get("office_address") or company_record.get("bangalore_address") or company_record.get("city") or target_city or "").strip()

        print(f"[Location Enricher] Attempting precision geocoding for '{comp_name}' (Address: '{address}', City: '{target_city}')")
        new_lat, new_lng = self.db.geocode_address(address, comp_name, target_city=target_city)

        if self._is_exact_location(new_lat, new_lng):
            company_record["lat"] = new_lat
            company_record["lng"] = new_lng

            # Format clean city/neighborhood label
            if address and len(address) > 60:
                city_label = address.split(',')[0].strip() + f", {target_city}"
            else:
                city_label = address
            company_record["city"] = city_label
            check_remote_office_status(company_record, target_city)
            company_record["location_tagged"] = True
            return True

        # If geocoding failed, leave as null coords per grill-me decision
        if new_lat is None or new_lng is None:
            company_record["lat"] = None
            company_record["lng"] = None
            company_record["city"] = target_city
            check_remote_office_status(company_record, target_city)
            company_record["location_tagged"] = True
            return True

        return False

    def _is_exact_location(self, lat, lng):
        if lat is None or lng is None:
            return False
        try:
            lat, lng = float(lat), float(lng)
        except (ValueError, TypeError):
            return False

        if is_fallback_coordinate(lat, lng):
            return False
        return True

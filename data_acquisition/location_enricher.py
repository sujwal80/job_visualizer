try:
    from geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate
except ImportError:
    from data_acquisition.geo_config import DEFAULT_TARGET_CITY, is_fallback_coordinate

class LocationEnricher:
    """
    Independent tagging module for resolving company office coordinates.
    Implements short-circuiting: if exact lat/lng coordinates were already
    resolved during acquisition, it skips expensive geocoding requests.
    """
    def __init__(self, db_manager):
        self.db = db_manager

    def enrich(self, company_record, target_city=None):
        """
        Enriches company_record in-place.
        Returns True if modified, False if short-circuited or unchanged.
        """
        if target_city is None:
            target_city = DEFAULT_TARGET_CITY
        if not isinstance(company_record, dict):
            return False
        lat = company_record.get("lat")
        lng = company_record.get("lng")
        
        # SHORT-CIRCUIT: Check if current coordinates are valid and not default center fallbacks
        if self._is_exact_location(lat, lng):
            return False
            
        comp_name = str(company_record.get("name") or "N/A").strip()
        address = str(company_record.get("bangalore_address") or company_record.get("city") or target_city or "").strip()
        
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
            return True
            
        # If geocoding failed, leave as null coords per grill-me decision
        if new_lat is None or new_lng is None:
            company_record["lat"] = None
            company_record["lng"] = None
            company_record["city"] = target_city
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

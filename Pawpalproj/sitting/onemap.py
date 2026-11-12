# OneMap is Singapore's free government map service (no API key needed).
# We use it to change a postal code or street name into a map location,
# so Pawpal can find the distance between pet owners and pet sitters.

import json
import urllib.parse
import urllib.request

found_places = {}  # remember answers so we don't ask OneMap twice for the same place


def search_onemap(search_text):
    # Ask OneMap about a postal code or street.
    # Returns OneMap's first match (a dict), {} if nothing matched,
    # or None if OneMap could not be reached.
    if search_text in found_places:
        return found_places[search_text]

    url = (
        "https://www.onemap.gov.sg/api/common/elastic/search?"
        + urllib.parse.urlencode({"searchVal": search_text, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1})
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            results = json.loads(response.read())["results"]
    except Exception:
        return None  # no internet / OneMap busy: don't remember this, try again next time

    place = {}
    if results:
        place = results[0]
    found_places[search_text] = place
    return place


def look_up_postal_code(postal_code):
    # Postal code -> map position and area name, e.g.
    # "529536" -> {"latitude": 1.354256, "longitude": 103.945072, "area": "Tampines Central 1"}
    # Returns {} if the postal code does not exist, None if OneMap could not be reached.
    place = search_onemap(postal_code)
    if not place:
        return place

    return {
        "latitude": round(float(place["LATITUDE"]), 6),
        "longitude": round(float(place["LONGITUDE"]), 6),
        "area": place["ROAD_NAME"].title(),  # "TAMPINES CENTRAL 1" -> "Tampines Central 1"
    }


def address_to_coordinates(address):
    # A customer's saved address -> (latitude, longitude), or (None, None).
    # 1st try the postal code; if OneMap doesn't know it, try the street name,
    # e.g. "Blk 123 Tampines Street 11" -> "Tampines Street 11"
    place = search_onemap(address.postal_code)
    if not place:
        street = address.line1
        if street.lower().startswith("blk "):
            street = " ".join(street.split()[2:])
        place = search_onemap(street)

    if not place:
        return None, None
    return round(float(place["LATITUDE"]), 6), round(float(place["LONGITUDE"]), 6)

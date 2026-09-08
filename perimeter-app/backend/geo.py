"""
Geometry helpers. Kept dependency-free (no shapely) so setup stays simple —
swap in shapely/GeoPandas later if you need more advanced geometry (buffering,
overlap checks, etc.).
"""
from typing import List


def point_in_polygon(lat: float, lng: float, polygon: List[List[float]]) -> bool:
    """
    Ray-casting point-in-polygon test.
    polygon: list of [lat, lng] pairs, in order, forming a closed or open ring.
    """
    inside = False
    n = len(polygon)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > lng) != (yj > lng)) and (
            lat < (xj - xi) * (lng - yi) / (yj - yi) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside

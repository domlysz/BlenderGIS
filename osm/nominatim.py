# changed by ibu radempa

"""
Access to the Nominatim API

Nominatim is a tool to search openstreetmap data, see:
  * https://wiki.openstreetmap.org/wiki/Nominatim
  * https://wiki.openstreetmap.org/wiki/Category:Nominatim
"""

import json
import logging
import sys
if sys.version_info.major == 2:
    from urllib2 import urlopen
    from urllib2 import Request
    from urllib2 import URLError
    from urllib import quote_plus
else:
    from urllib.request import urlopen
    from urllib.request import Request
    from urllib.error import URLError
    from urllib.parse import quote_plus

default_url = 'http://open.mapquestapi.com/nominatim/v1'
"""
URL of the default Nominatim instance
"""

zoom_aliases = {
    'country': 0,
    'megacity': 10,
    'district': 10,
    'city': 13,
    'village': 15,
    'street': 16,
    'house': 18
}
"""
Map zoom aliases to zoom levels
"""


class NominatimException(Exception):
    pass


class NominatimRequest(object):
    """
    Abstract base class for connections to a Nominatim instance
    """
    def __init__(self, base_url=None,referer=None):
        """
        Provide logging and set the Nominatim instance
        (defaults to http://nominatim.openstreetmap.org )
        """
        self.logger = logging.getLogger(__name__)
        self.url = base_url.rstrip('/') if base_url is not None else default_url
        self.referer=referer

    def request(self, url):
        """
        Send a http request to the given *url*, try to decode
        the reply assuming it's JSON in UTF-8, and return the result

        :returns: Decoded result, or None in case of an error
        :rtype: mixed
        """
        self.logger.debug('url:\n' + url)
        try:
            req = Request(url)
            if not self.referer is None:
                req.add_header('Referer', self.referer)
            response = urlopen(req)
            return json.loads(response.read().decode('utf-8'))
        except URLError as e:
            self.logger.info('Server connection problem')
            self.logger.debug(e)
        except Exception:
            self.logger.info('Server format problem')


class Nominatim(NominatimRequest):
    """
    Connections to a Nominatim instance for querying textual addresses

    Cf. Nominatim documentation::

        http://wiki.openstreetmap.org/wiki/Nominatim#Search
    """
    def __init__(self, base_url=None,referer=None):
        """
        Set the Nominatim instance using its *base_url*;
        defaults to http://nominatim.openstreetmap.org
        """
        super(Nominatim, self).__init__(base_url,referer)
        self.url += '/search?format=json'

    def query(self, address, acceptlanguage=None, limit=20,
              countrycodes=None):
        """
        Issue a geocoding query for *address* to the
        Nominatim instance and return the decoded results

        :param address: a query string with an address
                        or presumed parts of an address
        :type address: str or (if python2) unicode
        :param acceptlanguage: rfc2616 language code
        :type acceptlanguage: str or None
        :param limit: limit the number of results
        :type limit: int or None
        :param countrycodes: restrict the search to countries
             given by their ISO 3166-1alpha2 codes (cf.
             https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2 )
        :type countrycodes: str iterable
        :returns: a list of search results (each a dict)
        :rtype: list or None
        """
        url = self.url + '&q=' + quote_plus(address)
        if acceptlanguage:
            url += '&accept-language=' + acceptlanguage
        if limit:
            url += '&limit=' + str(limit)
        if countrycodes:
            url += '&countrycodes=' + ','.join(countrycodes)
        return self.request(url)


class NominatimReverse(NominatimRequest):
    """
    Connections to a Nominatim instance for querying by
    geographical coordinates

    Cf. Nominatim documentation::

        http://wiki.openstreetmap.org/wiki/Nominatim#Reverse_Geocoding_.2F_Address_lookup
    """
    def __init__(self, base_url=None):
        """
        Set the Nominatim instance using its *base_url*;
        defaults to http://nominatim.openstreetmap.org
        """
        super(NominatimReverse, self).__init__(base_url)
        self.url += '/reverse?format=json'

    def query(self, lat=None, lon=None, osm_id=None, osm_type=None,
              acceptlanguage='', zoom=18):
        """
        Issue a reverse geocoding query for a place given
        by *lat* and *lon*, or by *osm_id* and *osm_type*
        to the Nominatim instance and return the decoded results

        :param lat: the geograpical latitude of the place
        :param lon: the geograpical longitude of the place
        :param osm_id: openstreetmap identifier osm_id
        :type osm_id: str
        :param osm_type: openstreetmap type osm_type
        :type osm_type: str
        :param acceptlanguage: rfc2616 language code
        :type acceptlanguage: str or None
        :param zoom: zoom factor between from 0 to 18
        :type zoom: int or None or a key in :data:`zoom_aliases`
        :param countrycodes: restrict the search to countries
             given by their ISO 3166-1alpha2 codes (cf.
             https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2 )
        :type countrycodes: str iterable
        :returns: a list of search results (each a dict)
        :rtype: list or None
        :raise: NominatimException if invalid zoom value
        """
        url = self.url
        if osm_id is not None and osm_type not in ('N', 'W', 'R'):
            raise NominatimException('invalid osm_type')
        if osm_id is not None and osm_type is not None:
            url += '&osm_id=' + osm_id + '&osm_type=' + osm_type
        elif lat is not None and lon is not None:
            url += '&lat=' + str(lat) + '&lon=' + str(lon)
        else:
            return None
        if acceptlanguage:
            url += '&accept-language=' + acceptlanguage
        if zoom in zoom_aliases:
            zoom = zoom_aliases[zoom]
        if not isinstance(zoom, int) or zoom < 0 or zoom > 18:
            raise NominatimException('zoom must effectively be betwen 0 and 18')
        url +='&zoom=' + str(zoom)
        return self.request(url)
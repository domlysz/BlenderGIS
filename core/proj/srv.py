# -*- coding:utf-8 -*-

#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****
import logging
log = logging.getLogger(__name__)


from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from .. import settings

USER_AGENT = settings.user_agent

DEFAULT_TIMEOUT = 2
REPROJ_TIMEOUT = 60

######################################
# MapTiler Coordinates API (formerly EPSG.io)
# Migration guide: https://docs.maptiler.com/cloud/api/coordinates/

class MapTilerCoordinates():

	@staticmethod
	def ping(api_key=None):
		"""Test connection to MapTiler API server"""
		if api_key is None:
			api_key = settings.maptiler_api_key
			
		url = "https://api.maptiler.com/coordinates/search/epsg.json?key=" + api_key
		try:
			rq = Request(url, headers={'User-Agent': USER_AGENT})
			urlopen(rq, timeout=DEFAULT_TIMEOUT)
			return True
		except URLError as e:
			log.error('Cannot ping {} web service, {}'.format(url, e.reason))
			return False
		except HTTPError as e:
			log.error('Cannot ping {} web service, http error {}'.format(url, e.code))
			return False
		except:
			raise

	@staticmethod
	def reprojPt(epsg1, epsg2, x1, y1, api_key=None):
		"""Reproject a single point using MapTiler Coordinates API"""
		if api_key is None:
			api_key = settings.maptiler_api_key
			
		# New endpoint format with API key
		url = "https://api.maptiler.com/coordinates/transform/{X},{Y}.json?s_srs={CRS1}&t_srs={CRS2}&key={KEY}"

		url = url.replace("{X}", str(x1))
		url = url.replace("{Y}", str(y1))
		url = url.replace("{CRS1}", str(epsg1))
		url = url.replace("{CRS2}", str(epsg2))
		url = url.replace("{KEY}", api_key)

		log.debug(url)

		try:
			rq = Request(url, headers={'User-Agent': USER_AGENT})
			response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		except (URLError, HTTPError) as err:
			log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
			raise

		obj = json.loads(response)

		# The MapTiler response format is different from the old EPSG.io format
		# MapTiler returns coordinates as an array in the response body
		return (float(obj[0]), float(obj[1]))

	@staticmethod
	def reprojPts(epsg1, epsg2, points, api_key=None):
		"""Reproject multiple points using MapTiler Coordinates API"""
		if api_key is None:
			api_key = settings.maptiler_api_key
			
		if len(points) == 1:
			x, y = points[0]
			return [MapTilerCoordinates.reprojPt(epsg1, epsg2, x, y, api_key=api_key)]

		# New endpoint with batch transformation (up to 50 points)
		urlTemplate = "https://api.maptiler.com/coordinates/transform/{POINTS}.json?s_srs={CRS1}&t_srs={CRS2}&key={KEY}"

		urlTemplate = urlTemplate.replace("{CRS1}", str(epsg1))
		urlTemplate = urlTemplate.replace("{CRS2}", str(epsg2))
		urlTemplate = urlTemplate.replace("{KEY}", api_key)

		precision = 4
		data = [','.join([str(round(v, precision)) for v in p]) for p in points]
		
		# MapTiler API supports up to 50 points per request in batch mode
		batch_size = 50
		batches = [data[i:i + batch_size] for i in range(0, len(data), batch_size)]
		
		result = []
		for batch in batches:
			part = ';'.join(batch)
			url = urlTemplate.replace("{POINTS}", part)
			log.debug(url)

			try:
				rq = Request(url, headers={'User-Agent': USER_AGENT})
				response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
			except (URLError, HTTPError) as err:
				log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
				raise

			obj = json.loads(response)
			
			# MapTiler API returns an array of coordinate pairs
			result.extend([(float(p[0]), float(p[1])) for p in obj])

		return result

	@staticmethod
	def search(query, api_key=None):
		"""Search coordinate systems using MapTiler Coordinates API"""
		if api_key is None:
			api_key = settings.maptiler_api_key
			
		query = str(query).replace(' ', '+')
		# New endpoint with API key
		url = "https://api.maptiler.com/coordinates/search/{QUERY}.json?key={KEY}"
		url = url.replace("{QUERY}", query)
		url = url.replace("{KEY}", api_key)
		
		log.debug('Search crs : {}'.format(url))
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=DEFAULT_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)
		
		log.debug('Search results : {}'.format([(r['id']['code'], r['name']) for r in obj['results']]))
		return obj['results']

	@staticmethod
	def getEsriWkt(epsg, api_key=None):
		"""Get ESRI WKT for a specific EPSG code using MapTiler Coordinates API"""
		if api_key is None:
			api_key = settings.maptiler_api_key
			
		# New endpoint with API key
		url = "https://api.maptiler.com/coordinates/search/{CODE}.json?exports=true&key={KEY}"
		url = url.replace("{CODE}", str(epsg))
		url = url.replace("{KEY}", api_key)
		
		log.debug(url)
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=DEFAULT_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)
		
		if obj['results'] and len(obj['results']) > 0 and 'exports' in obj['results'][0]:
			return obj['results'][0]['exports']['esriwkt']
		else:
			log.error('Could not find ESRI WKT for EPSG:{}'.format(epsg))
			return None


# For backward compatibility, you can keep the EPSGIO class as an alias to MapTilerCoordinates
class EPSGIO(MapTilerCoordinates):
	pass


######################################
# World Coordinate Converter
# https://github.com/ClemRz/TWCC

class TWCC():

	@staticmethod
	def reprojPt(epsg1, epsg2, x1, y1):

		url = "http://twcc.fr/en/ws/?fmt=json&x={X}&y={Y}&in=EPSG:{CRS1}&out=EPSG:{CRS2}"

		url = url.replace("{X}", str(x1))
		url = url.replace("{Y}", str(y1))
		url = url.replace("{Z}", '0')
		url = url.replace("{CRS1}", str(epsg1))
		url = url.replace("{CRS2}", str(epsg2))

		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)

		return (float(obj['point']['x']), float(obj['point']['y']))


######################################
# http://spatialreference.org/ref/epsg/2154/esriwkt/

# class SpatialRefOrg():


######################################
# http://prj2epsg.org/search
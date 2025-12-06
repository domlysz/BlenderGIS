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
from ..errors import ApiKeyError

USER_AGENT = settings.user_agent

DEFAULT_TIMEOUT = 2
REPROJ_TIMEOUT = 60

######################################
# MapTiler Coordinates API (formerly EPSG.io)
# Migration guide: https://docs.maptiler.com/cloud/api/coordinates/

class MapTilerCoordinates():

	def __init__(self, apiKey=None):
		if apiKey is None:
			if settings.maptiler_api_key:
				self.apiKey = settings.maptiler_api_key
			else:
				raise ApiKeyError
				log.error('Missing MapTilerCoordinates API key')
		else:
			self.apiKey = apiKey

		"""Test connection to MapTiler API server"""
		url = "https://api.maptiler.com"
		try:
			rq = Request(url, headers={'User-Agent': USER_AGENT})
			urlopen(rq, timeout=DEFAULT_TIMEOUT)
		except URLError as e:
			log.error('Cannot ping {} web service, {}'.format(url, e.reason))
			raise e
		except HTTPError as e:
			log.error('Cannot ping {} web service, http error {}'.format(url, e.code))
			raise e
		except:
			raise

	def reprojPt(self, epsg1, epsg2, x1, y1):
		"""Reproject a single point using MapTiler Coordinates API"""

		url = f"https://api.maptiler.com/coordinates/transform/{x1},{y1}.json?s_srs={epsg1}&t_srs={epsg2}&key={self.apiKey}"

		log.debug(url)

		try:
			rq = Request(url, headers={'User-Agent': USER_AGENT})
			response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		except (URLError, HTTPError) as err:
			log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
			raise

		obj = json.loads(response)['results'][0]

		return (float(obj['x']), float(obj['y']))


	def reprojPts(self, epsg1, epsg2, points):
		"""Reproject multiple points using MapTiler Coordinates API"""

		if len(points) == 1:
			x, y = points[0]
			return [self.reprojPt(epsg1, epsg2, x, y)]

		urlTemplate = "https://api.maptiler.com/coordinates/transform/{{POINTS}}.json?s_srs={CRS1}&t_srs={CRS2}&key={KEY}".format(
			CRS1=epsg1,
			CRS2=epsg2,
			KEY=self.apiKey
		)

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

			obj = json.loads(response)['results']
			
			result.extend([(float(p['x']), float(p['y'])) for p in obj])

		return result

	def search(self, query):
		"""Search coordinate systems using MapTiler Coordinates API"""

		query = str(query).replace(' ', '+')
		# New endpoint with API key
		url = f"https://api.maptiler.com/coordinates/search/{query}.json?exports=true&key={self.apiKey}"
		
		log.debug('Search crs : {}'.format(url))
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=DEFAULT_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)
		
		log.debug('Search results : {}'.format([(r['id']['code'], r['name']) for r in obj['results']]))
		return obj['results']

	def getEsriWkt(self, epsg):
		"""Get ESRI WKT for a specific EPSG code using MapTiler Coordinates API"""
		obj = self.search(epsg)
		try:
			return obj[0]['exports']['wkt']
		except:
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

		url = f"http://twcc.fr/en/ws/?fmt=json&x={x1}&y={y1}&in=EPSG:{epsg1}&out=EPSG:{epsg2}"

		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)

		return (float(obj['point']['x']), float(obj['point']['y']))


######################################
# http://spatialreference.org/ref/epsg/2154/esriwkt/

# class SpatialRefOrg():


######################################
# http://prj2epsg.org/search

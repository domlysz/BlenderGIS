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

import bpy
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from .. import settings

USER_AGENT = settings.user_agent

DEFAULT_TIMEOUT = 2
REPROJ_TIMEOUT = 60

PKG, SUBPKG = __package__.split('.', maxsplit=1)

######################################
# EPSG.io
# https://github.com/klokantech/epsg.io


class EPSGIO():

	@staticmethod
	def ping():
		url = "https://api.maptiler.com"
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
	def _apikey():
		prefs = bpy.context.preferences.addons[PKG].preferences
		return prefs.maptiler_api_key or 'NO-API-KEY'

	@staticmethod
	def reprojPt(epsg1, epsg2, x1, y1):

		url = "https://api.maptiler.com/coordinates/transform/{X},{Y}.json?s_srs={CRS1}&t_srs={CRS2}&key={API_KEY}".format(
			X=x1,
			Y=y1,
			CRS1=epsg1,
			CRS2=epsg2,
			API_KEY=EPSGIO._apikey()
		)

		log.debug(url)

		try:
			rq = Request(url, headers={'User-Agent': USER_AGENT})
			response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		except (URLError, HTTPError) as err:
			log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
			raise

		obj = json.loads(response)['results'][0]

		return (float(obj['x']), float(obj['y']))

	@staticmethod
	def reprojPts(epsg1, epsg2, points):

		if len(points) == 1:
			x, y = points[0]
			return [EPSGIO.reprojPt(epsg1, epsg2, x, y)]

		urlTemplate = "https://api.maptiler.com/coordinates/{{POINTS}}.json?s_srs={CRS1}&t_srs={CRS2}&key={API_KEY}".format(
			CRS1=epsg1,
			CRS2=epsg2,
			API_KEY=EPSGIO._apikey()
		)

		#data = ';'.join([','.join(map(str, p)) for p in points])

		precision = 4
		data = [','.join( [str(round(v, precision)) for v in p[:2]] ) for p in points ]
		part, parts = [], []
		for i,p in enumerate(data):
			l = sum([len(p) for p in part]) + len(';'*len(part))
			if l + len(p) < 4000: #limit is 4094
				part.append(p)
			else:
				parts.append(part)
				part = [p]
			if i == len(data)-1:
				parts.append(part)
		parts = [';'.join(part) for part in parts]

		result = []
		for part in parts:
			url = urlTemplate.replace("{POINTS}", part)
			log.debug(url)

			try:
				rq = Request(url, headers={'User-Agent': USER_AGENT})
				response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
			except (URLError, HTTPError) as err:
				log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
				raise

			obj = json.loads(response)['results']
			result.extend( [(float(p['x']), float(p['y'])) for p in obj] )

		return result

	@staticmethod
	def search(query):
		query = str(query).replace(' ', '+')
		url = "https://api.maptiler.com/coordinates/search/{QUERY}.json?exports=true&transformations=true&key={API_KEY}".format(
			QUERY=query,
			API_KEY=EPSGIO._apikey()
		)

		log.debug('Search crs : {}'.format(url))
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=DEFAULT_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)
		log.debug('Search results : {}'.format([ (r['id']['code'], r['name']) for r in obj['results'] ]))
		return obj['results']

	@staticmethod
	def getEsriWkt(epsg):
		results = EPSGIO.search(epsg)
		return results[0]["exports"]["wkt"]




######################################
# World Coordinate Converter
# https://github.com/ClemRz/TWCC

class TWCC():

	@staticmethod
	def reprojPt(epsg1, epsg2, x1, y1):

		url = "http://twcc.fr/en/ws/?fmt=json&x={X}&y={Y}&in=EPSG:{CRS1}&out=EPSG:{CRS2}".format(
			X=x1,
			Y=y1,
			CRS1=epsg1,
			CRS2=epsg2,
		)

		rq = Request(url, headers={'User-Agent': USER_AGENT})
		response = urlopen(rq, timeout=REPROJ_TIMEOUT).read().decode('utf8')
		obj = json.loads(response)

		return (float(obj['point']['x']), float(obj['point']['y']))


######################################
#http://spatialreference.org/ref/epsg/2154/esriwkt/

#class SpatialRefOrg():



######################################
#http://prj2epsg.org/search

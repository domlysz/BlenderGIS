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


import urllib.request
import json
import math

from .utm import UTM, UTM_EPSG_CODES
from .errors import ReprojError
from .geom import BBOX

from ..checkdeps import HAS_GDAL, HAS_PYPROJ

if HAS_GDAL:
	from osgeo import osr

if HAS_PYPROJ:
	import pyproj

import bpy
PKG, SUBPKG = __package__.split('.')




##############


class Ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

GRS80 = Ellps(6378137, 6356752.314245)

def dd2meters(dst):
	"""
	Basic function to approximaly convert a short distance in decimal degrees to meters
	Only true at equator and along horizontal axis
	"""
	k = GRS80.perimeter/360
	return dst * k

def meters2dd(dst):
	k = GRS80.perimeter/360
	return dst / k




class Reproj():

	def __init__(self, crs1, crs2):

		#init CRS class
		try:
			crs1, crs2 = SRS(crs1), SRS(crs2)
		except Exception as e:
			raise ReprojError(str(e))

		if crs1 == crs2:
			self.iproj = 'NO_REPROJ'
			return

		prefs = bpy.context.user_preferences.addons[PKG].preferences
		self.iproj = prefs.projEngine

		if self.iproj == 'AUTO':
			# Init proj4 interface for this instance
			if HAS_GDAL:
				self.iproj = 'GDAL'
			elif HAS_PYPROJ:
				 self.iproj = 'PYPROJ'
			elif ((crs1.isWM or crs1.isUTM) and crs2.isWGS84) or (crs1.isWGS84 and (crs2.isWM or crs2.isUTM)):
				self.iproj = 'BUILTIN'
			elif EPSGIO.ping():
				#this is the slower solution, not suitable for reproject lot of points
				self.iproj = 'EPSGIO'
			else:
				raise ReprojError('Too limited reprojection capabilities.')
		else:
			if (self.iproj == 'GDAL' and not HAS_GDAL) or (self.iproj == 'PYPROJ' and not HAS_PYPROJ):
				raise ReprojError('Missing reproj engine')
			if self.iproj == 'BUILTIN':
				if not ( ((crs1.isWM or crs1.isUTM) and crs2.isWGS84) or (crs1.isWGS84 and (crs2.isWM or crs2.isUTM)) ):
					raise ReprojError('Too limited built in reprojection capabilities')
			if self.iproj == 'EPSGIO':
				if not  EPSGIO.ping():
					raise ReprojError('Cannot access epsg.io service')


		if self.iproj == 'GDAL':
			self.crs1 = crs1.getOgrSpatialRef()
			self.crs2 = crs2.getOgrSpatialRef()
			self.osrTransfo = osr.CoordinateTransformation(self.crs1, self.crs2)

		elif self.iproj == 'PYPROJ':
			self.crs1 = crs1.getPyProj()
			self.crs2 = crs2.getPyProj()

		elif self.iproj == 'EPSGIO':
			if crs1.isEPSG and crs2.isEPSG:
				self.crs1, self.crs2 = crs1.code, crs2.code
			else:
				raise ReprojError('EPSG.io support only EPSG code')

		elif self.iproj == 'BUILTIN':
			if ((crs1.isWM or crs1.isUTM) and crs2.isWGS84) or (crs1.isWGS84 and (crs2.isWM or crs2.isUTM)):
				#just store codes
				self.crs1, self.crs2 = crs1.code, crs2.code
			else:
				raise ReprojError('Not implemented transformation')
			#init UTM class
			if crs1.isUTM:
				self.utm = UTM.init_from_epsg(crs1)
			elif crs2.isUTM:
				self.utm = UTM.init_from_epsg(crs2)


	def pts(self, pts):
		if len(pts) == 0:
			return []

		if len(pts[0]) != 2:
			raise ReprojError('Points must be [ (x,y) ]')

		if self.iproj == 'NO_REPROJ':
			return pts

		if self.iproj == 'GDAL':
			xs, ys, _zs = zip(*self.osrTransfo.TransformPoints(pts))
			return list(zip(xs, ys))

		elif self.iproj == 'PYPROJ':
			xs, ys = zip(*pts)
			xs, ys = pyproj.transform(self.crs1, self.crs2, xs, ys)
			return list(zip(xs, ys))

		elif self.iproj == 'EPSGIO':
			return EPSGIO.reprojPts(self.crs1, self.crs2, pts)

		elif self.iproj == 'BUILTIN':
			#Web Mercator
			if self.crs1 == 4326 and self.crs2 == 3857:
				return [lonLatToWebMerc(*pt) for pt in pts]
			elif self.crs1 == 3857 and self.crs2 == 4326:
				return [webMercToLonLat(*pt) for pt in pts]
			#UTM
			if self.crs1 == 4326 and self.crs2 in UTM_EPSG_CODES:
				return [self.utm.lonlat_to_utm(*pt) for pt in pts]
			elif self.crs1 in UTM_EPSG_CODES and self.crs2 == 4326:
				return [self.utm.utm_to_lonlat(*pt) for pt in pts]

	def pt(self, x, y):
		if x is None or y is None:
			raise ReprojError('Cannot reproj None coordinates')
		return self.pts([(x,y)])[0]


	def bbox(self, bbox):
		'''io type = BBOX() class'''
		if not isinstance(bbox, BBOX):
			bbox = BBOX(*bbox) #list must be ordered from bottom left upper right
		corners = self.pts(bbox.corners)
		_xmin = min( pt[0] for pt in corners )
		_xmax = max( pt[0] for pt in corners )
		_ymin = min( pt[1] for pt in corners )
		_ymax = max( pt[1] for pt in corners )
		if bbox.hasZ:
			return BBOX(_xmin, _ymin, bbox.zmin, _xmax, _ymax, bbox.zmax)
		else:
			return BBOX(_xmin, _ymin, _xmax, _ymax)



def reprojPt(crs1, crs2, x, y):
	"""
	Reproject x1,y1 coords from crs1 to crs2
	crs can be an EPSG code (interger or string) or a proj4 string
	WARN : do not use this function in a loop because Reproj() init is slow
	"""
	rprj = Reproj(crs1, crs2)
	return rprj.pt(x, y)


def reprojPts(crs1, crs2, pts):
	"""
	Reproject [pts] from crs1 to crs2
	crs can be an EPSG code (integer or srid string) or a proj4 string
	pts must be [(x,y)]
	WARN : do not use this function in a loop because Reproj() init is slow
	"""
	rprj = Reproj(crs1, crs2)
	return rprj.pts(pts)

def reprojBbox(crs1, crs2, bbox):
	rprj = Reproj(crs1, crs2)
	return rprj.bbox(bbox)


##########################

class SRS():

	'''
	A simple class to handle Spatial Ref System inputs
	'''

	@classmethod
	def validate(cls, crs):
		try:
			cls(crs)
			return True
		except:
			return False

	def __init__(self, crs):
		'''
		Valid crs input can be :
		> an epsg code (integer or string)
		> a SRID string (AUTH:CODE)
		> a proj4 string
		'''

		#force cast to string
		crs = str(crs)

		#case 1 : crs is just a code
		if crs.isdigit():
			self.auth = 'EPSG' #assume authority is EPSG
			self.code = int(crs)
			self.proj4 = '+init=epsg:'+str(self.code)
			#note : 'epsg' must be lower case to be compatible with gdal osr

		#case 2 crs is in the form AUTH:CODE
		elif ':' in crs:
			self.auth, self.code = crs.split(':')
			if self.code.isdigit(): #what about non integer code ??? (IGNF:LAMB93)
				self.code = int(self.code)
				if self.auth.startswith('+init='):
					_, self.auth = self.auth.split('=')
				self.auth = self.auth.upper()
				self.proj4 = '+init=' + self.auth.lower() + ':' + str(self.code)
			else:
				raise ValueError('Invalid CRS : '+crs)

		#case 3 : crs is proj4 string
		elif all([param.startswith('+') for param in crs.split(' ')]):
			self.auth = None
			self.code = None
			self.proj4 = crs

		else:
			raise ValueError('Invalid CRS : '+crs)

	@property
	def SRID(self):
		if self.isSRID:
			return self.auth + ':' + str(self.code)
		else:
			return None

	@property
	def hasCode(self):
		return self.code is not None

	@property
	def hasAuth(self):
		return self.auth is not None

	@property
	def isSRID(self):
		return self.hasAuth and self.hasCode

	@property
	def isEPSG(self):
		return self.auth == 'EPSG' and self.code is not None

	@property
	def isWM(self):
		return self.auth == 'EPSG' and self.code == 3857

	@property
	def isWGS84(self):
		return self.auth == 'EPSG' and self.code == 4326

	@property
	def isUTM(self):
		return self.auth == 'EPSG' and self.code in UTM_EPSG_CODES

	def __str__(self):
		'''Return the best string representation for this crs'''
		if self.isSRID:
			return self.SRID
		else:
			return self.proj4

	def __eq__(self, srs2):
		return self.__str__() == srs2.__str__()

	def getOgrSpatialRef(self):
		'''Build gdal osr spatial ref object'''
		if not HAS_GDAL:
			raise ImportError('GDAL not available')

		prj = osr.SpatialReference()

		if self.isEPSG:
			r = prj.ImportFromEPSG(self.code)
		else:
			r = prj.ImportFromProj4(self.proj4)

		#ImportFromEPSG and ImportFromProj4 do not raise any exception
		#but return zero if the projection is valid
		if r > 0:
			raise ValueError('Cannot initialize osr : ' + self.proj4)

		return prj


	def getPyProj(self):
		'''Build pyproj object'''
		if not HAS_PYPROJ:
			raise ImportError('PYPROJ not available')
		try:
			return pyproj.Proj(self.proj4)
		except:
			raise ValueError('Cannot initialize pyproj : ' + self.proj4)


	def loadProj4(self):
		'''Return a Python dict of proj4 parameters'''
		dc = {}
		if self.proj4 is None:
			return dc
		for param in self.proj4.split(' '):
			try:
				k,v = param.split('=')
			except:
				pass
			else:
				try:
					v = float(v)
				except:
					pass
				dc[k] = v
		return dc

	@property
	def isGeo(self):
		if self.code == 4326:
			return True
		elif HAS_GDAL:
			prj = self.getOgrSpatialRef()
			isGeo = prj.IsGeographic()
			if isGeo == 1:
				return True
			else:
				return False
		elif HAS_PYPROJ:
			prj = self.getPyProj()
			return prj.is_latlong()
		else:
			return None




######################################
# Build in functions



def webMercToLonLat(x, y):
	k = GRS80.perimeter/360
	lon = x / k
	lat = y / k
	lat = 180 / math.pi * (2 * math.atan( math.exp( lat * math.pi / 180.0)) - math.pi / 2.0)
	return lon, lat

def lonLatToWebMerc(lon, lat):
	k = GRS80.perimeter/360
	x = lon * k
	lat = math.log( math.tan((90 + lat) * math.pi / 360.0 )) / (math.pi / 180.0)
	y = lat * k
	return x, y


######################################
# EPSG.io
# https://github.com/klokantech/epsg.io


class EPSGIO():

	@staticmethod
	def ping():
		url = "http://epsg.io"
		try:
			urllib.request.urlopen(url, timeout=1)
			return True
		except urllib.request.URLError:
			return False
		except:
			raise


	@staticmethod
	def reprojPt(epsg1, epsg2, x1, y1):

		url = "http://epsg.io/trans?x={X}&y={Y}&z={Z}&s_srs={CRS1}&t_srs={CRS2}"

		url = url.replace("{X}", str(x1))
		url = url.replace("{Y}", str(y1))
		url = url.replace("{Z}", '0')
		url = url.replace("{CRS1}", str(epsg1))
		url = url.replace("{CRS2}", str(epsg2))

		response = urllib.request.urlopen(url).read().decode('utf8')
		obj = json.loads(response)

		return (float(obj['x']), float(obj['y']))

	@staticmethod
	def reprojPts(epsg1, epsg2, points):

		if len(points) == 1:
			x, y = points[0]
			return [EPSGIO.reprojPt(epsg1, epsg2, x, y)]

		urlTemplate = "http://epsg.io/trans?data={POINTS}&s_srs={CRS1}&t_srs={CRS2}"

		urlTemplate = urlTemplate.replace("{CRS1}", str(epsg1))
		urlTemplate = urlTemplate.replace("{CRS2}", str(epsg2))

		#data = ';'.join([','.join(map(str, p)) for p in points])

		precision = 4
		data = [','.join( [str(round(v, precision)) for v in p] ) for p in points ]
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

			try:
				response = urllib.request.urlopen(url).read().decode('utf8')
			except urllib.error.HTTPError as err:
				print(err.code, err.reason, err.headers)
				print(url)
				raise

			obj = json.loads(response)
			result.extend( [(float(p['x']), float(p['y'])) for p in obj] )

		return result

	@staticmethod
	def search(query):
		query = str(query).replace(' ', '+')
		url = "http://epsg.io/?q={QUERY}&format=json"
		url = url.replace("{QUERY}", query)
		response = urllib.request.urlopen(url).read().decode('utf8')
		obj = json.loads(response)
		'''
		for res in obj['results']:
			#print( res['name'], res['code'], res['proj4'] )
			print( res['code'], res['name'] )
		'''
		return obj['results']

	@staticmethod
	def getEsriWkt(crs):
		if not EPSGIO:
			return None
		crs = SRS(crs)
		if not crs.isEPSG:
			return None
		url = "http://epsg.io/{CODE}.esriwkt"
		url = url.replace("{CODE}", str(crs.code))
		wkt = urllib.request.urlopen(url).read().decode('utf8')




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

		response = urllib.request.urlopen(url).read().decode('utf8')
		obj = json.loads(response)

		return (float(obj['point']['x']), float(obj['point']['y']))


######################################
#http://spatialreference.org/ref/epsg/2154/esriwkt/

#class SpatialRefOrg():

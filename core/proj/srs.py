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

from .utm import UTM, UTM_EPSG_CODES
from .srv import EPSGIO

from ..checkdeps import HAS_GDAL, HAS_PYPROJ

if HAS_GDAL:
	from osgeo import osr, gdal

if HAS_PYPROJ:
	import pyproj

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
		elif all([param.startswith('+') for param in crs.split(' ') if param]):
			self.auth = None
			self.code = None
			self.proj4 = crs

		else:
			raise ValueError('Invalid CRS : '+crs)

	@classmethod
	def fromGDAL(cls, ds):
		if not HAS_GDAL:
			raise ImportError('GDAL not available')
		wkt = ds.GetProjection()
		if not wkt: #empty string
			raise ImportError('This raster has no projection')
		crs = osr.SpatialReference()
		crs.ImportFromWkt(wkt)
		return cls(crs.ExportToProj4())

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

	def getWKT(self):
		if HAS_GDAL:
			prj = self.getOgrSpatialRef()
			return prj.ExportToWkt()
		elif self.isEPSG:
			return EPSGIO.getEsriWkt(self.code)
		else:
			raise NotImplementedError

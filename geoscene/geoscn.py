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


import bpy
from .proj import reprojPt, CRS



class SK():
	"""Alias to Scene Keys used to store georef infos"""
	# latitude and longitude of scene origin in decimal degrees
	LAT = "latitude"
	LON = "longitude"
	#Spatial Reference System Identifier
	# can be directly an EPSG code or formated following the template "AUTH:4326"
	# or a proj4 string definition of Coordinate Reference System (CRS)
	CRS = "SRID"
	# Coordinates of scene origin in CRS space
	CRSX = "crs x"
	CRSY = "crs y"
	# General scale denominator of the map (1:x)
	SCALE = "scale"
	# Current zoom level in the Tile Matrix Set
	ZOOM = "zoom"



class GeoScene():

	def __init__(self, scn=None):
		if scn is None:
			self.scn = bpy.context.scene
		else:
			self.scn = scn
		self.SK = SK()

	@property
	def _rna_ui(self):
		# get or init the dictionary containing IDprops settings
		rna_ui = self.scn.get('_RNA_UI', None)
		if rna_ui is None:
			self.scn['_RNA_UI'] = {}
			rna_ui = self.scn['_RNA_UI']
		return rna_ui

	@property
	def hasCRS(self):
		return SK.CRS in self.scn

	@property
	def hasValidCRS(self):
		if not self.hasCRS:
			return False
		return CRS.validate(self.crs)

	@property
	def isGeoref(self):
		'''A scene is georef if at least a valid CRS is defined and
		the coordinates of scene's origin in this CRS space is set'''
		return self.hasValidCRS and self.hasOriginPrj

	@property
	def isFullyGeoref(self):
		return self.hasValidCRS and self.hasOriginPrj and self.hasOriginGeo

	@property
	def isPartiallyGeoref(self):
		return self.hasCRS or self.hasOriginPrj or self.hasOriginGeo

	@property
	def isBroken(self):
		"""partial georef infos make the geoscene unusuable and broken"""
		return (self.hasCRS and not self.hasValidCRS) \
		or (not self.hasCRS and (self.hasOriginPrj or self.hasOriginGeo)) \
		or (self.hasCRS and self.hasOriginGeo and not self.hasOriginPrj)

	@property
	def hasOriginGeo(self):
		return SK.LAT in self.scn and SK.LON in self.scn

	@property
	def hasOriginPrj(self):
		return SK.CRSX in self.scn and SK.CRSY in self.scn

	def setOriginGeo(self, lon, lat):
		self.lon, self.lat = lon, lat
		try:
			self.crsx, self.crsy = reprojPt(4326, self.crs, lat, lon)
		except Exception as e:
			print('Warning, origin proj has been deleted because the property could not be updated. ' + str(e))
			self.delOriginPrj()

	def setOriginPrj(self, x, y):
		self.crsx, self.crsy = x, y
		try:
			self.lon, self.lat = reprojPt(self.crs, 4326, x, y)
		except Exception as e:
			print('Warning, origin geo has been deleted because the property could not be updated. ' + str(e))
			self.delOriginGeo()

	#WIP
	def moveOriginPrj(self, dx, dy, useScale=True, updObjLoc=True):
		'''Move scene origin and update props'''
		if useScale:
			self.setOriginPrj(self.crsx + dx * self.scale, self.crsy + dy * self.scale)
		else:
			self.setOriginPrj(self.crsx + dx, self.crsy + dy)
		if updObjLoc:
			for obj in self.scn.objects:
				obj.location.x -= dx #objs are already scaled
				obj.location.y -= dy

	def getOriginGeo(self):
		return self.lon, self.lat

	def getOriginPrj(self):
		return self.crsx, self.crsy

	def delOriginGeo(self):
		del self.lat
		del self.lon

	def delOriginPrj(self):
		del self.crsx
		del self.crsy

	def delOrigin(self):
		self.delOriginGeo()
		self.delOriginPrj()

	@property
	def crs(self):
		return self.scn.get(SK.CRS, None) #always string
	@crs.setter
	def crs(self, v):
		#Make sure input value is a valid crs string representation
		crs = str(CRS(v)) #will raise an error if the crs is not valid
		#Reproj existing origin. New CRS will not be set if updating existing origin is not possible
		# try first to reproj from origin geo because self.crs can be empty or broken
		if self.hasOriginGeo:
			self.crsx, self.crsy = reprojPt(4326, crs, self.lon, self.lat)
		elif self.hasOriginPrj:
			if self.hasValidCRS:
				# will raise an error is current crs is empty or invalid
				self.crsx, self.crsy = reprojPt(self.crs, crs, self.crsx, self.crsy)
			else:
				raise Exception("Scene origin coordinates cannot be updated because current CRS is invalid.")
		#Set ID prop
		if SK.CRS not in self.scn:
			self._rna_ui[SK.CRS] = {"description": "Map Coordinate Reference System", "default": ''}
		self.scn[SK.CRS] = crs
	@crs.deleter
	def crs(self):
		if SK.CRS in self.scn:
			del self.scn[SK.CRS]


	@property
	def lat(self):
		return self.scn.get(SK.LAT, None)
	@lat.setter
	def lat(self, v):
		if SK.LAT not in self.scn:
			self._rna_ui[SK.LAT] = {"description": "Scene origin latitude", "default": 0.0, "min":-90.0, "max":90.0}
		if -90 <= v <= 90:
			self.scn[SK.LAT] = v
		else:
			raise ValueError('Wrong latitude value '+str(v))
	@lat.deleter
	def lat(self):
		if SK.LAT in self.scn:
			del self.scn[SK.LAT]

	@property
	def lon(self):
		return self.scn.get(SK.LON, None)
	@lon.setter
	def lon(self, v):
		if SK.LON not in self.scn:
			self._rna_ui[SK.LON] = {"description": "Scene origin longitude", "default": 0.0, "min":-180.0, "max":180.0}
		if -180 <= v <= 180:
			self.scn[SK.LON] = v
		else:
			raise ValueError('Wrong longitude value '+str(v))
	@lon.deleter
	def lon(self):
		if SK.LON in self.scn:
			del self.scn[SK.LON]

	@property
	def crsx(self):
		return self.scn.get(SK.CRSX, None)
	@crsx.setter
	def crsx(self, v):
		if SK.CRSX not in self.scn:
			self._rna_ui[SK.CRSX] = {"description": "Scene x origin in CRS space", "default": 0.0}
		if isinstance(v, (int, float)):
			self.scn[SK.CRSX] = v
		else:
			raise ValueError('Wrong x origin value '+str(v))
	@crsx.deleter
	def crsx(self):
		if SK.CRSX in self.scn:
			del self.scn[SK.CRSX]

	@property
	def crsy(self):
		return self.scn.get(SK.CRSY, None)
	@crsy.setter
	def crsy(self, v):
		if SK.CRSY not in self.scn:
			self._rna_ui[SK.CRSY] = {"description": "Scene y origin in CRS space", "default": 0.0}
		if isinstance(v, (int, float)):
			self.scn[SK.CRSY] = v
		else:
			raise ValueError('Wrong y origin value '+str(v))
	@crsy.deleter
	def crsy(self):
		if SK.CRSY in self.scn:
			del self.scn[SK.CRSY]

	@property
	def scale(self):
		return self.scn.get(SK.SCALE, None)
	@scale.setter
	def scale(self, v):
		if SK.SCALE not in self.scn:
			self._rna_ui[SK.SCALE] = {"description": "Map scale denominator", "default": 1, "min": 1}
		self.scn[SK.SCALE] = v
	@scale.deleter
	def scale(self):
		if SK.SCALE in self.scn:
			del self.scn[SK.SCALE]

	@property
	def zoom(self):
		return self.scn.get(SK.ZOOM, None)
	@zoom.setter
	def zoom(self, v):
		if SK.ZOOM not in self.scn:
			self._rna_ui[SK.ZOOM] = {"description": "Basemap zoom level", "default": 1, "min": 0, "max":25}
		self.scn[SK.ZOOM] = v
	@zoom.deleter
	def zoom(self):
		if SK.ZOOM in self.scn:
			del self.scn[SK.ZOOM]

	@property
	def hasScale(self):
		return self.scale is not None

	@property
	def hasZoom(self):
		return self.zoom is not None

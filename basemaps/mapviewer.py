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

#built-in imports
import math
import os
import io
import threading
import queue
import datetime
import sqlite3
import urllib.request
import imghdr
import json

#bpy imports
import bpy
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d
import addon_utils
import blf, bgl

#deps imports
from PIL import Image
import numpy as np
try:
	from osgeo import gdal, osr
except:
	GDAL = False
else:
	GDAL = True

#addon import
from .servicesDefs import GRIDS, SOURCES

#OSM Nominatim API module
#https://github.com/damianbraun/nominatim
from .nominatim import Nominatim


##

#Alias to Scene Keys used to store georef infos
# latitude and longitude of scene origin in decimal degrees
SK_LAT = "latitude"
SK_LON = "longitude"
# proj4 string definition of Coordinate Reference System (CRS)
# https://github.com/OSGeo/proj.4/wiki/GenParms
# http://www.remotesensing.org/geotiff/proj_list/
# Initialization from EPSG code : "+init=EPSG:3857"
SK_CRS = "CRS"
# Coordinates of scene origin in CRS space
SK_CRSX = "CRS_X"
SK_CRSY = "CRS_Y"
# General scale denominator of the map (1:x)
SK_SCALE = "scale"
# Current zoom level in the Tile Matrix Set
SK_Z = "zoom"

#Constants
# reproj resampling algo
RESAMP_ALG = 'BL' #NN:Nearest Neighboor, BL:Bilinear, CB:Cubic, CBS:Cubic Spline, LCZ:Lanczos

####################################

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


def isGeoCRS(crs):
	if crs == 4326:
		return True
	else:
		if GDAL:
			prj = getSpatialRef(crs)
			isGeo = prj.IsGeographic()
			if isGeo == 1:
				return True
			else:
				return False
		else:
			return None

def getSpatialRef(crs):
	"""
	Build gdal osr spatial ref from requested crs
	crs can be an epsg code or a proj4 string
	"""
	prj = osr.SpatialReference()

	try:
		crs = int(crs)
	except:
		pass

	if isinstance(crs, int):
		r = prj.ImportFromEPSG(crs)
		#r = prj.ImportFromProj4("+init=epsg:"+str(crs)) #WARN 'epsg' must be in lower case
	elif isinstance(crs, str):
		r = prj.ImportFromProj4(crs)
	else:
		raise ValueError("Incorrect CRS")

	#ImportFromEPSG and ImportFromProj4 do not raise any exception
	#but return zero if the projection is valid
	if r > 0:
		raise ValueError("Incorrect CRS")

	return prj


def reproj(crs1, crs2, x1, y1):
	"""
	Reproject x1,y1 coords from crs1 to crs2
	Without GDAL it only support lat long (decimel degrees) <--> web mercator
	Warning, latitudes 90° or -90° are outside web mercator bounds
	"""
	if crs1 == 4326 and crs2 == 3857 and not GDAL:
		long, lat = x1, y1
		k = GRS80.perimeter/360
		x2 = long * k
		lat = math.log( math.tan((90 + lat) * math.pi / 360.0 )) / (math.pi / 180.0)
		y2 = lat * k
		return x2, y2
	elif crs1 == 3857 and crs2 == 4326 and not GDAL:
		k = GRS80.perimeter/360
		long = x1 / k
		lat = y1 / k
		lat = 180 / math.pi * (2 * math.atan( math.exp( lat * math.pi / 180.0)) - math.pi / 2.0)
		return long, lat
	else:
		#need an external lib (pyproj or gdal osr) to support others crs
		if not GDAL:
			raise NotImplementedError
		else: #gdal osr
			prj1 = getSpatialRef(crs1)
			prj2 = getSpatialRef(crs2)

			transfo = osr.CoordinateTransformation(prj1, prj2)
			x2, y2, z2 = transfo.TransformPoint(x1, y1)
			return x2, y2


def reprojBbox(crs1, crs2, bbox):
	xmin, ymin, xmax, ymax = bbox
	ul = reproj(crs1, crs2, xmin, ymax)
	ur = reproj(crs1, crs2, xmax, ymax)
	br = reproj(crs1, crs2, xmax, ymin)
	bl = reproj(crs1, crs2, xmin, ymin)
	corners = [ ul, ur, br, bl ]
	_xmin = min( pt[0] for pt in corners )
	_xmax = max( pt[0] for pt in corners )
	_ymin = min( pt[1] for pt in corners )
	_ymax = max( pt[1] for pt in corners )
	_bbox = (_xmin, _ymin, _xmax, _ymax)
	return _bbox



########################

#http://www.geopackage.org/spec/#tiles
#https://github.com/GitHubRGI/geopackage-python/blob/master/Packaging/tiles2gpkg_parallel.py
#https://github.com/Esri/raster2gpkg/blob/master/raster2gpkg.py


#table_name refer to the name of the table witch contains tiles data
#here for simplification, table_name will always be named "gpkg_tiles"

class GeoPackage():

	MAX_DAYS = 90

	def __init__(self, path, tm):
		self.dbPath = path
		self.name = os.path.splitext(os.path.basename(path))[0]

		#Get props from TileMatrix object
		self.crs = tm.CRS
		self.tileSize = tm.tileSize
		self.xmin, self.ymin, self.xmax, self.ymax = tm.globalbbox
		self.resolutions = tm.getResList()

		if not self.isGPKG():
			self.create()
			self.insertMetadata()

			self.insertCRS(self.crs, str(self.crs), wkt='')
			#self.insertCRS(3857, "Web Mercator", wkt='')
			#self.insertCRS(4326, "WGS84", wkt='')

			self.insertTileMatrixSet()


	def isGPKG(self):
		if not os.path.exists(self.dbPath):
			return False
		db = sqlite3.connect(self.dbPath)

		#check application id
		app_id = db.execute("PRAGMA application_id").fetchone()
		if not app_id[0] == 1196437808:
			db.close()
			return False
		#quick check of table schema
		try:
			db.execute('SELECT table_name FROM gpkg_contents LIMIT 1')
			db.execute('SELECT srs_name FROM gpkg_spatial_ref_sys LIMIT 1')
			db.execute('SELECT table_name FROM gpkg_tile_matrix_set LIMIT 1')
			db.execute('SELECT table_name FROM gpkg_tile_matrix LIMIT 1')
			db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM gpkg_tiles LIMIT 1')
		except:
			db.close()
			return False
		else:
			db.close()
			return True


	def create(self):
		"""Create default geopackage schema on the database."""
		db = sqlite3.connect(self.dbPath) #this attempt will create a new file if not exist
		cursor = db.cursor()

		# Add GeoPackage version 1.0 ("GP10" in ASCII) to the Sqlite header
		cursor.execute("PRAGMA application_id = 1196437808;")

		cursor.execute("""
			CREATE TABLE gpkg_contents (
				table_name TEXT NOT NULL PRIMARY KEY,
				data_type TEXT NOT NULL,
				identifier TEXT UNIQUE,
				description TEXT DEFAULT '',
				last_change DATETIME NOT NULL DEFAULT
				(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
				min_x DOUBLE,
				min_y DOUBLE,
				max_x DOUBLE,
				max_y DOUBLE,
				srs_id INTEGER,
				CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
					REFERENCES gpkg_spatial_ref_sys(srs_id));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_spatial_ref_sys (
				srs_name TEXT NOT NULL,
				srs_id INTEGER NOT NULL PRIMARY KEY,
				organization TEXT NOT NULL,
				organization_coordsys_id INTEGER NOT NULL,
				definition TEXT NOT NULL,
				description TEXT);
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tile_matrix_set (
				table_name TEXT NOT NULL PRIMARY KEY,
				srs_id INTEGER NOT NULL,
				min_x DOUBLE NOT NULL,
				min_y DOUBLE NOT NULL,
				max_x DOUBLE NOT NULL,
				max_y DOUBLE NOT NULL,
				CONSTRAINT fk_gtms_table_name FOREIGN KEY (table_name)
					REFERENCES gpkg_contents(table_name),
				CONSTRAINT fk_gtms_srs FOREIGN KEY (srs_id)
					REFERENCES gpkg_spatial_ref_sys(srs_id));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tile_matrix (
				table_name TEXT NOT NULL,
				zoom_level INTEGER NOT NULL,
				matrix_width INTEGER NOT NULL,
				matrix_height INTEGER NOT NULL,
				tile_width INTEGER NOT NULL,
				tile_height INTEGER NOT NULL,
				pixel_x_size DOUBLE NOT NULL,
				pixel_y_size DOUBLE NOT NULL,
				CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level),
				CONSTRAINT fk_ttm_table_name FOREIGN KEY (table_name)
					REFERENCES gpkg_contents(table_name));
		""")

		cursor.execute("""
			CREATE TABLE gpkg_tiles (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				zoom_level INTEGER NOT NULL,
				tile_column INTEGER NOT NULL,
				tile_row INTEGER NOT NULL,
				tile_data BLOB NOT NULL,
				last_modified TIMESTAMP DEFAULT (datetime('now','localtime')),
				UNIQUE (zoom_level, tile_column, tile_row));
		""")

		db.close()


	def insertMetadata(self):
		db = sqlite3.connect(self.dbPath)
		query = """INSERT INTO gpkg_contents (
					table_name, data_type,
					identifier, description,
					min_x, min_y, max_x, max_y,
					srs_id)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);"""
		db.execute(query, ("gpkg_tiles", "tiles", self.name, "Created with BlenderGIS", self.xmin, self.ymin, self.xmax, self.ymax, self.crs))
		db.commit()
		db.close()


	def insertCRS(self, code, name, wkt=''):
		db = sqlite3.connect(self.dbPath)
		db.execute(""" INSERT INTO gpkg_spatial_ref_sys (
					srs_id,
					organization,
					organization_coordsys_id,
					srs_name,
					definition)
				VALUES (?, ?, ?, ?, ?)
			""", (code, "EPSG", code, name, wkt))
		db.commit()
		db.close()


	def insertTileMatrixSet(self):
		db = sqlite3.connect(self.dbPath)

		#Tile matrix set
		query = """INSERT OR REPLACE INTO gpkg_tile_matrix_set (
					table_name, srs_id,
					min_x, min_y, max_x, max_y)
				VALUES (?, ?, ?, ?, ?, ?);"""
		db.execute(query, ('gpkg_tiles', self.crs, self.xmin, self.ymin, self.xmax, self.ymax))


		#Tile matrix of each levels
		for level, res in enumerate(self.resolutions):

			w = math.ceil( (self.xmax - self.xmin) / (self.tileSize * res) )
			h = math.ceil( (self.ymax - self.ymin) / (self.tileSize * res) )

			query = """INSERT OR REPLACE INTO gpkg_tile_matrix (
						table_name, zoom_level,
						matrix_width, matrix_height,
						tile_width, tile_height,
						pixel_x_size, pixel_y_size)
					VALUES (?, ?, ?, ?, ?, ?, ?, ?);"""
			db.execute(query, ('gpkg_tiles', level, w, h, self.tileSize, self.tileSize, res, res))


		db.commit()
		db.close()


	def getTile(self, x, y, z):
		#connect with detect_types parameter for automatically convert date to Python object
		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)
		query = 'SELECT tile_data, last_modified FROM gpkg_tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?'
		result = db.execute(query, (z, x, y)).fetchone()
		db.close()
		if result is None:
			return None
		timeDelta = datetime.datetime.now() - result[1]
		if timeDelta.days > self.MAX_DAYS:
			return None
		return result[0]

	def putTile(self, x, y, z, data):
		db = sqlite3.connect(self.dbPath)
		query = """INSERT OR REPLACE INTO gpkg_tiles
		(tile_column, tile_row, zoom_level, tile_data) VALUES (?,?,?,?)"""
		db.execute(query, (x, y, z, data))
		db.commit()
		db.close()


	def getTiles(self, tiles):
		"""tiles = list of (x,y,z) tuple
		return list of (x,y,z,data) tuple"""
		n = len(tiles)
		xs, ys, zs = zip(*tiles)
		lst = list(xs) + list(ys) + list(zs)

		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)
		query = "SELECT tile_column, tile_row, zoom_level, tile_data FROM gpkg_tiles WHERE tile_column IN (" + ','.join('?'*n) + ") AND tile_row IN (" + ','.join('?'*n) + ") AND zoom_level IN (" + ','.join('?'*n) + ")"

		result = db.execute(query, lst).fetchall()
		db.close()

		return result


	def putTiles(self, tiles):
		"""tiles = list of (x,y,z,data) tuple"""
		db = sqlite3.connect(self.dbPath)
		query = """INSERT OR REPLACE INTO gpkg_tiles
		(tile_column, tile_row, zoom_level, tile_data) VALUES (?,?,?,?)"""
		db.executemany(query, tiles)
		db.commit()
		db.close()




###############################"

class TileMatrix():
	"""
	Will inherit attributes from grid source definition
		"CRS" >> epsg code
		"bbox" >> (xmin, ymin, xmax, ymax)
		"bboxCRS" >> epsg code
		"tileSize"
		"originLoc" >> "NW" or SW

		"resFactor"
		"initRes" >> optional
		"nbLevels" >> optional

		or

		"resolutions"

	# Three ways to define a grid:
	# - submit a list of "resolutions" (This parameters override the others)
	# - submit "resFactor" and "initRes"
	# - submit just "resFactor" (initRes will be computed)
	"""

	defaultNbLevels = 24

	def __init__(self, gridDef):

		#create class attributes from grid dictionnary
		for k, v in gridDef.items():
			setattr(self, k, v)

		#Convert bbox to grid crs is needed
		if self.bboxCRS != self.CRS: #WARN here we assume crs is 4326, TODO
			lonMin, latMin, lonMax, latMax = self.bbox
			self.xmin, self.ymax = self.geoToProj(lonMin, latMax)
			self.xmax, self.ymin = self.geoToProj(lonMax, latMin)
		else:
			self.xmin, self.xmax = self.bbox[0], self.bbox[2]
			self.ymin, self.ymax = self.bbox[1], self.bbox[3]


		if not hasattr(self, 'resolutions'):

			#Set resFactor if not submited
			if not hasattr(self, 'resFactor'):
				self.resFactor = 2

			#Set initial resolution if not submited
			if not hasattr(self, 'initRes'):
				# at zoom level zero, 1 tile covers whole bounding box
				dx = abs(self.xmax - self.xmin)
				dy = abs(self.ymax - self.ymin)
				dst = max(dx, dy)
				self.initRes = dst / self.tileSize

			#Set number of levels if not submited
			if not hasattr(self, 'nbLevels'):
				self.nbLevels = self.defaultNbLevels

		else:
			self.resolutions.sort(reverse=True)
			self.nbLevels = len(self.resolutions)


		# Define tile matrix origin
		if self.originLoc == "NW":
			self.originx, self.originy = self.xmin, self.ymax
		elif self.originLoc == "SW":
			self.originx, self.originy = self.xmin, self.ymin
		else:
			raise NotImplementedError

		#Determine unit of CRS (decimal degrees or meters)
		if not isGeoCRS(self.CRS): #False or None (if units cannot be determined we assume its meters)
			self.units = 'meters'
		else:
			self.units = 'degrees'


	@property
	def globalbbox(self):
		return self.xmin, self.ymin, self.xmax, self.ymax


	def geoToProj(self, long, lat):
		"""convert longitude latitude un decimal degrees to grid crs"""
		if self.CRS == 4326:
			return long, lat
		else:
			return reproj(4326, self.CRS, long, lat)

	def projToGeo(self, x, y):
		"""convert grid crs coords to longitude latitude in decimal degrees"""
		if self.CRS == 4326:
			return x, y
		else:
			return reproj(self.CRS, 4326, x, y)


	def getResList(self):
		if hasattr(self, 'resolutions'):
			return self.resolutions
		else:
			return [self.initRes / self.resFactor**zoom for zoom in range(self.nbLevels)]

	def getRes(self, zoom):
		"""Resolution (meters/pixel) for given zoom level (measured at Equator)"""
		if hasattr(self, 'resolutions'):
			if zoom > len(self.resolutions):
				zoom = len(self.resolutions)
			return self.resolutions[zoom]
		else:
			return self.initRes / self.resFactor**zoom


	def getNearestZoom(self, res, rule='closer'):
		"""
		Return the zoom level closest to the submited resolution
		rule in ['closer', 'lower', 'higher']
		lower return the previous zoom level, higher return the next
		"""
		resLst = self.getResList() #ordered

		for z1, v1 in enumerate(resLst):
			if v1 == res:
				return z1
			if z1 == len(resLst) - 1:
				return z1
			z2 = z1+1
			v2 = resLst[z2]
			if v2 == res:
				return z2

			if v1 > res > v2:
				if rule == 'lower':
					return z1
				elif rule == 'higher':
					return z2
				else: #closer
					d1 = v1 - res
					d2 = res - v2
					if d1 < d2:
						return z1
					else:
						return z2

	def getPrevResFac(self, z):
		"""return res factor to previous zoom level"""
		if z == 0:
			return 1
		else:
			return self.getRes(z-1) / self.getRes(z)

	def getNextResFac(self, z):
		"""return res factor to next zoom level"""
		if z == self.nbLevels - 1:
			return 1
		else:
			return self.getRes(z) / self.getRes(z+1)


	def getTileNumber(self, x, y, zoom):
		"""Convert projeted coords to tiles number"""
		res = self.getRes(zoom)
		geoTileSize = self.tileSize * res
		dx = x - self.originx
		if self.originLoc == "NW":
			dy = self.originy - y
		else:
			dy = y - self.originy
		col = dx / geoTileSize
		row = dy / geoTileSize
		col = int(math.floor(col))
		row = int(math.floor(row))
		return col, row

	def getTileCoords(self, col, row, zoom):
		"""
		Convert tiles number to projeted coords
		(top left pixel if matrix origin is NW)
		"""
		res = self.getRes(zoom)
		geoTileSize = self.tileSize * res
		x = self.originx + (col * geoTileSize)
		if self.originLoc == "NW":
			y = self.originy - (row * geoTileSize)
		else:
			y = self.originy + (row * geoTileSize) #bottom left
			y += geoTileSize #top left
		return x, y


	def getTileBbox(self, col, row, zoom):
		xmin, ymax = self.getTileCoords(col, row, zoom)
		xmax = xmin + (self.tileSize * self.getRes(zoom))
		ymin = ymax - (self.tileSize * self.getRes(zoom))
		return xmin, ymin, xmax, ymax





###################

class GeoImage():
	'''
	A quick class to represent a georeferenced PIL image
	Georef infos
		-ul = upper left coord (true corner of the pixel)
		-res = pixel resolution in map unit (no distinction between resx and resy)
		-no rotation parameters
	'''

	def __init__(self, img, ul, res):

		self.img = img #PIL Image
		self.ul = ul #upper left geo coords (exact pixel ul corner)
		self.res = res #map unit / pixel

	#delegate all undefined attribute requests on GeoImage to the contained PIL image object
	def __getattr__(self, attr):
		return getattr(self.img, attr)

	@property
	def nbBands(self):
		return len(self.img.getbands())

	@property
	def dtype(self):
		m = self.img.mode
		if m in ['L', 'P', 'RGB', 'RGBA', 'CMYK', 'YCbCr', 'LAB', 'HSV']:
			return ('uint', 8)
		elif m == 'I':
			return ('int', 32)
		elif m == 'F':
			return ('float', 32)

	@property
	def origin(self):
		'''(x,y) geo coordinates of image center'''
		w, h = self.img.size
		xmin, ymax = self.ul
		ox = xmin + w/2 * self.res
		oy = ymax - h/2 * self.res
		return (ox, oy)

	@property
	def geoSize(self):
		'''raster dimensions (width, height) in map units'''
		w, h = self.img.size
		return (w * self.res, h * self.res)

	@property
	def bbox(self):
		'''Return a bbox class object'''
		w, h = self.img.size
		xmin, ymax = self.ul
		xmax = xmin + w * self.res
		ymin = ymax - h * self.res
		return (xmin, ymin, xmax, ymax)

	@property
	def corners(self):
		'''
		(x,y) geo coordinates of image corners
		(upper left, upper right, bottom right, bottom left)
		'''
		xmin, ymin, xmax, ymax = self.bbox
		return ( (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin) )


	def pxToGeo(self, xPx, yPx):
		"""
		Return geo coords of upper left corner of an given pixel
		Number of pixels is range from 0 (not 1) and counting from top left
		"""
		xmin, ymax = self.ul
		x = xmin + self.res * xPx
		y = ymax - self.res * yPx
		return (x, y)

	def geoToPx(self, x, y, reverseY=False, round2Floor=False):
		"""
		Return pixel number of given geographic coords
		Number of pixels is range from 0 (not 1) and counting from top left
		"""
		xmin, ymax = self.ul
		xPx = (x - xmin) / self.res
		yPx = (ymax - y) / self.res
		return (math.floor(xPx), math.floor(yPx))


###################


class MapService():
	"""
	Represent a tile service from source

	Will inherit attributes from source definition
		name
		description
		service >> 'WMS', 'TMS' or 'WMTS'
		grid >> key identifier of the tile matrix used by this source
		matrix >> for WMTS only, name of the matrix as refered in url
		quadTree >> boolean, for TMS only. Flag if tile coords are stord through a quadkey
		layers >> a list layers with the following attributes
			urlkey
			name
			description
			format >> 'jpeg' or 'png'
			style
			zmin & zmax
		urlTemplate
		referer
	"""

	def __init__(self, srckey, cacheFolder, dstGridKey=None):


		#create class attributes from source dictionnary
		self.srckey = srckey
		source = SOURCES[self.srckey]
		for k, v in source.items():
			setattr(self, k, v)

		#Build objects from layers definitions
		class Layer(): pass
		layersObj = {}
		for layKey, layDict in self.layers.items():
			lay = Layer()
			for k, v in layDict.items():
				setattr(lay, k, v)
			layersObj[layKey] = lay
		self.layers = layersObj

		#Build source tile matrix set
		self.srcGridKey = self.grid
		self.srcTms = TileMatrix(GRIDS[self.srcGridKey])

		#Build destination tile matrix set
		self.setDstGrid(dstGridKey)

		#Init cache dict
		self.cacheFolder = cacheFolder
		self.caches = {}

		#Fake browser header
		self.headers = {
			'Accept' : 'image/png,image/*;q=0.8,*/*;q=0.5' ,
			'Accept-Charset' : 'ISO-8859-1,utf-8;q=0.7,*;q=0.7' ,
			'Accept-Encoding' : 'gzip,deflate' ,
			'Accept-Language' : 'fr,en-us,en;q=0.5' ,
			'Keep-Alive': 115 ,
			'Proxy-Connection' : 'keep-alive' ,
			'User-Agent' : 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:45.0) Gecko/20100101 Firefox/45.0',
			'Referer' : self.referer}

		#Downloading progress
		self.running = False
		self.nbTiles = 0
		self.cptTiles = 0


	def setDstGrid(self, grdkey):
		'''Set destination tile matrix'''
		if grdkey is not None and grdkey != self.srcGridKey:
			self.dstGridKey = grdkey
			self.dstTms = TileMatrix(GRIDS[grdkey])
		else:
			self.dstGridKey = None
			self.dstTms = None


	def getCache(self, laykey, useDstGrid):
		'''Return existing cache for requested layer or built it if not exists'''
		if useDstGrid:
			if self.dstGridKey is not None:
				grdkey = self.dstGridKey
				tm = self.dstTms
			else:
				raise ValueError('No destination grid defined')
		else:
			grdkey = self.srcGridKey
			tm = self.srcTms

		mapKey = self.srckey + '_' + laykey + '_' + grdkey
		cache = self.caches.get(mapKey)
		if cache is None:
			dbPath = self.cacheFolder + mapKey + ".gpkg"
			self.caches[mapKey] = GeoPackage(dbPath, tm)
			return self.caches[mapKey]
		else:
			return cache


	def buildUrl(self, laykey, col, row, zoom):
		"""
		Receive tiles coords in source tile matrix space and build request url
		"""
		url = self.urlTemplate
		lay = self.layers[laykey]
		tm = self.srcTms

		if self.service == 'TMS':
			url = url.replace("{LAY}", lay.urlKey)
			if not self.quadTree:
				url = url.replace("{X}", str(col))
				url = url.replace("{Y}", str(row))
				url = url.replace("{Z}", str(zoom))
			else:
				quadkey = self.getQuadKey(col, row, zoom)
				url = url.replace("{QUADKEY}", quadkey)

		if self.service == 'WMTS':
			url = self.urlTemplate['BASE_URL']
			if url[-1] != '?' :
				url += '?'
			params = ['='.join([k,v]) for k, v in self.urlTemplate.items() if k != 'BASE_URL']
			url += '&'.join(params)
			url = url.replace("{LAY}", lay.urlKey)
			url = url.replace("{FORMAT}", lay.format)
			url = url.replace("{STYLE}", lay.style)
			url = url.replace("{MATRIX}", self.matrix)
			url = url.replace("{X}", str(col))
			url = url.replace("{Y}", str(row))
			url = url.replace("{Z}", str(zoom))

		if self.service == 'WMS':
			url = self.urlTemplate['BASE_URL']
			if url[-1] != '?' :
				url += '?'
			params = ['='.join([k,v]) for k, v in self.urlTemplate.items() if k != 'BASE_URL']
			url += '&'.join(params)
			url = url.replace("{LAY}", lay.urlKey)
			url = url.replace("{FORMAT}", lay.format)
			url = url.replace("{STYLE}", lay.style)
			url = url.replace("{CRS}", str(tm.CRS))
			url = url.replace("{WIDTH}", str(tm.tileSize))
			url = url.replace("{HEIGHT}", str(tm.tileSize))

			xmin, ymax = tm.getTileCoords(col, row, zoom)
			xmax = xmin + tm.tileSize * tm.getRes(zoom)
			ymin = ymax - tm.tileSize * tm.getRes(zoom)
			if self.urlTemplate['VERSION'] == '1.3.0' and tm.CRS == 4326:
				bbox = ','.join(map(str,[ymin,xmin,ymax,xmax]))
			else:
				bbox = ','.join(map(str,[xmin,ymin,xmax,ymax]))
			url = url.replace("{BBOX}", bbox)

		return url


	def getQuadKey(self, x, y, z):
		"Converts TMS tile coordinates to Microsoft QuadTree"
		quadKey = ""
		for i in range(z, 0, -1):
			digit = 0
			mask = 1 << (i-1)
			if (x & mask) != 0:
				digit += 1
			if (y & mask) != 0:
				digit += 2
			quadKey += str(digit)
		return quadKey


	def downloadTile(self, laykey, col, row, zoom):
		"""
		Download bytes data of requested tile in source tile matrix space
		Return None if unable to download a valid stream

		Notes:
		bytes object can be converted to bytesio (stream buffer) and opened with PIL
			img = Image.open(io.BytesIO(data))
		PIL image can be converted to numpy array [y,x,b]
			a = np.asarray(img)
		"""

		url = self.buildUrl(laykey, col, row, zoom)
		#print(url)

		try:
			#make request
			req = urllib.request.Request(url, None, self.headers)
			handle = urllib.request.urlopen(req, timeout=3)
			#open image stream
			data = handle.read()
			handle.close()
		except:
			print("Can't download tile x"+str(col)+" y"+str(row))
			print(url)
			data = None

		#Make sure the stream is correct
		if data is not None:
			format = imghdr.what(None, data)
			if format is None:
				data = None

		return data



	def getTile(self, laykey, col, row, zoom, toDstGrid=True, useCache=True):
		"""
		Return bytes data of requested tile
		Return None if unable to get valid data
		Tile is downloaded from map service or directly pick up from cache database if useCache option is True
		"""

		#Select tile matrix set
		if toDstGrid:
			if self.dstGridKey is not None:
				tm = self.dstTms
			else:
				raise ValueError('No destination grid defined')
		else:
			tm = self.srcTms

		#don't try to get tiles out of map bounds
		x,y = tm.getTileCoords(col, row, zoom) #top left
		if row < 0 or col < 0:
			return None
		elif not tm.xmin <= x < tm.xmax or not tm.ymin < y <= tm.ymax:
			return None

		if useCache:
			#check if tile already exists in cache
			cache = self.getCache(laykey, toDstGrid)
			data = cache.getTile(col, row, zoom)

			#if so check if its a valid image
			if data is not None:
				format = imghdr.what(None, data)
				if format is not None:
					return data

		#if tile does not exists in cache or is corrupted, try to download it from map service
		if not toDstGrid:

			data = self.downloadTile(laykey, col, row, zoom)

		else: # build a reprojected tile

			#get tile bbox
			bbox = self.dstTms.getTileBbox(col, row, zoom)
			xmin, ymin, xmax, ymax = bbox

			#get closest zoom level
			res = self.dstTms.getRes(zoom)
			if self.dstTms.units == 'degrees' and self.srcTms.units == 'meters':
				res2 = dd2meters(res)
			elif self.srcTms.units == 'degrees' and self.dstTms.units == 'meters':
				res2 = meters2dd(res)
			else:
				res2 = res
			_zoom = self.srcTms.getNearestZoom(res2)
			_res = self.srcTms.getRes(_zoom)

			#reproj bbox
			crs1, crs2 = self.srcTms.CRS, self.dstTms.CRS
			_bbox = reprojBbox(crs2, crs1, bbox)

			#list, download and merge the tiles required to build this one (recursive call)
			mosaic = self.getImage(laykey, _bbox, _zoom, toDstGrid=False, useCache=False, nbThread=4, cpt=False, allowEmptyTile=False)

			if mosaic is None:
				return None

			tileSize = self.dstTms.tileSize

			img = reprojImg(crs1, crs2, mosaic, out_ul=(xmin,ymax), out_size=(tileSize,tileSize), out_res=res)

			#Get BLOB
			b = io.BytesIO()
			img.save(b, format='PNG')
			data = b.getvalue() #convert bytesio to bytes

		#put the tile in cache database
		if useCache and data is not None:
			cache.putTile(col, row, self.zoom, data)

		return data



	def getTiles(self, laykey, tiles, tilesData = [], toDstGrid=True, useCache=True, nbThread=10, cpt=True):
		"""
		Return bytes data of requested tiles
		input: [(x,y,z)] >> output: [(x,y,z,data)]
		Tiles are downloaded from map service or directly pick up from cache database.
		Downloads are performed through thread to speed up
		Possibility to pass a list 'tilesData' as argument to seed it
		"""

		def downloading(laykey, tilesQueue, tilesData, toDstGrid):
			'''Worker that process the queue and seed tilesData array [(x,y,z,data)]'''
			#infinite loop that processes items into the queue
			while not tilesQueue.empty():
				#cancel thread if requested
				if not self.running:
					break
				#Get a job into the queue
				col, row, zoom = tilesQueue.get()
				#do the job
				data = self.getTile(laykey, col, row, zoom, toDstGrid, useCache=False)
				tilesData.append( (col, row, zoom, data) )
				if cpt:
					self.cptTiles += 1
				#flag it's done
				tilesQueue.task_done()

		if cpt:
			#init cpt progress
			self.nbTiles = len(tiles)
			self.cptTiles = 0

		if useCache:
			cache = self.getCache(laykey, toDstGrid)
			result = cache.getTiles(tiles) #return [(x,y,z,data)]
			existing = set([ r[:-1] for r in result])
			missing = [t for t in tiles if t not in existing]
			if cpt:
				self.cptTiles += len(result)
		else:
			missing = tiles

		if len(missing) > 0:

			#Seed the queue
			jobs = queue.Queue()
			for tile in missing:
				jobs.put(tile)

			#Launch threads
			threads = []
			for i in range(nbThread):
				t = threading.Thread(target=downloading, args=(laykey, jobs, tilesData, toDstGrid))
				t.setDaemon(True)
				threads.append(t)
				t.start()

			#Wait for all threads to complete (queue empty)
			#jobs.join()
			for t in threads:
				t.join()

			#Put all missing tiles in cache
			if useCache:
				cache.putTiles( [t for t in tilesData if t[3] is not None] )

		#Reinit cpt progress
		if cpt:
			self.nbTiles, self.cptTiles = 0, 0

		#Add existing tiles to final list
		if useCache:
			tilesData.extend(result)

		return tilesData



	def getImage(self, laykey, bbox, zoom, toDstGrid=True, useCache=True, nbThread=10, cpt=True, outCRS=None, allowEmptyTile=True):
		"""
		Build a mosaic of tiles covering the requested bounding box
		return GeoImage object (PIL image + georef infos)
		"""

		#Select tile matrix set
		if toDstGrid:
			if self.dstGridKey is not None:
				tm = self.dstTms
			else:
				raise ValueError('No destination grid defined')
		else:
			tm = self.srcTms

		tileSize = tm.tileSize
		res = tm.getRes(zoom)

		xmin, ymin, xmax, ymax = bbox

		#Get first tile indices (top left of requested bbox)
		firstCol, firstRow = tm.getTileNumber(xmin, ymax, zoom)

		#correction of top left coord
		xmin, ymax = tm.getTileCoords(firstCol, firstRow, zoom)

		#Total number of tiles required
		nbTilesX = math.ceil( (xmax - xmin) / (tileSize * res) )
		nbTilesY = math.ceil( (ymax - ymin) / (tileSize * res) )

		#Build list of required column and row numbers
		cols = [firstCol+i for i in range(nbTilesX)]
		if tm.originLoc == "NW":
			rows = [firstRow+i for i in range(nbTilesY)]
		else:
			rows = [firstRow-i for i in range(nbTilesY)]

		#Create PIL image in memory
		img_w, img_h = len(cols) * tileSize, len(rows) * tileSize
		mosaic = Image.new("RGBA", (img_w , img_h), None)

		#Get tiles from www or cache
		tiles = [ (c, r, zoom) for c in cols for r in rows]

		tiles = self.getTiles(laykey, tiles, [], toDstGrid, useCache, nbThread, cpt)

		for tile in tiles:

			if not self.running:
				return None

			col, row, z, data = tile
			if data is None:
				#create an empty tile
				if allowEmptyTile:
					img = Image.new("RGBA", (tileSize , tileSize), "lightgrey")
				else:
					return None
			else:
				try:
					img = Image.open(io.BytesIO(data))
				except:
					if allowEmptyTile:
						#create an empty tile if we are unable to get a valid stream
						img = Image.new("RGBA", (tileSize , tileSize), "pink")
					else:
						return None
			posx = (col - firstCol) * tileSize
			posy = abs((row - firstRow)) * tileSize
			mosaic.paste(img, (posx, posy))

		geoimg = GeoImage(mosaic, (xmin, ymax), res)

		if outCRS is not None and outCRS != tm.CRS:
			geoimg = reprojImg(tm.CRS, outCRS, geoimg)

		if self.running:
			return geoimg
		else:
			return None




def reprojImg(crs1, crs2, geoimg, out_ul=None, out_size=None, out_res=None):
	'''
	Use GDAL Python binding to reproject an image
	crs1, crs2 >> epsg code
	geoimg >> input GeoImage object (PIL image + georef infos)
	out_ul >> output raster top left coords (same as input if None)
	out_size >> output raster size (same as input is None)
	out_res >> output raster resolution (same as input if None)
	'''

	if not GDAL:
		raise NotImplementedError

	#Create an in memory gdal raster and write data to it (PIL > Numpy > GDAL)
	data = np.asarray(geoimg.img)
	img_h, img_w, nbBands = data.shape
	ds1 = gdal.GetDriverByName('MEM').Create('', img_w, img_h, nbBands, gdal.GDT_Byte)
	for bandIdx in range(nbBands):
		bandArray = data[:,:,bandIdx]
		ds1.GetRasterBand(bandIdx+1).WriteArray(bandArray)
	"""
	# Alternative : Use a virtual memory file to create gdal dataset from buffer
	buff = io.BytesIO()
	geoimg.img.save(buff, format='PNG')
	vsipath = '/vsimem/mosaic'
	gdal.FileFromMemBuffer(vsipath, buff.getvalue())
	ds1 = gdal.Open(vsipath)
	img_h, img_w = ds1.RasterXSize, ds1.RasterYSize
	nbBands = ds1.RasterCount
	"""

	#Assign georef infos
	xmin, ymax = geoimg.ul
	res = geoimg.res
	geoTrans = (xmin, res, 0, ymax, 0, -res)
	ds1.SetGeoTransform(geoTrans)
	prj1 = getSpatialRef(crs1)
	wkt1 = prj1.ExportToWkt()
	ds1.SetProjection(wkt1)

	#Build destination dataset
	# ds2 will be a template empty raster to reproject the data into
	# we can directly set its size, res and top left coord as expected
	# reproject funtion will match the template (clip and resampling)

	if out_ul is not None:
		xmin, ymax = out_ul
	else:
		xmin, ymax = reproj(crs1, crs2, xmin, ymax)

	#submit resolution and size
	if out_res is not None and out_size is not None:
		res = out_res
		img_w, img_h = out_size

	#submit resolution and auto compute the best image size
	if out_res is not None and out_size is None:
		res = out_res
		#reprojected image size depend on final bbox and expected resolution
		xmin, ymin, xmax, ymax = reprojBbox(crs1, crs2, geoimg.bbox)
		img_w = int( (xmax - xmin) / res )
		img_h = int( (ymax - ymin) / res )

	#submit image size and ...
	if out_res is None and out_size is not None:
		img_w, img_h = out_size
		#...let's res as source value ? (image will be croped)

	#Keep original image px size and compute resolution to approximately preserve geosize
	if out_res is None and out_size is None:
		#find the res that match source diagolal size
		xmin, ymin, xmax, ymax = reprojBbox(crs1, crs2, geoimg.bbox)
		dst_diag = math.sqrt( (xmax - xmin)**2 + (ymax - ymin)**2)
		px_diag = math.sqrt(img_w**2 + img_h**2)
		res = dst_diag / px_diag

	ds2 = gdal.GetDriverByName('MEM').Create('', img_w, img_h, nbBands, gdal.GDT_Byte)
	geoTrans = (xmin, res, 0, ymax, 0, -res)
	ds2.SetGeoTransform(geoTrans)
	prj2 = getSpatialRef(crs2)
	wkt2 = prj2.ExportToWkt()
	ds2.SetProjection(wkt2)

	#Perform the projection/resampling
	# Resample algo
	if RESAMP_ALG == 'NN' : alg = gdal.GRA_NearestNeighbour
	elif RESAMP_ALG == 'BL' : alg = gdal.GRA_Bilinear
	elif RESAMP_ALG == 'CB' : alg = gdal.GRA_Cubic
	elif RESAMP_ALG == 'CBS' : alg = gdal.GRA_CubicSpline
	elif RESAMP_ALG == 'LCZ' : alg = gdal.GRA_Lanczos
	# Memory limit (0 = no limit)
	memLimit = 0
	# Error in pixels (0 will use the exact transformer)
	threshold = 0.25
	# Warp options (http://www.gdal.org/structGDALWarpOptions.html)
	opt = ['NUM_THREADS=ALL_CPUS, SAMPLE_GRID=YES']
	gdal.ReprojectImage( ds1, ds2, wkt1, wkt2, alg, memLimit, threshold)#, options=opt) #option parameter start with gdal 2.1

	#Convert to PIL image
	data = ds2.ReadAsArray()
	data = np.rollaxis(data, 0, 3) # because first axis is band index
	img = Image.fromarray(data, 'RGBA')

	#Close gdal datasets
	ds1 = None
	ds2 = None

	return GeoImage(img, (xmin, ymax), res)






####################

class BaseMap():

	"""Handle a map as background image in Blender"""

	def __init__(self, context, srckey, laykey, grdkey=None):

		#Get context
		self.scn = context.scene
		self.area = context.area
		self.area3d = [r for r in self.area.regions if r.type == 'WINDOW'][0]
		self.view3d = self.area.spaces.active
		self.reg3d = self.view3d.region_3d

		#Get cache destination folder in addon preferences
		prefs = context.user_preferences.addons[__package__].preferences
		folder = prefs.cacheFolder

		#Get resampling algo preference and set the constant
		global RESAMP_ALG
		RESAMP_ALG = prefs.resamplAlg

		#Init MapService class
		self.srv = MapService(srckey, folder)

		#Set destination tile matrix
		if grdkey is None:
			grdkey = self.srv.srcGridKey
		else:
			grdkey = grdkey

		if self.srv.srcGridKey == grdkey:
			self.tm = self.srv.srcTms
		else:
			#Define destination grid in map service
			self.srv.setDstGrid(grdkey)
			self.tm = self.srv.dstTms

		#Set path to tiles mosaic used as background image in Blender
		self.imgPath = folder + srckey + '_' + laykey + '_' + grdkey + ".png"

		#Get layer def obj
		self.layer = self.srv.layers[laykey]

		#map keys
		self.srckey = srckey
		self.laykey = laykey
		self.grdkey = grdkey

		#Read scene props (we assume these props have already been created, cf. MAP_START)
		self.update()

		#Thread attributes
		self.thread = None
		#Background image attributes
		self.img = None #bpy image
		self.bkg = None #bpy background
		self.viewDstZ = None #view 3d z distance
		#Store previous request
		#TODO

	def update(self):
		'''Read scene properties and update attributes'''
		scn = self.scn
		self.zoom = scn[SK_Z]
		self.scale = scn[SK_SCALE]
		self.lat, self.long = scn[SK_LAT], scn[SK_LON]

		#TODO add ability to read proj4 def
		if scn[SK_CRS] == "":
			scn[SK_CRS] = str(self.tm.CRS)
		try:
			self.crs = int(scn[SK_CRS])
		except:
			self.crs = scn[SK_CRS]

		#get scene origin coords in proj system
		self.origin_x, self.origin_y = reproj(4326, self.crs, self.long, self.lat)

	def get(self):
		'''Launch run() function in a new thread'''
		self.stop()
		self.srv.running = True
		self.thread = threading.Thread(target=self.run)
		self.thread.start()

	def stop(self):
		'''Stop actual thread'''
		if self.srv.running:
			self.srv.running = False
			self.thread.join()

	def run(self):
		"""thread method"""
		self.update()
		self.mosaic = self.request()
		if self.srv.running and self.mosaic is not None:
			#save image
			self.mosaic.save(self.imgPath)
		if self.srv.running:
			#Place background image
			self.place()

	def progress(self):
		'''Report thread download progress'''
		return self.srv.cptTiles, self.srv.nbTiles


	def view3dToProj(self, dx, dy):
		'''Convert view3d coords to crs coords'''
		x = self.origin_x + dx
		y = self.origin_y + dy
		return x, y

	def moveOrigin(self, dx, dy):
		'''Move scene origin and update props'''
		self.origin_x += dx
		self.origin_y += dy
		lon, lat = reproj(self.crs, 4326, self.origin_x, self.origin_y)
		self.scn[SK_LAT], self.scn[SK_LON] = lat, lon

	def request(self):
		'''Request map service to build a mosaic of required tiles to cover view3d area'''
		#Get area dimension
		#w, h = self.area.width, self.area.height
		w, h = self.area3d.width, self.area3d.height

		#Get area bbox coords (map origin is bottom lelf)
		res = self.tm.getRes(self.zoom)
		xmin = self.origin_x - w/2 * res
		ymax = self.origin_y + h/2 * res
		xmax = self.origin_x + w/2 * res
		ymin = self.origin_y - h/2 * res
		bbox = (xmin, ymin, xmax, ymax)

		#reproj bbox to destination grid crs if scene crs is different
		if self.crs != self.tm.CRS:
			bbox = reprojBbox(self.crs, self.tm.CRS, bbox)

		#Stop thread if the request is same as previous
		#TODO

		if self.srv.srcGridKey == self.grdkey:
			toDstGrid = False
		else:
			toDstGrid = True

		mosaic = self.srv.getImage(self.laykey, bbox, self.zoom, toDstGrid, outCRS=self.crs)

		return mosaic


	def place(self):
		'''Set map as background image'''

		#Get or load bpy image
		try:
			self.img = [img for img in bpy.data.images if img.filepath == self.imgPath][0]
		except:
			self.img = bpy.data.images.load(self.imgPath)

		#Activate view3d background
		self.view3d.show_background_images = True

		#Hide all existing background
		for bkg in self.view3d.background_images:
			bkg.show_background_image = False

		#Get or load background image
		bkgs = [bkg for bkg in self.view3d.background_images if bkg.image is not None]
		try:
			self.bkg = [bkg for bkg in bkgs if bkg.image.filepath == self.imgPath][0]
		except:
			self.bkg = self.view3d.background_images.new()
			self.bkg.image = self.img

		#Set some background props
		self.bkg.show_background_image = True
		self.bkg.view_axis = 'TOP'
		self.bkg.opacity = 1

		#Get some image props
		img_ox, img_oy = self.mosaic.origin
		img_w, img_h = self.mosaic.size
		res = self.mosaic.res
		#res = self.tm.getRes(self.zoom)

		#Set background size
		sizex = img_w * res / self.scale
		self.bkg.size = sizex #since blender > 2.74 else = sizex/2

		#Set background offset (image origin does not match scene origin)
		dx = (self.origin_x - img_ox) / self.scale
		dy = (self.origin_y - img_oy) / self.scale
		self.bkg.offset_x = -dx
		ratio = img_w / img_h
		self.bkg.offset_y = -dy * ratio #https://developer.blender.org/T48034

		#Compute view3d z distance
		#in ortho view, view_distance = max(view3d dst x, view3d dist y) / 2
		dst =  max( [self.area3d.width, self.area3d.height] )
		dst = dst * res / self.scale
		dst /= 2
		self.reg3d.view_distance = dst
		self.viewDstZ = dst

		#Update image drawing
		self.bkg.image.reload()




####################################


def drawInfosText(self, context):
	"""Draw map infos on 3dview"""

	#Get contexts
	scn = context.scene
	area = context.area
	area3d = [reg for reg in area.regions if reg.type == 'WINDOW'][0]
	view3d = area.spaces.active
	reg3d = view3d.region_3d

	#Get area3d dimensions
	w, h = area3d.width, area3d.height
	cx = w/2 #center x

	#Get map props stored in scene
	zoom = scn[SK_Z]
	lat, long = scn[SK_LAT], scn[SK_LON]
	scale = scn[SK_SCALE]

	#Set text police and color
	font_id = 0  # ???
	prefs = context.user_preferences.addons[__package__].preferences
	fontColor = prefs.fontColor
	bgl.glColor4f(*fontColor) #rgba

	#Draw title
	blf.position(font_id, cx-25, 70, 0) #id, x, y, z
	blf.size(font_id, 15, 72) #id, point size, dpi
	blf.draw(font_id, "Map view")

	#Draw other texts
	blf.size(font_id, 12, 72)
	# thread progress
	blf.position(font_id, cx-45, 90, 0)
	if self.nbTotal > 0:
		blf.draw(font_id, '(Downloading... ' + str(self.nb)+'/'+str(self.nbTotal) + ')')
	# zoom and scale values
	blf.position(font_id, cx-50, 50, 0)
	blf.draw(font_id, "Zoom " + str(zoom) + " - Scale 1:" + str(int(scale)))
	# view3d distance
	dst = reg3d.view_distance
	blf.position(font_id, cx-50, 30, 0)
	blf.draw(font_id, '3D View distance ' + str(int(dst)))
	# cursor crs coords
	blf.position(font_id, cx-45, 10, 0)
	blf.draw(font_id, str((int(self.posx), int(self.posy))))



def drawZoomBox(self, context):

	bgl.glEnable(bgl.GL_BLEND)
	bgl.glColor4f(0, 0, 0, 0.5)
	bgl.glLineWidth(2)

	if self.zoomBoxMode and not self.zoomBoxDrag:
		# before selection starts draw infinite cross
		bgl.glBegin(bgl.GL_LINES)

		px, py = self.zb_xmax, self.zb_ymax

		bgl.glVertex2i(0, py)
		bgl.glVertex2i(context.area.width, py)		

		bgl.glVertex2i(px, 0)
		bgl.glVertex2i(px, context.area.height)

		bgl.glEnd()

	elif self.zoomBoxMode and self.zoomBoxDrag:
		# when selecting draw dashed line box
		bgl.glEnable(bgl.GL_LINE_STIPPLE)
		bgl.glLineStipple(2, 0x3333)
		bgl.glBegin(bgl.GL_LINE_LOOP)

		bgl.glVertex2i(self.zb_xmin, self.zb_ymin)
		bgl.glVertex2i(self.zb_xmin, self.zb_ymax)
		bgl.glVertex2i(self.zb_xmax, self.zb_ymax)
		bgl.glVertex2i(self.zb_xmax, self.zb_ymin)

		bgl.glEnd()

		bgl.glDisable(bgl.GL_LINE_STIPPLE)


	# restore opengl defaults
	bgl.glLineWidth(1)
	bgl.glDisable(bgl.GL_BLEND)
	bgl.glColor4f(0.0, 0.0, 0.0, 1.0)

###############

class MAP_START(bpy.types.Operator):

	bl_idname = "view3d.map_start"
	bl_description = 'Toggle 2d map navigation'
	bl_label = "Map viewer"
	bl_options = {'REGISTER'}

	#special function to auto redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True

	def listSources(self, context):
		srcItems = []
		for srckey, src in SOURCES.items():
			#put each item in a tuple (key, label, tooltip)
			srcItems.append( (srckey, src['name'], src['description']) )
		return srcItems

	def listGrids(self, context):
		grdItems = []
		src = SOURCES[self.src]
		for gridkey, grd in GRIDS.items():
			#put each item in a tuple (key, label, tooltip)
			if gridkey == src['grid']:
				#insert at first position
				grdItems.insert(0, (gridkey, grd['name']+' (source)', grd['description']) )
			else:
				grdItems.append( (gridkey, grd['name'], grd['description']) )
		return grdItems

	def listLayers(self, context):
		layItems = []
		src = SOURCES[self.src]
		for laykey, lay in src['layers'].items():
			#put each item in a tuple (key, label, tooltip)
			layItems.append( (laykey, lay['name'], lay['description']) )
		return layItems


	src = EnumProperty(
				name = "Map",
				description = "Choose map service source",
				items = listSources
				)

	grd = EnumProperty(
				name = "Grid",
				description = "Choose cache tiles matrix",
				items = listGrids
				)

	lay = EnumProperty(
				name = "Layer",
				description = "Choose layer",
				items = listLayers
				)

	crsOpt = EnumProperty(
				name = "CRS",
				description = "Choose Coordinate Reference System",
				items = [ ("grid", "Same as tile matrix", ""), ("scene", "Custom (scene)", ""), ("predef", "Custom (predefinate)", "") ]
				)

	dialog = StringProperty(default='MAP') # 'MAP', 'SEARCH', 'OPTIONS'

	query = StringProperty(name="Go to")


	def draw(self, context):
		addonPrefs = context.user_preferences.addons[__package__].preferences
		scn = context.scene
		layout = self.layout

		if self.dialog == 'SEARCH':
				layout.prop(self, 'query')

		elif self.dialog == 'OPTIONS':
			layout.prop(addonPrefs, "fontColor")
			#viewPrefs = context.user_preferences.view
			#layout.prop(viewPrefs, "use_zoom_to_mouse")
			layout.prop(addonPrefs, "zoomToMouse")

		elif self.dialog == 'MAP':
			layout.prop(self, 'src', text='Source')
			layout.prop(self, 'lay', text='Layer')
			col = layout.column()
			if not GDAL:
				col.enabled = False
				col.label('Install GDAL to enable raster reprojection support')
			col.prop(self, 'grd', text='Tile matrix set')
			col.prop(self, 'crsOpt', text='CRS')
			if self.crsOpt == 'scene':
				#display the scene prop
				col.prop(scn, '["'+SK_CRS+'"]', text='Scene CRS')
			elif self.crsOpt == "predef":
				col.prop(addonPrefs, "predefCrs", text='Predefinate CRS')
			row = layout.row()
			row.label('Map scale:')
			row.prop(scn, '["'+SK_SCALE+'"]', text='')


	def invoke(self, context, event):

		if not context.area.type == 'VIEW_3D':
			self.report({'WARNING'}, "View3D not found, cannot run operator")
			return {'CANCELLED'}

		#Init scene props if not exists
		scn = context.scene
		# get or init the dictionary containing IDprops settings
		rna_ui = scn.get('_RNA_UI')
		if rna_ui is None:
			scn['_RNA_UI'] = {}
			rna_ui = scn['_RNA_UI']
		# scene origin lat long
		if SK_LAT not in scn and SK_LON not in scn:
			scn[SK_LAT], scn[SK_LON] = 0.0, 0.0 #explicit float for id props
		# zoom level
		if SK_Z not in scn:
			scn[SK_Z] = 0
		# EPSG code or proj4 string
		if SK_CRS not in scn:
			scn[SK_CRS] = "" #string id props
		# scale
		if SK_SCALE not in scn:
			scn[SK_SCALE] = 1 #1:1
			rna_ui[SK_SCALE] = {"description": "Map scale denominator", "default": 1, "min": 1}

		#Display dialog
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		scn = context.scene
		prefs = context.user_preferences.addons[__package__].preferences

		#check cache folder
		folder = prefs.cacheFolder
		if folder == "" or not os.path.exists(folder):
			self.report({'ERROR'}, "Please define a valid cache folder path")
			return {'FINISHED'}

		#check crs option
		if self.crsOpt == 'grid':
			scn[SK_CRS] = "" #will be correctly assigned later
		elif self.crsOpt == 'scene' and scn[SK_CRS] == "":
			self.report({'ERROR'}, "Scene does not contains CRS definition")
			return {'FINISHED'}
		elif self.crsOpt == 'predef':
			crskey = prefs.predefCrs
			if crskey == '':
				self.report({'ERROR'}, "No predefined CRS. Please add one in addon preferences")
				return {'FINISHED'}
			else:
				data = json.loads(prefs.predefCrsJson)
				scn[SK_CRS] = data[crskey]['projection']

		#Move scene origin to the researched place
		if self.dialog == 'SEARCH':
			bpy.ops.view3d.map_search('EXEC_DEFAULT', query=self.query)

		#Start map viewer operator
		self.dialog = 'MAP' #reinit dialog type
		bpy.ops.view3d.map_viewer('INVOKE_DEFAULT', srckey=self.src, laykey=self.lay, grdkey=self.grd)

		return {'FINISHED'}





###############


class MAP_VIEWER(bpy.types.Operator):

	bl_idname = "view3d.map_viewer"
	bl_description = 'Toggle 2d map navigation'
	bl_label = "Map viewer"
	bl_options = {'INTERNAL'}

	srckey = StringProperty()

	grdkey = StringProperty()

	laykey = StringProperty()

	@classmethod
	def poll(cls, context):
		return context.area.type == 'VIEW_3D'


	def __del__(self):
		if getattr(self, 'restart', False):
			if self.map.crs == self.map.tm.CRS:
				crsOpt = 'grid'
			else:
				crsOpt = 'scene'
			#TODO identify predef crs
			bpy.ops.view3d.map_start('INVOKE_DEFAULT', src=self.srckey, lay=self.laykey, grd=self.grdkey, dialog=self.dialog, crsOpt=crsOpt)


	def invoke(self, context, event):

		self.restart = False
		self.dialog = 'MAP' # dialog name for MAP_START >> string in  ['MAP', 'SEARCH', 'OPTIONS']

		self.moveFactor = 0.1

		#Add draw callback to view space
		args = (self, context)
		self._drawTextHandler = bpy.types.SpaceView3D.draw_handler_add(drawInfosText, args, 'WINDOW', 'POST_PIXEL')
		self._drawZoomBoxHandler = bpy.types.SpaceView3D.draw_handler_add(drawZoomBox, args, 'WINDOW', 'POST_PIXEL')

		#Add modal handler and init a timer
		context.window_manager.modal_handler_add(self)
		self.timer = context.window_manager.event_timer_add(0.05, context.window)

		#Switch to top view ortho (center to origin)
		view3d = context.area.spaces.active
		bpy.ops.view3d.viewnumpad(type='TOP')
		view3d.region_3d.view_perspective = 'ORTHO'
		view3d.cursor_location = (0, 0, 0)
		bpy.ops.view3d.view_center_cursor()
		##view3d.region_3d.view_location = (0, 0, 0)

		#Init some properties
		# tag if map is currently drag
		self.inMove = False
		# mouse crs coordinates reported in draw callback
		self.posx, self.posy = 0, 0
		# thread progress infos reported in draw callback
		self.nb, self.nbTotal = 0, 0
		# Zoom box 
		self.zoomBoxMode = False
		self.zoomBoxDrag = False
		self.zb_xmin, self.zb_xmax = 0, 0
		self.zb_ymin, self.zb_ymax = 0, 0

		#Get map
		self.map = BaseMap(context, self.srckey, self.laykey, self.grdkey)
		self.map.get()

		return {'RUNNING_MODAL'}



	def mouseTo3d(self, context, x, y):
		'''Convert event.mouse_region to world coordinates'''
		coords = (x, y)
		reg = context.region
		reg3d = context.region_data
		vec = region_2d_to_vector_3d(reg, reg3d, coords)
		loc = region_2d_to_location_3d(reg, reg3d, coords, vec)
		return loc


	def modal(self, context, event):

		context.area.tag_redraw()
		scn = bpy.context.scene

		if event.type == 'TIMER':
			#report thread progression
			self.nb, self.nbTotal = self.map.progress()
			return {'PASS_THROUGH'}


		if event.type in ['WHEELUPMOUSE', 'NUMPAD_PLUS']:

			if event.value == 'PRESS':

				if event.alt:
					# map scale up
					scn[SK_SCALE] *= 10
					self.map.scale = scn[SK_SCALE]
					self.map.place()

				elif event.ctrl:
					# view3d zoom up
					dst = context.region_data.view_distance
					context.region_data.view_distance -= dst * self.moveFactor
					if context.user_preferences.addons[__package__].preferences.zoomToMouse:
						mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
						viewLoc = context.region_data.view_location
						k = (viewLoc - mouseLoc) * self.moveFactor
						viewLoc -= k
				else:
					# map zoom up
					if scn[SK_Z] < self.map.layer.zmax and scn[SK_Z] < self.map.tm.nbLevels-1:
						scn[SK_Z] += 1

						resFactor = self.map.tm.getNextResFac(scn[SK_Z])

						#if not context.user_preferences.view.use_zoom_to_mouse:
						if not context.user_preferences.addons[__package__].preferences.zoomToMouse:
							context.region_data.view_distance /= resFactor
						else:
							#Progressibly zoom to cursor (use intercept theorem)
							dst = context.region_data.view_distance
							dst2 = dst / resFactor
							context.region_data.view_distance = dst2
							k = (dst - dst2) / dst
							loc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
							dx = loc.x * k
							dy = loc.y * k
							s = self.map.scale
							self.map.moveOrigin(dx*s, dy*s)
							if self.map.bkg is not None:
								ratio = self.map.img.size[0] / self.map.img.size[1]
								self.map.bkg.offset_x -= dx
								self.map.bkg.offset_y -= dy * ratio
						self.map.get()


		if event.type in ['WHEELDOWNMOUSE', 'NUMPAD_MINUS']:

			if event.value == 'PRESS':

				if event.alt:
					#map scale down
					s = scn[SK_SCALE] / 10
					if s < 1: s = 1
					scn[SK_SCALE] = s
					self.map.scale = s
					self.map.place()

				elif event.ctrl:
					#view3d zoom down
					dst = context.region_data.view_distance
					context.region_data.view_distance += dst * self.moveFactor
					if context.user_preferences.addons[__package__].preferences.zoomToMouse:
						mouseLoc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
						viewLoc = context.region_data.view_location
						k = (viewLoc - mouseLoc) * self.moveFactor
						viewLoc += k
				else:
					#map zoom down
					if scn[SK_Z] > self.map.layer.zmin and scn[SK_Z] > 0:
						scn[SK_Z] -= 1

						resFactor = self.map.tm.getPrevResFac(scn[SK_Z])

						#if not context.user_preferences.view.use_zoom_to_mouse:
						if not context.user_preferences.addons[__package__].preferences.zoomToMouse:
							context.region_data.view_distance *= resFactor
						else:
							#Progressibly zoom to cursor (use intercept theorem)
							dst = context.region_data.view_distance
							dst2 = dst * resFactor
							context.region_data.view_distance = dst2
							k = (dst - dst2) / dst
							loc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
							dx = loc.x * k
							dy = loc.y * k
							s = self.map.scale
							self.map.moveOrigin(dx*s, dy*s)
							if self.map.bkg is not None:
								ratio = self.map.img.size[0] / self.map.img.size[1]
								self.map.bkg.offset_x -= dx
								self.map.bkg.offset_y -= dy * ratio
						self.map.get()



		if event.type == 'MOUSEMOVE':

			#Report mouse location coords in projeted crs
			loc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
			self.posx, self.posy = self.map.view3dToProj(loc.x, loc.y)

			if self.zoomBoxMode:
				self.zb_xmax, self.zb_ymax = event.mouse_region_x, event.mouse_region_y

			#Drag background image (edit its offset values)
			if self.inMove and self.map.bkg is not None:
				loc1 = self.mouseTo3d(context, self.x1, self.y1)
				loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
				dx = loc1.x - loc2.x
				dy = loc1.y - loc2.y
				if event.ctrl:
					x, y, z = self.viewLoc
					context.region_data.view_location = (dx+x, dy+y, z)
				else:
					ratio = self.map.img.size[0] / self.map.img.size[1]
					self.map.bkg.offset_x = self.offset_x - dx
					self.map.bkg.offset_y = self.offset_y - (dy * ratio)


		if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'}:

			if event.value == 'PRESS' and self.zoomBoxMode:
				self.zoomBoxDrag = True
				self.zb_xmin, self.zb_ymin = event.mouse_region_x, event.mouse_region_y

			if event.value == 'PRESS' and not self.zoomBoxMode:
				#Get click mouse position and background image offset (if exist)
				self.x1, self.y1 = event.mouse_region_x, event.mouse_region_y
				if event.ctrl:
					self.viewLoc = context.region_data.view_location.copy()
				else:
					#Stop thread now, because we don't know when the mouse click will be released
					self.map.stop()
					if self.map.bkg is not None:
						self.offset_x = self.map.bkg.offset_x
						self.offset_y = self.map.bkg.offset_y
				#Tag that map is currently draging
				self.inMove = True

			if event.value == 'RELEASE' and not self.zoomBoxMode:
				self.inMove = False
				if not event.ctrl:
					#Compute final shift
					loc1 = self.mouseTo3d(context, self.x1, self.y1)
					loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
					dx = (loc1.x - loc2.x) * self.map.scale
					dy = (loc1.y - loc2.y) * self.map.scale
					#Update map
					self.map.moveOrigin(dx,dy)
					self.map.get()

			if event.value == 'RELEASE' and self.zoomBoxMode:
				#Get final zoom box
				xmax = max(event.mouse_region_x, self.zb_xmin)
				ymax = max(event.mouse_region_y, self.zb_ymin)
				xmin = min(event.mouse_region_x, self.zb_xmin)
				ymin = min(event.mouse_region_y, self.zb_ymin)
				#Exit zoom box mode
				self.zoomBoxDrag = False
				self.zoomBoxMode = False
				context.window.cursor_set('DEFAULT')
				#Move scene origin to box origin
				w = xmax - xmin
				h = ymax - ymin
				cx = xmin + w/2
				cy = ymin + h/2
				loc = self.mouseTo3d(context, cx, cy)
				dx = loc.x * self.map.scale
				dy = loc.y * self.map.scale
				self.map.moveOrigin(dx, dy)
				#Compute target resolution
				px_diag = math.sqrt(context.area.width**2 + context.area.height**2)
				mapRes = self.map.tm.getRes(self.map.zoom)
				dst_diag = math.sqrt( (w*mapRes)**2 + (h*mapRes)**2)
				targetRes = dst_diag / px_diag
				z = self.map.tm.getNearestZoom(targetRes, rule='lower')
				scn[SK_Z] = z
				#Update map
				self.map.get()				


		if event.type in ['LEFT_CTRL', 'RIGHT_CTRL']:
			if event.value == 'RELEASE':
				#restore view 3d distance and location
				if self.map.viewDstZ is not None:
					context.region_data.view_distance = self.map.viewDstZ
				context.region_data.view_location = (0,0,0)


		#NUMPAD MOVES (3D VIEW or MAP)
		if event.value == 'PRESS':
			if event.type == 'NUMPAD_4':
				if event.ctrl:
					x, y, z = context.region_data.view_location
					dx = self.map.bkg.size * self.moveFactor
					x -= dx
					context.region_data.view_location = (x,y,z)
				else:
					self.map.stop()
					dx = self.map.bkg.size * self.moveFactor
					self.map.moveOrigin(-dx*self.map.scale, 0)
					if self.map.bkg is not None:
						self.map.bkg.offset_x += dx
					self.map.get()
			if event.type == 'NUMPAD_6':
				if event.ctrl:
					x, y, z = context.region_data.view_location
					dx = self.map.bkg.size * self.moveFactor
					x += dx
					context.region_data.view_location = (x,y,z)
				else:
					self.map.stop()
					dx = self.map.bkg.size * self.moveFactor
					self.map.moveOrigin(dx*self.map.scale, 0)
					if self.map.bkg is not None:
						self.map.bkg.offset_x -= dx
					self.map.get()
			if event.type == 'NUMPAD_2':
				if event.ctrl:
					x, y, z = context.region_data.view_location
					dy = self.map.bkg.size * self.moveFactor
					y -= dy
					context.region_data.view_location = (x,y,z)
				else:
					self.map.stop()
					dy = self.map.bkg.size * self.moveFactor
					self.map.moveOrigin(0, -dy*self.map.scale)
					if self.map.bkg is not None:
						ratio = self.map.img.size[0] / self.map.img.size[1]
						self.map.bkg.offset_y += dy * ratio
					self.map.get()
			if event.type == 'NUMPAD_8':
				if event.ctrl:
					x, y, z = context.region_data.view_location
					dy = self.map.bkg.size * self.moveFactor
					y += dy
					context.region_data.view_location = (x,y,z)
				else:
					self.map.stop()
					dy = self.map.bkg.size * self.moveFactor
					self.map.moveOrigin(0, dy*self.map.scale)
					if self.map.bkg is not None:
						ratio = self.map.img.size[0] / self.map.img.size[1]
						self.map.bkg.offset_y -= dy * ratio
					self.map.get()

		#SWITCH LAYER
		if event.type == 'SPACE':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			return {'FINISHED'}

		#GO TO
		if event.type == 'G':
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			self.dialog = 'SEARCH'
			return {'FINISHED'}

		#OPTIONS
		if event.type == 'O': 
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			self.restart = True
			self.dialog = 'OPTIONS'
			return {'FINISHED'}

		#ZOOM BOX
		if event.type == 'B' and event.value == 'PRESS':
			self.map.stop()
			self.zoomBoxMode = True
			self.zb_xmax, self.zb_ymax = event.mouse_region_x, event.mouse_region_y
			context.window.cursor_set('CROSSHAIR')

		#EXIT
		if event.type == 'ESC' and event.value == 'PRESS': 
			if self.zoomBoxMode:
				self.zoomBoxDrag = False
				self.zoomBoxMode = False
				context.window.cursor_set('DEFAULT')
			else:
				self.map.stop()
				bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
				bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
				return {'CANCELLED'}

		"""
		#FINISH
		if event.type in {'RET'}:
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._drawTextHandler, 'WINDOW')
			bpy.types.SpaceView3D.draw_handler_remove(self._drawZoomBoxHandler, 'WINDOW')
			return {'FINISHED'}
		"""

		return {'RUNNING_MODAL'}



####################################

class MAP_SEARCH(bpy.types.Operator):

	bl_idname = "view3d.map_search"
	bl_description = 'Search for a place and move scene origin to it'
	bl_label = "Map search"
	bl_options = {'INTERNAL'}

	query = StringProperty(name="Go to")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		scn = context.scene
		geocoder = Nominatim(base_url="http://nominatim.openstreetmap.org", referer="bgis")
		results = geocoder.query(self.query)
		if len(results) >= 1:
			result = results[0]
			lat, long = float(result['lat']), float(result['lon'])
			scn[SK_LAT], scn[SK_LON] = lat, long

		return {'FINISHED'}


####################################

class MAP_PREFS(AddonPreferences):

	bl_idname = __package__

	def listPredefCRS(self, context):
		crsItems = []
		data = json.loads(self.predefCrsJson)
		for crskey, crs in data.items():
			#put each item in a tuple (key, label, tooltip)
			crsItems.append( (crskey, crs['description'], crs['description']) )
		return crsItems

	cacheFolder = StringProperty(
		name = "Cache folder",
		default = "",
		description = "Define a folder where to store Geopackage SQlite db",
		subtype = 'DIR_PATH'
		)

	fontColor = FloatVectorProperty(
		name="Font color",
		subtype='COLOR',
		min=0, max=1,
		size=4,
		default=(0, 0, 0, 1)
		)

	zoomToMouse = BoolProperty(name="Zoom to mouse", description='Zoom towards the mouse pointer position', default=True)

	resamplAlg = EnumProperty(
		name = "Resampling method",
		description = "Choose GDAL's resampling method used for reprojection",
		items = [ ('NN', 'Nearest Neighboor', ''), ('BL', 'Bilinear', ''), ('CB', 'Cubic', ''), ('CBS', 'Cubic Spline', ''), ('LCZ', 'Lanczos', '') ]
		)

	#json string
	predefCrsJson = StringProperty(default='{}')

	predefCrs = EnumProperty(
		name = "Predefinate CRS",
		description = "Choose predefinite Coordinate Reference System",
		items = listPredefCRS
		)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, "cacheFolder")


		row = layout.row()
		row.prop(self, "zoomToMouse")
		row.label('Font color:')
		row.prop(self, "fontColor", text='')

		row = layout.row()
		row.label('Predefinate CRS:')
		row.prop(self, "predefCrs", text='')
		row.operator("view3d.map_add_predef_crs")
		row.operator("view3d.map_edit_predef_crs")
		row.operator("view3d.map_rmv_predef_crs")

		row = layout.row()
		row.prop(self, "resamplAlg")



class MAP_PREFS_SHOW(bpy.types.Operator):

	bl_idname = "view3d.map_pref_show"
	bl_description = 'Display basemaps addon preferences'
	bl_label = "Preferences"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		addon_utils.modules_refresh()
		bpy.context.user_preferences.active_section = 'ADDONS'
		bpy.data.window_managers["WinMan"].addon_search = __package__
		#bpy.ops.wm.addon_expand(module=__package__)
		mod = addon_utils.addons_fake_modules.get(__package__)
		mod.bl_info['show_expanded'] = True
		bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
		return {'FINISHED'}


class PREDEF_CRS_ADD(bpy.types.Operator):

	bl_idname = "view3d.map_add_predef_crs"
	bl_description = 'Add predefinate CRS'
	bl_label = "Add CRS"
	bl_options = {'INTERNAL'}

	key = StringProperty(name = "Short name (key)", description = "Choose an identifier for this CRS (like an acronym)")
	desc = StringProperty(name = "Description", description = "Choose a convenient name for this CRS")
	prj = StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		addonPrefs = context.user_preferences.addons[__package__].preferences
		data = json.loads(addonPrefs.predefCrsJson)
		data[self.key] = {"description":self.desc, "projection":self.prj}
		addonPrefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		#bpy.ops.wm.save_userpref()
		return {'FINISHED'}

class PREDEF_CRS_RMV(bpy.types.Operator):

	bl_idname = "view3d.map_rmv_predef_crs"
	bl_description = 'Remove predefinate CRS'
	bl_label = "Remove CRS"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		addonPrefs = context.user_preferences.addons[__package__].preferences
		key = addonPrefs.predefCrs
		if key != '':
			data = json.loads(addonPrefs.predefCrsJson)
			del data[key]
			addonPrefs.predefCrsJson = json.dumps(data)
		return {'FINISHED'}

class PREDEF_CRS_EDIT(bpy.types.Operator):

	bl_idname = "view3d.map_edit_predef_crs"
	bl_description = 'Edit predefinate CRS'
	bl_label = "Edit CRS"
	bl_options = {'INTERNAL'}

	key = StringProperty(name = "Short name (key)", description = "Choose an identifier for this CRS (like an acronym)")
	desc = StringProperty(name = "Description", description = "Choose a convenient name for this CRS")
	prj = StringProperty(name = "EPSG code or Proj4 string",  description = "Specify EPSG code or Proj4 string definition for this CRS")

	def invoke(self, context, event):
		addonPrefs = context.user_preferences.addons[__package__].preferences
		key = addonPrefs.predefCrs
		if key == '':
			return {'FINISHED'}
		data = json.loads(addonPrefs.predefCrsJson)
		self.key = key
		self.desc = data[key]["description"]
		self.prj = data[key]["projection"]
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		addonPrefs = context.user_preferences.addons[__package__].preferences
		data = json.loads(addonPrefs.predefCrsJson)
		data[self.key] = {"description":self.desc, "projection":self.prj}
		addonPrefs.predefCrsJson = json.dumps(data)
		context.area.tag_redraw()
		return {'FINISHED'}


####################################

class MAP_PANEL(Panel):
	bl_category = "GIS"
	bl_label = "Basemap"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"#"UI"


	def draw(self, context):
		layout = self.layout
		scn = context.scene
		addonPrefs = context.user_preferences.addons[__package__].preferences

		layout.operator("view3d.map_start")

		layout.label("Options :")

		box = layout.box()
		box.operator("view3d.map_pref_show")
		#box.label("Cache folder:")
		#box.prop(addonPrefs, "cacheFolder", text='')

		r = box.row()
		r.label('Font color:')
		r.prop(addonPrefs, "fontColor", text='')

		#viewPrefs = context.user_preferences.view
		#box.prop(viewPrefs, "use_zoom_to_mouse")
		box.prop(addonPrefs, "zoomToMouse")

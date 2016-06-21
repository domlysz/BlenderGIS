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


#deps imports
import numpy as np

try:
	from PIL import Image
except:
	PILLOW = False
else:
	PILLOW = True

try:
	from osgeo import gdal, osr
except:
	GDAL = False
else:
	GDAL = True

#addon import
from .servicesDefs import GRIDS, SOURCES

#reproj functions
from geoscene.proj import reprojPt, reprojBbox, dd2meters, CRS

#Constants



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
		self.auth, self.code = tm.CRS.split(':')
		self.code = int(self.code)
		self.tileSize = tm.tileSize
		self.xmin, self.ymin, self.xmax, self.ymax = tm.globalbbox
		self.resolutions = tm.getResList()

		if not self.isGPKG():
			self.create()
			self.insertMetadata()

			self.insertCRS(self.code, str(self.code), self.auth)
			#self.insertCRS(3857, "Web Mercator")
			#self.insertCRS(4326, "WGS84")

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
		db.execute(query, ("gpkg_tiles", "tiles", self.name, "Created with BlenderGIS", self.xmin, self.ymin, self.xmax, self.ymax, self.code))
		db.commit()
		db.close()


	def insertCRS(self, code, name, auth='EPSG', wkt=''):
		db = sqlite3.connect(self.dbPath)
		db.execute(""" INSERT INTO gpkg_spatial_ref_sys (
					srs_id,
					organization,
					organization_coordsys_id,
					srs_name,
					definition)
				VALUES (?, ?, ?, ?, ?)
			""", (code, auth, code, name, wkt))
		db.commit()
		db.close()


	def insertTileMatrixSet(self):
		db = sqlite3.connect(self.dbPath)

		#Tile matrix set
		query = """INSERT OR REPLACE INTO gpkg_tile_matrix_set (
					table_name, srs_id,
					min_x, min_y, max_x, max_y)
				VALUES (?, ?, ?, ?, ?, ?);"""
		db.execute(query, ('gpkg_tiles', self.code, self.xmin, self.ymin, self.xmax, self.ymax))


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
		if CRS(self.CRS).isGeo:
			self.units = 'degrees'
		else: #(if units cannot be determined we assume its meters)
			self.units = 'meters'


	@property
	def globalbbox(self):
		return self.xmin, self.ymin, self.xmax, self.ymax


	def geoToProj(self, long, lat):
		"""convert longitude latitude un decimal degrees to grid crs"""
		if self.CRS == 'EPSG:4326':
			return long, lat
		else:
			return reprojPt(4326, self.CRS, long, lat)

	def projToGeo(self, x, y):
		"""convert grid crs coords to longitude latitude in decimal degrees"""
		if self.CRS == 'EPSG:4326':
			return x, y
		else:
			return reprojPt(self.CRS, 4326, x, y)


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
		return self.getFromToResFac(z, z-1)

	def getNextResFac(self, z):
		"""return res factor to next zoom level"""
		return self.getFromToResFac(z, z+1)

	def getFromToResFac(self, z1, z2):
		"""return res factor from z1 to z2"""
		if z1 == z2:
			return 1
		if z1 < z2:
			if z2 >= self.nbLevels - 1:
				return 1
			else:
				return self.getRes(z2) / self.getRes(z1)
		elif z1 > z2:
			if z2 <= 0:
				return 1
			else:
				return self.getRes(z2) / self.getRes(z1)

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

	# resampling algo for reprojection
	RESAMP_ALG = 'BL' #NN:Nearest Neighboor, BL:Bilinear, CB:Cubic, CBS:Cubic Spline, LCZ:Lanczos

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
		self.report = None


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
			if self.urlTemplate['VERSION'] == '1.3.0' and tm.CRS == 'EPSG:4326':
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
			try:
				_bbox = reprojBbox(crs2, crs1, bbox)
			except Exception as e:
				print('WARN : cannot reproj tile bbox - ' + str(e))
				return None

			#list, download and merge the tiles required to build this one (recursive call)
			mosaic = self.getImage(laykey, _bbox, _zoom, toDstGrid=False, useCache=True, nbThread=4, cpt=False, allowEmptyTile=False)

			if mosaic is None:
				return None

			tileSize = self.dstTms.tileSize

			img = reprojImg(crs1, crs2, mosaic, out_ul=(xmin,ymax), out_size=(tileSize,tileSize), out_res=res, resamplAlg=self.RESAMP_ALG)

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
			geoimg = reprojImg(tm.CRS, outCRS, geoimg, resamplAlg=self.RESAMP_ALG)

		if self.running:
			return geoimg
		else:
			return None




def reprojImg(crs1, crs2, geoimg, out_ul=None, out_size=None, out_res=None, resamplAlg='BL'):
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
	prj1 = CRS(crs1).getOgrSpatialRef()
	wkt1 = prj1.ExportToWkt()
	ds1.SetProjection(wkt1)

	#Build destination dataset
	# ds2 will be a template empty raster to reproject the data into
	# we can directly set its size, res and top left coord as expected
	# reproject funtion will match the template (clip and resampling)

	if out_ul is not None:
		xmin, ymax = out_ul
	else:
		xmin, ymax = reprojPt(crs1, crs2, xmin, ymax)

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
	prj2 = CRS(crs2).getOgrSpatialRef()
	wkt2 = prj2.ExportToWkt()
	ds2.SetProjection(wkt2)

	#Perform the projection/resampling
	# Resample algo
	if resamplAlg == 'NN' : alg = gdal.GRA_NearestNeighbour
	elif resamplAlg == 'BL' : alg = gdal.GRA_Bilinear
	elif resamplAlg == 'CB' : alg = gdal.GRA_Cubic
	elif resamplAlg == 'CBS' : alg = gdal.GRA_CubicSpline
	elif resamplAlg == 'LCZ' : alg = gdal.GRA_Lanczos
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

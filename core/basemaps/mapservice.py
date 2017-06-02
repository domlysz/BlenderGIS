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
import threading
import queue
import time
import urllib.request
import imghdr

#core imports
from .servicesDefs import GRIDS, SOURCES
from .gpkg import GeoPackage
from ..georaster import NpImage, GeoRef
from ..utils import BBOX
from ..proj.reproj import reprojPt, reprojBbox, reprojImg
from ..proj.ellps import dd2meters, meters2dd
from ..proj.srs import SRS



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
		if SRS(self.CRS).isGeo:
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
		self.running = False #flag using to stop getTiles() / getImage() process
		self.nbTiles = 0
		self.cptTiles = 0

		#codes that indicate the current status of the service
		# 0 = no running tasks
		# 1 = getting cache (create a new db if needed)
		# 2 = downloading
		# 3 = building mosaic
		# 4 = reprojecting
		self.status = 0

	@property
	def report(self):
		if self.status == 0:
			return ''
		if self.status == 1:
			return 'Get cache database...'
		if self.status == 2:
			return 'Downloading... ' + str(self.cptTiles)+'/'+str(self.nbTiles)
		if self.status == 3:
			return 'Building mosaic...'
		if self.status == 4:
			return 'Reprojecting...'


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

			img = reprojImg(crs1, crs2, mosaic, out_ul=(xmin,ymax), out_size=(tileSize,tileSize), out_res=res, sqPx=True, resamplAlg=self.RESAMP_ALG)

			#Get BLOB
			data = img.toBLOB()

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

		#Get cache db
		self.status = 1
		if useCache:
			cache = self.getCache(laykey, toDstGrid)
			result = cache.getTiles(tiles) #return [(x,y,z,data)]
			existing = set([ r[:-1] for r in result])
			missing = [t for t in tiles if t not in existing]
			if cpt:
				self.cptTiles += len(result)
		else:
			missing = tiles

		#Downloading tiles
		self.status = 2
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

		#Add existing tiles to final list
		if useCache:
			tilesData.extend(result)

		#Reinit status and cpt progress
		self.status = 0
		if cpt:
			self.nbTiles, self.cptTiles = 0, 0

		return tilesData



	def getImage(self, laykey, bbox, zoom, toDstGrid=True, useCache=True, nbThread=10, cpt=True, outCRS=None, allowEmptyTile=True):
		"""
		Build a mosaic of tiles covering the requested bounding box
		return georeferenced NpImage object
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

		#Create numpy image in memory
		img_w, img_h = len(cols) * tileSize, len(rows) * tileSize
		georef = GeoRef((img_w, img_h), (res, -res), (xmin, ymax), pxCenter=False, crs=None)
		mosaic = NpImage.new(img_w, img_h, bkgColor=(255,255,255,255), georef=georef)

		#Get tiles from www or cache
		tiles = [ (c, r, zoom) for c in cols for r in rows]
		tiles = self.getTiles(laykey, tiles, [], toDstGrid, useCache, nbThread, cpt)

		#Build mosaic
		self.status = 3
		for tile in tiles:

			if not self.running:
				self.status = 0
				return None

			col, row, z, data = tile
			if data is None:
				#create an empty tile
				if allowEmptyTile:
					img = NpImage.new(tileSize, tileSize, bkgColor=(128,128,128,255))
				else:
					return None
			else:
				try:
					img = NpImage(data)
				except Exception as e:
					print(str(e))
					if allowEmptyTile:
						#create an empty tile if we are unable to get a valid stream
						img = NpImage.new(tileSize, tileSize, bkgColor=(255,192,203,255))
					else:
						return None
			posx = (col - firstCol) * tileSize
			posy = abs((row - firstRow)) * tileSize
			mosaic.paste(img, posx, posy)

		#Reproject if needed
		if outCRS is not None and outCRS != tm.CRS:
			self.status = 4
			time.sleep(0.1) #make sure client have enough time to get the new status...
			mosaic = NpImage(reprojImg(tm.CRS, outCRS, mosaic.toGDAL(),  sqPx=True, resamplAlg=self.RESAMP_ALG))

		#Finish
		self.status = 0
		if self.running:
			return mosaic
		else:
			return None

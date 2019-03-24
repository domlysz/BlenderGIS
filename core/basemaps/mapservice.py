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
import logging
log = logging.getLogger(__name__)

import math
import threading
import queue
import time
import urllib.request
import imghdr
import sys, time, os

#core imports
from .servicesDefs import GRIDS, SOURCES
from .gpkg import GeoPackage
from ..georaster import NpImage, GeoRef, BigTiffWriter
from ..utils import BBOX
from ..proj.reproj import reprojPt, reprojBbox, reprojImg
from ..proj.ellps import dd2meters, meters2dd
from ..proj.srs import SRS

from ..settings import getSetting
USER_AGENT = getSetting('user_agent')

# Set mosaic backgroung image color, it will be the base color for area not covered
# by the map service (ie when requests return non valid data)
MOSAIC_BKG_COLOR = (128,128,128,255)

EMPTY_TILE_COLOR = (255,192,203,255) #color for cached tile with empty data
CORRUPTED_TILE_COLOR = (255,0,0,255) #color for cached tile which is non valid image data

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
		self.crs = SRS(self.CRS)
		if self.crs.isGeo:
			self.units = 'degrees'
		else: #(if units cannot be determined we assume its meters)
			self.units = 'meters'


	@property
	def globalbbox(self):
		return self.xmin, self.ymin, self.xmax, self.ymax


	def geoToProj(self, long, lat):
		"""convert longitude latitude in decimal degrees to grid crs"""
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


	def bboxRequest(self, bbox, zoom):
		return BBoxRequest(self, bbox, zoom)

class BBoxRequestMZ():
	'''Multiple Zoom BBox request'''
	def __init__(self, tm, bbox, zooms):

		self.tm = tm
		self.bboxrequests = {}
		for z in zooms:
			self.bboxrequests[z] = BBoxRequest(tm, bbox, z)

	@property
	def tiles(self):
		tiles = []
		for bboxrequest in self.bboxrequests.values():
			tiles.extend(bboxrequest.tiles)
		return tiles

	@property
	def nbTiles(self):
		return len(self.tiles)

	def __getitem__(self, z):
		return self.bboxrequests[z]


class BBoxRequest():

	def __init__(self, tm, bbox, zoom):

		self.tm = tm
		self.zoom = zoom
		self.tileSize = tm.tileSize
		self.res = tm.getRes(zoom)

		xmin, ymin, xmax, ymax = bbox

		#Get first tile indices (top left of requested bbox)
		self.firstCol, self.firstRow = tm.getTileNumber(xmin, ymax, zoom)

		#correction of top left coord
		xmin, ymax = tm.getTileCoords(self.firstCol, self.firstRow, zoom)
		self.bbox = BBOX(xmin, ymin, xmax, ymax)

		#Total number of tiles required
		self.nbTilesX = math.ceil( (xmax - xmin) / (self.tileSize * self.res) )
		self.nbTilesY = math.ceil( (ymax - ymin) / (self.tileSize * self.res) )

	@property
	def cols(self):
		return [self.firstCol+i for i in range(self.nbTilesX)]

	@property
	def rows(self):
		if self.tm.originLoc == "NW":
			return [self.firstRow+i for i in range(self.nbTilesY)]
		else:
			return [self.firstRow-i for i in range(self.nbTilesY)]

	@property
	def tiles(self):
		return [(c, r, self.zoom) for c in self.cols for r in self.rows]

	@property
	def nbTiles(self):
		return self.nbTilesX * self.nbTilesY

	#megapixel, geosize



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

	Service status code
		0 = no running tasks
		1 = getting cache (create a new db if needed)
		2 = downloading
		3 = building mosaic
		4 = reprojecting
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
			'User-Agent' : USER_AGENT,
			'Referer' : self.referer}

		#Downloading progress
		self.running = False #flag using to stop getTiles() / getImage() process
		self.nbTiles = 0
		self.cptTiles = 0

		#codes that indicate the current status of the service
		self.status = 0

		self.lock = threading.RLock()

	def reportLoop(self):
		msg = self.report
		while self.running:
			time.sleep(0.05)
			if self.report != msg:
				#sys.stdout.write("\033[F") #back to previous line
				sys.stdout.write("\033[K") #clear line
				sys.stdout.flush()
				print(self.report, end='\r') #'\r' will move the cursor back to the beginning of the line
				msg = self.report

	def start(self):
		self.running = True
		reporter = threading.Thread(target=self.reportLoop)
		reporter.setDaemon(True) #daemon threads will die when the main non-daemon thread have exited.
		reporter.start()

	def stop(self):
		self.running = False

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
			dbPath = os.path.join(self.cacheFolder, mapKey + ".gpkg")
			self.caches[mapKey] = GeoPackage(dbPath, tm)
			return self.caches[mapKey]
		else:
			return cache

	def getTM(self, dstGrid=False):
		if dstGrid:
			if self.dstTms is not None:
				return self.dstTms
			else:
				raise ValueError('No destination grid defined')
		else:
			return self.srcTms


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


	def isTileInMapsBounds(self, col, row, zoom, tm):
		'''Test if the tile is not out of tile matrix bounds'''
		x,y = tm.getTileCoords(col, row, zoom) #top left
		if row < 0 or col < 0:
			return False
		elif not tm.xmin <= x < tm.xmax or not tm.ymin < y <= tm.ymax:
			return False
		else:
			return True


	def downloadTile(self, laykey, col, row, zoom):
		"""
		Download bytes data of requested tile in source tile matrix space
		Return None if unable to download a valid stream
		"""

		url = self.buildUrl(laykey, col, row, zoom)
		log.debug(url)

		try:
			#make request
			req = urllib.request.Request(url, None, self.headers)
			handle = urllib.request.urlopen(req, timeout=3)
			#open image stream
			data = handle.read()
			handle.close()
		except Exception as e:
			log.error("Can't download tile x{} y{}. Error {}".format(col, row, e))
			data = None

		#Make sure the stream is correct
		if data is not None:
			format = imghdr.what(None, data)
			if format is None:
				data = None

		if data is None:
			log.debug("Invalid tile data for request {}".format(url))

		return data


	def tileRequest(self, laykey, col, row, zoom, toDstGrid=True):
		"""
		Return bytes data of the requested tile or None if unable to get valid data
		Tile is downloaded from map service and, if needed, reprojected to fit the destination grid
		"""

		#Select tile matrix set
		tm = self.getTM(toDstGrid)

		#don't try to get tiles out of map bounds
		if not self.isTileInMapsBounds(col, row, zoom, tm):
			return None

		if not toDstGrid:
			data = self.downloadTile(laykey, col, row, zoom)
		else:
			data = self.buildDstTile(laykey, col, row, zoom)

		return data


	def buildDstTile(self, laykey, col, row, zoom):
		'''build a tile that fit the destination tile matrix'''

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
			log.warning('Cannot reproj tile bbox - ' + str(e))
			return None

		#list, download and merge the tiles required to build this one (recursive call)
		mosaic = self.getImage(laykey, _bbox, _zoom, toDstGrid=False, nbThread=4, cpt=False, allowEmptyTile=False)

		if mosaic is None:
			return None

		#Reprojection
		tileSize = self.dstTms.tileSize
		img = NpImage(reprojImg(crs1, crs2, mosaic.toGDAL(), out_ul=(xmin,ymax), out_size=(tileSize,tileSize), out_res=res, sqPx=True, resamplAlg=self.RESAMP_ALG))

		return img.toBLOB()




	def seedTiles(self, laykey, tiles, toDstGrid=True, nbThread=10, buffSize=5000, cpt=True):
		"""
		Seed the cache by downloading the requested tiles from map service
		Downloads are performed through thread to speed up

		buffSize : maximum number of tiles keeped in memory before put them in cache database
		"""

		def downloading(laykey, tilesQueue, tilesData, toDstGrid):
			'''Worker that process the queue and seed tilesData array [(x,y,z,data)]'''
			#infinite loop that processes items into the queue
			while not tilesQueue.empty(): #empty is True if all item was get but it not tell if all task was done
				#cancel thread if requested
				if not self.running:
					break
				#Get a job into the queue
				col, row, zoom = tilesQueue.get() #get() pop the item from queue
				#do the job
				data = self.tileRequest(laykey, col, row, zoom, toDstGrid)
				if data is not None:
					tilesData.put( (col, row, zoom, data) ) #will block if the queue is full
				if cpt:
					self.cptTiles += 1
				#self.nTaskDone += 1
				#flag it's done
				tilesQueue.task_done() #it's just a count of finished tasks used by join() to know if the work is finished

		def finished():
			#return self.nTaskDone == nMissing
			#self.nTaskDone is not reliable because the recursive call to getImage will
			#start multiple threads to seedTiles() and all these process will increments nTaskDone
			return not any([t.is_alive() for t in threads])

		def putInCache(tilesData, jobs, cache):
			while True:
				if tilesData.full() or \
				( (finished() or not self.running) and not tilesData.empty()):
					data = [tilesData.get() for i in range(tilesData.qsize())]
					with self.lock:
						cache.putTiles(data)
				if finished() and tilesData.empty():
					break
				if not self.running:
					break

		if cpt:
			#init cpt progress
			self.nbTiles = len(tiles)
			self.cptTiles = 0

		#self.nTaskDone = 0

		#Get cache db
		if cpt:
			self.status = 1
		cache = self.getCache(laykey, toDstGrid)
		missing = cache.listMissingTiles(tiles)
		nMissing = len(missing)
		nExists = self.nbTiles - len(missing)
		log.debug("{} tiles requested, {} already in cache, {} remains to download".format(self.nbTiles, nExists, nMissing))
		if cpt:
			self.cptTiles += nExists

		#Downloading tiles
		if cpt:
			self.status = 2
		if len(missing) > 0:

			#Result queue
			tilesData = queue.Queue(maxsize=buffSize)

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

			seeder = threading.Thread(target=putInCache, args=(tilesData, jobs, cache))
			seeder.setDaemon(True)
			seeder.start()
			seeder.join()

			#Make sure all threads has finished
			for t in threads:
				t.join()

		#Reinit status and cpt progress
		if cpt:
			self.status = 0
			self.nbTiles, self.cptTiles = 0, 0


	def getTiles(self, laykey, tiles, toDstGrid=True, nbThread=10, cpt=True):
		"""
		Return bytes data of requested tiles
		input: [(x,y,z)] >> output: [(x,y,z,data)]
		Tiles are downloaded from map service or directly pick up from cache database.
		"""
		#seed the cache
		self.seedTiles(laykey, tiles, toDstGrid=toDstGrid, nbThread=10, cpt=cpt)
		#request the cache and return
		cache = self.getCache(laykey, toDstGrid)
		return cache.getTiles(tiles) #[(x,y,z,data)]


	def getTile(self, laykey, col, row, zoom, toDstGrid=True):
		return self.getTiles(laykey, [col, row, zoom], toDstGrid)[0]


	def bboxRequest(self, bbox, zoom, dstGrid=True):
		#Select tile matrix set
		tm = self.getTM(dstGrid)
		return BBoxRequest(tm, bbox, zoom)


	def seedCache(self, laykey, bbox, zoom, toDstGrid=True, nbThread=10, buffSize=5000):
		"""
		Seed the cache with the tiles covering the requested bbox
		"""
		#Select tile matrix set
		tm = self.getTM(toDstGrid)
		if isinstance(zoom, list):
			rq = BBoxRequestMZ(tm, bbox, zoom)
		else:
			rq = BBoxRequest(tm, bbox, zoom)
		self.seedTiles(laykey, rq.tiles, toDstGrid=toDstGrid, nbThread=10, buffSize=5000)


	def getImage(self, laykey, bbox, zoom, path=None, bigTiff=False, outCRS=None, toDstGrid=True, nbThread=10, cpt=True):
		"""
		Build a mosaic of tiles covering the requested bounding box
		#laykey (str)
		#bbox
		#zoom (int)
		#path (str): if None the function will return a georeferenced NpImage object. If not None, then the resulting output will be
		writen as geotif file on disk and the function will return None
		#bigTiff (bool): if true then the raster will be writen by small part with the help of GDAL API. If false the raster will be
		writen at one, in this case all the tiles must fit in memory otherwise it will raise a memory overflow error
		#outCRS : destination CRS if a reprojection if expected (require GDAL support)
		#toDstGrid (bool) : decide if the function will seed the destination tile matrix sets for this MapService instance
		(different from the source tile matrix set)
		#nbThread (int) : nimber of threads that will be used for downloading tiles
		#cpt (bool) : define if the service must report or not tiles downloading count for this request
		"""

		#Select tile matrix set
		tm = self.getTM(toDstGrid)

		#Get request
		rq = BBoxRequest(tm, bbox, zoom)
		tileSize = rq.tileSize
		res = rq.res
		cols, rows = rq.cols, rq.rows
		rqTiles = rq.tiles #[(x,y,z)]

		##method 1) Seed the cache with all required tiles
		self.seedCache(laykey, bbox, zoom, toDstGrid=toDstGrid, nbThread=nbThread, buffSize=5000)
		cache = self.getCache(laykey, toDstGrid)

		if not self.running:
			if cpt:
				self.status = 0
			return

		#Get georef parameters
		img_w, img_h = len(cols) * tileSize, len(rows) * tileSize
		xmin, ymin, xmax, ymax = rq.bbox
		georef = GeoRef((img_w, img_h), (res, -res), (xmin, ymax), pxCenter=False, crs=tm.crs)

		if bigTiff and path is None:
			raise ValueError('No output path defined for creating bigTiff')

		if not bigTiff:
			#Create numpy image in memory
			mosaic = NpImage.new(img_w, img_h, bkgColor=MOSAIC_BKG_COLOR, georef=georef)
			chunkSize = rq.nbTiles
		else:
			#Create bigtiff file on disk
			mosaic = BigTiffWriter(path, img_w, img_h, georef)
			ds = mosaic.ds
			chunkSize = 5 #number of tiles to extract in one cache request

		#Build mosaic
		for i in range(0, rq.nbTiles, chunkSize):
			chunkTiles = rqTiles[i:i+chunkSize]

			##method 1) Get cached tiles
			tiles = cache.getTiles(chunkTiles) #[(x,y,z,data)]

			##method 2) Get tiles from www or cache (all tiles must fit in memory)
			#tiles = self.getTiles(laykey, chunkTiles, toDstGrid, nbThread, cpt)

			if cpt:
				self.status = 3
			for tile in tiles:

				if not self.running:
					if cpt:
						self.status = 0
					return None

				col, row, z, data = tile

				#TODO corrupted or empty tiles must be deleted from cache are fetched again
				if data is None:
					#create an empty tile
					img = NpImage.new(tileSize, tileSize, bkgColor=EMPTY_TILE_COLOR)
				else:
					try:
						img = NpImage(data)
					except Exception as e:
						log.error('Corrupted tile on cache', exc_info=True)
						#create an empty tile if we are unable to get a valid stream
						img = NpImage.new(tileSize, tileSize, bkgColor=CORRUPTED_TILE_COLOR)


				posx = (col - rq.firstCol) * tileSize
				posy = abs((row - rq.firstRow)) * tileSize
				mosaic.paste(img, posx, posy)

		if not self.running:
			if cpt:
				self.status = 0
			return None

		#Reproject if needed
		if outCRS is not None and outCRS != tm.CRS:
			if cpt:
				self.status = 4
			time.sleep(0.1) #make sure client have enough time to get the new status...

			if not bigTiff:
				mosaic = NpImage(reprojImg(tm.CRS, outCRS, mosaic.toGDAL(), sqPx=True, resamplAlg=self.RESAMP_ALG))
			else:
				outPath = path[:-4] + '_' + str(outCRS) + '.tif'
				ds = reprojImg(tm.CRS, outCRS, mosaic.ds, sqPx=True, resamplAlg=self.RESAMP_ALG, path=outPath)

		#build overviews for file output
		if bigTiff:
			ds.BuildOverviews(overviewlist=[2,4,8,16,32])
			ds = None

		if not bigTiff and path is not None:
			mosaic.save(path)

		#Finish
		if cpt:
			self.status = 0
		if path is None:
			return mosaic
		else:
			return None

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
import datetime
import sqlite3
import urllib.request

#bpy imports
import bpy
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_vector_3d
import blf, bgl

#deps imports
from PIL import Image
try:
	from osgeo import osr
except:
	PROJ = False
else:
	PROJ = True

#addon import
from .servicesDefs import grids, sources


####################################

class MBTiles():
	"""
	specs :
	https://github.com/mapbox/mbtiles-spec

	this classe is a quick mashup from these sources :
	https://github.com/mapbox/mbutil/blob/master/mbutil/util.py
	https://github.com/ecometrica/gdal2mbtiles/blob/master/gdal2mbtiles/mbtiles.py
	https://github.com/mapproxy/mapproxy/blob/master/mapproxy/cache/mbtiles.py
	https://github.com/TileStache/TileStache/blob/master/TileStache/MBTiles.py  
	"""

	MAX_DAYS = 90

	def __init__(self, path):
		#self.dbPath = path + name + ".mbtiles"
		self.dbPath = path
		if not self.isMBtiles():
			self.createMBtiles()
			self.addMetadata()


	def isMBtiles(self):
		if not os.path.exists(self.dbPath):
			return False	
		db = sqlite3.connect(self.dbPath)
		try:
			db.execute('SELECT name, value FROM metadata LIMIT 1')
			db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles LIMIT 1')
		except:
			db.close()
			return False
		else:
			db.close()
			return True		


	def createMBtiles(self):
		db = sqlite3.connect(self.dbPath) #this attempt will create a new file if not exist
		cursor = db.cursor()
		cursor.execute("""CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, last_modified TIMESTAMP DEFAULT (datetime('now','localtime')) );""")
		cursor.execute("""CREATE TABLE metadata (name TEXT, value TEXT);""")
		cursor.execute("""CREATE UNIQUE INDEX name ON metadata (name);""")
		cursor.execute("""CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);""")
		db.commit()
		db.close()


	def addMetadata(self, name="", description="", type="baselayer", version=1.1, format='png', bounds='-180.0,-85,180,85'):
		db = sqlite3.connect(self.dbPath)
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('name', name))
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('type', type))
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('version', version))
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('description', description))
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('format', format))
		db.execute('INSERT INTO metadata VALUES (?, ?)', ('bounds', bounds))
		db.commit()
		db.close()

		
	def putTile(self, x, y, z, data):
		db = sqlite3.connect(self.dbPath)
		query = "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?,?,?,?)"
		db.execute(query, (z, x, y, data))
		db.commit()
		db.close()

			
	def getTile(self, x, y, z):
		#connect with detect_types parameter for automatically convert date to Python object
		db = sqlite3.connect(self.dbPath, detect_types=sqlite3.PARSE_DECLTYPES)
		query = 'SELECT tile_data, last_modified FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?'
		result = db.execute(query, (z, x, y)).fetchone()
		db.close()
		if result is None:
			return None
		timeDelta = datetime.datetime.now() - result[1]
		if timeDelta.days > self.MAX_DAYS:
			return None
		return result[0]



####################################

class Ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

GRS80 = Ellps(6378137, 6356752.314245)


def reproj(crs1, crs2, x1, y1):
	"""
	Reproject x1,y1 coords from crs1 to crs2 
	Actually support only lat long (decimel degrees) <--> web mercator
	Warning, latitudes 90° or -90° are outside web mercator bounds
	"""
	if crs1 == 4326 and crs2 == 3857:
		long, lat = x1, y1
		k = GRS80.perimeter/360
		x2 = long * k
		lat = math.log( math.tan((90 + lat) * math.pi / 360.0 )) / (math.pi / 180.0)
		y2 = lat * k
		return x2, y2
	elif crs1 == 3857 and crs2 == 4326:
		k = GRS80.perimeter/360
		long = x1 / k
		lat = y1 / k
		lat = 180 / math.pi * (2 * math.atan( math.exp( lat * math.pi / 180.0)) - math.pi / 2.0)
		return long, lat
	else:
		#need an external lib (pyproj or gdal osr) to support others crs
		if not PROJ:
			raise NotImplementedError
		else: #gdal osr
			prj1 = osr.SpatialReference()
			prj1.ImportFromEPSG(crs1)

			prj2 = osr.SpatialReference()
			prj2.ImportFromEPSG(crs2)

			transfo = osr.CoordinateTransformation(prj1, prj2)
			x2, y2, z2 = transfo.TransformPoint(x1, y1)
			return x2, y2


####################################



class TileMatrix():
	
	
	def __init__(self, gridDef):

		#create class attributes from grid dictionnary
		for k, v in gridDef.items():
			setattr(self, k, v)
		
		#Convert bbox to grid crs is needed
		if self.bboxCRS != self.CRS:
			if self.bboxCRS == 4326:
				lonMin, latMin, lonMax, latMax = self.bbox
				self.tm_xmin, self.tm_ymax = self.geoToProj(lonMin, latMax)
				self.tm_xmax, self.tm_ymin = self.geoToProj(lonMax, latMin)
			else:
				raise NotImplementedError
		else:
			self.tm_xmin, self.tm_xmax = self.bbox[0], self.bbox[2]
			self.tm_ymin, self.tm_ymax = self.bbox[1], self.bbox[3]

		#Get initial resolution
		if getattr(self, 'resolutions', None) is not None:
			pass
		else:
			if getattr(self, 'initRes', None) is not None:
				pass
			else:
				# at zoom level zero, 1 tile covers whole bounding box
				dx = abs(self.tm_xmax - self.tm_xmin)
				dy = abs(self.tm_ymax - self.tm_ymin)
				dst = max(dx, dy)
				self.initRes = dst / self.tileSize
		
		# Define tile matrix origin
		if self.originLoc == "NW":
			self.tm_ox, self.tm_oy = self.tm_xmin, self.tm_ymax
		elif self.originLoc == "SW":
			raise NotImplementedError
	

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


	def getRes(self, zoom):
		"""Resolution (meters/pixel) for given zoom level (measured at Equator)"""
		if getattr(self, 'resolutions', None) is not None:
			if zoom > len(self.resolutions):
				zoom = len(self.resolutions)
			return self.resolutions[zoom]
		else:
			return self.initRes / self.resFactor**zoom


	def getTileNumber(self, x, y, zoom):
		"""Convert projeted coords to tiles number"""
		res = self.getRes(zoom)
		geoTileSize = self.tileSize * res
		dx = x - self.tm_ox
		dy = self.tm_oy - y
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
		x = self.tm_ox + (col * geoTileSize)
		y = self.tm_oy - (row * geoTileSize)
		return x, y

####################################


class MapService(TileMatrix):
	"""
	Represent a tile service from source
	"""	
	
	def __init__(self, source):
		
		#create class attributes from source dictionnary
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
	
		#init parent grid class
		super().__init__(grids[self.grid])


	def buildUrl(self, layKey, col, row, zoom):
		url = self.urlTemplate
		lay = self.layers[layKey]
		
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
			url = url.replace("{CRS}", str(self.CRS))
			url = url.replace("{WIDTH}", str(self.tileSize))
			url = url.replace("{HEIGHT}", str(self.tileSize))
			
			xmin, ymax = self.getTileCoords(col, row, zoom)
			xmax = xmin + self.tileSize * self.getRes(zoom)
			ymin = ymax - self.tileSize * self.getRes(zoom)
			if self.urlTemplate['VERSION'] == '1.3.0' and self.CRS == 4326:
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





####################

class Map(MapService):
	"""Handle a map as background image in Blender"""
	
	
	def __init__(self, context):

		#Get context
		self.scn = context.scene
		self.area = context.area
		self.area3d = [r for r in self.area.regions if r.type == 'WINDOW'][0]
		self.view3d = self.area.spaces.active
		self.reg3d = self.view3d.region_3d
		
		#Get tool props stored in scene
		folder = self.scn.cacheFolder
		mapKey = self.scn.mapSource
		self.srcKey, self.layKey = mapKey.split(':')

		#Init parent MapService class
		super().__init__(sources[self.srcKey])
	
		#Get layer def obj
		self.layer = self.layers[self.layKey]
			
		#Paths
		mapKey = mapKey.replace(':', '_')
		# MBtiles database path
		self.dbPath = folder + mapKey+ ".mbtiles"
		# Tiles mosaic used as background image in Blender
		self.imgPath = folder + mapKey + ".png"
		
		#Init cache
		self.cache = MBTiles(self.dbPath)

		#Init scene props if not exists
		scn = self.scn
		# scene origin lat long
		if "lat" not in scn and "long" not in scn:
			scn["lat"], scn["long"] = 0.0, 0.0 #explit float for id props
		# zoom level
		if 'z' not in scn:
			scn["z"] = 0
		# EPSG code or proj4 string
		if 'CRS' not in scn:
			scn["CRS"] = '3857' #epsg code web mercator (string id props)
		# scale
		if 'scale' not in scn:
			scn["scale"] = 1 #1:1

		#Read scene props
		self.update()

		#Fake browser header
		self.headers = {
			'Accept' : 'image/png,image/*;q=0.8,*/*;q=0.5' ,
			'Accept-Charset' : 'ISO-8859-1,utf-8;q=0.7,*;q=0.7' ,
			'Accept-Encoding' : 'gzip,deflate' ,
			'Accept-Language' : 'fr,en-us,en;q=0.5' ,
			'Keep-Alive': 115 ,
			'Proxy-Connection' : 'keep-alive' ,
			'User-Agent' : 'Mozilla/5.0 (Windows; U; Windows NT 5.1; fr; rv:1.9.2.13) Gecko/20101003 Firefox/12.0',
			'Referer' : self.referer}

		#Thread attributes
		self.running = False
		self.thread = None
		#Background image attributes
		self.img = None #bpy image
		self.bkg = None #bpy background
		self.img_w, self.img_h = None, None #width, height
		self.img_ox, self.img_oy = None, None #image origin
		#Store list of previous tile number requested
		self.previousNumColLst, self.previousNumRowLst = None, None


	@property
	def res(self):
		'''Resolution in meters per pixel for current zoom level'''
		return self.getRes(self.zoom)


	def update(self):
		'''Read scene properties and update attributes'''
		#get scene props
		self.zoom = self.scn['z']
		self.scale = self.scn['scale']
		self.lat, self.long = self.scn['lat'], self.scn['long']

		#scene origin coords in projeted system
		self.origin_x, self.origin_y = self.geoToProj(self.long, self.lat)

		#reinit thread progress cpt
		self.cptTiles = 0
		self.nbTiles = 0



	def get(self):
		'''Launch run() function in a new thread'''
		self.stop()
		self.running = True
		self.thread = threading.Thread(target=self.run)
		self.thread.start()

	def stop(self):
		'''Stop actual thread'''
		if self.running:
			self.running = False
			self.thread.join()

	def run(self):
		'''Main process'''
		if self.running:
			self.update()
		if self.running:
			self.request()
		if self.running:
			self.load()
		if self.running:
			self.place()

	def progress(self):
		'''Report thread download progress'''
		return self.cptTiles, self.nbTiles	



	def view3dToProj(self, dx, dy):
		'''Convert view3d coords to crs coords'''
		x = self.origin_x + dx
		y = self.origin_y + dy	
		return x, y

	def moveOrigin(self, dx, dy):
		'''Move scene origin and update props'''
		self.origin_x += dx
		self.origin_y += dy
		lon, lat = self.projToGeo(self.origin_x, self.origin_y)
		self.scn["lat"], self.scn["long"] = lat, lon


		
	def request(self):
		'''Compute list of required tiles to cover view3d area'''
		#Get area dimension
		#w, h = self.area.width, self.area.height		
		w, h = self.area3d.width, self.area3d.height
		
		#Get area top left coords ((map origin is bottom lelf)
		x_shift = self.origin_x - w/2 * self.res
		y_shift = self.origin_y + h/2 * self.res
		
		#Get first tile indices (tiles matrix origin is top left)
		firstCol, firstRow = self.getTileNumber(x_shift, y_shift, self.zoom)
		
		#Total number of tiles required
		nbTilesX, nbTilesY = math.ceil(w/self.tileSize), math.ceil(h/self.tileSize)
			
		#Add more tiles because background image will be offseted 
		# and could be to small to cover all area
		nbTilesX += 1
		nbTilesY += 1
		
		#Final image size
		self.img_w, self.img_h = nbTilesX * self.tileSize, nbTilesY * self.tileSize
		
		#Compute image origin
		#Image origin will not match scene origin, it's why we should offset the image
		xmin, ymax = self.getTileCoords(firstCol, firstRow, self.zoom) #top left (px center ?)
		self.img_ox = xmin + self.img_w/2 * self.res
		self.img_oy = ymax - self.img_h/2 * self.res

		#Build list of required column and row numbers
		self.numColLst = [firstCol+i for i in range(nbTilesX)]
		self.numRowLst = [firstRow+i for i in range(nbTilesY)]
		
		#Stop thread if the request is same as previous
		if self.previousNumColLst == self.numColLst and self.previousNumRowLst == self.numRowLst:
			self.running = False
		else:
			self.previousNumColLst = self.numColLst
			self.previousNumRowLst = self.numRowLst


	def load(self):
		'''
		Build requested background image (mosaic of tiles)
		Tiles are downloaded from map service or directly taken in cache database.
		'''
		#Create PIL image in memory
		mosaic = Image.new("RGBA", (self.img_w , self.img_h), None)

		nbTilesX = len(self.numColLst)
		nbTilesY = len(self.numRowLst)
		self.nbTiles = nbTilesX * nbTilesY
		self.cptTiles = 0
		
		posy = 0
		for row in self.numRowLst:
			
			posx = 0
			
			for col in self.numColLst:

				#cancel thread if requested
				if not self.running:
					return
				
				#don't try to get tiles out of map bounds
				x,y = self.getTileCoords(col, row, self.zoom) #top left
				if row < 0 or col < 0:
					data = None
				elif not self.tm_xmin <= x < self.tm_xmax or not self.tm_ymin < y <= self.tm_ymax:
					data = None
				
				else:
					
					#check if tile already exists in cache
					data = self.cache.getTile(col, row, self.zoom)
					
					#if so try to open it with PIL
					if data is not None:
						try:
							img = Image.open(io.BytesIO(data))
						except: #corrupted
							data = None
						
					#if not or corrupted try to download it from map service			
					if data is None:
					
						url = self.buildUrl(self.layKey, col, row, self.zoom)
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
							#print(url)
							data = None
					
						#Make sure the stream is correct and put in db
						if data is not None:
							try:
								#open with PIL
								img = Image.open(io.BytesIO(data))
							except:
								data = None
							else:
								#put in mbtiles database
								self.cache.putTile(col, row, self.zoom, data)
						
				#finally, if we are unable to get a valid stream
				#then create an empty tile
				if data is None:
					img = Image.new("RGBA", (self.tileSize , self.tileSize), "white")
				
				#Paste tile into mosaic image
				mosaic.paste(img, (posx, posy))
				self.cptTiles += 1
				posx += self.tileSize
			#
			posy += self.tileSize
			
		#save image
		mosaic.save(self.imgPath)

		#reinit cpt progress
		self.cptTiles = 0
		self.nbTiles = 0
		
		

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

		#Set some props
		self.bkg.show_background_image = True
		self.bkg.view_axis = 'TOP'
		self.bkg.opacity = 1
		
		#Set background size
		sizex = self.img_w * self.res / self.scale
		self.bkg.size = sizex #since blender > 2.74 else = sizex/2
		
		#Set background offset (image origin does not match scene origin)
		dx = (self.origin_x - self.img_ox) / self.scale
		dy = (self.origin_y - self.img_oy) / self.scale
		self.bkg.offset_x = -dx
		ratio = self.img_w / self.img_h
		self.bkg.offset_y = -dy * ratio #https://developer.blender.org/T48034
	
		#Compute view3d z distance
		#in ortho view, view_distance = max(view3d dst x, view3d dist y) / 2
		dst =  max( [self.area3d.width, self.area3d.height] )
		dst = dst * self.res / self.scale
		dst /= 2
		self.reg3d.view_distance = dst
		
		#Update image drawing	
		self.bkg.image.reload()





####################################


def draw_callback(self, context):
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
	zoom = scn['z']
	lat, long = scn['lat'], scn['long']
	scale = scn['scale']

	#Set text police and color
	font_id = 0  # ???
	bgl.glColor4f(*scn.fontColor) #rgba
	
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



class MAP_VIEW(bpy.types.Operator):

	bl_idname = "view3d.map_view"
	bl_description = 'Toggle 2d map navigation'
	bl_label = "Map viewer"


	def invoke(self, context, event):
		
		if context.area.type == 'VIEW_3D':
			
			#Add draw callback to view space
			args = (self, context)
			self._handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback, args, 'WINDOW', 'POST_PIXEL')

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
	
			#Get map
			try:
				self.map = Map(context)
			except Exception as e:
				self.report({'ERROR'}, str(e))
				return {'CANCELLED'}
			
			self.map.get()
			
			return {'RUNNING_MODAL'}
		
		else:
			
			self.report({'WARNING'}, "View3D not found, cannot run operator")
			return {'CANCELLED'}


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
					scn['scale'] *= 10
					self.map.scale = scn['scale']
					self.map.place()
				
				elif event.ctrl:
					# view3d zoom up
					context.region_data.view_distance -= 100
				
				else:
					# map zoom up
					if scn["z"] < self.map.layer.zmax:
						scn["z"] += 1
						self.map.get()
	
		if event.type in ['WHEELDOWNMOUSE', 'NUMPAD_MINUS']:
			
			if event.value == 'PRESS':
				
				if event.alt:
					#map scale down
					s = scn['scale'] / 10
					if s < 1: s = 1
					scn['scale'] = s
					self.map.scale = s
					self.map.place()
					
				elif event.ctrl:
					#view3d zoom down
					context.region_data.view_distance += 100
					
				else:
					#map zoom down			
					if scn["z"] > self.map.layer.zmin:
						scn["z"] -= 1
						self.map.get()

		if event.type == 'MOUSEMOVE':
			
			#Report mouse location coords in projeted crs
			loc = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
			self.posx, self.posy = self.map.view3dToProj(loc.x, loc.y)
			
			#Drag background image (edit its offset values)
			if self.inMove and self.map.bkg is not None:
				loc1 = self.mouseTo3d(context, self.x1, self.y1)
				loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
				dx = loc1.x - loc2.x
				dy = loc1.y - loc2.y
				ratio = self.map.img_w / self.map.img_h
				self.map.bkg.offset_x = -dx + self.offset_x
				self.map.bkg.offset_y = (-dy * ratio) + self.offset_y
					
		if event.type in {'LEFTMOUSE', 'MIDDLEMOUSE'}:
			
			if event.value == 'PRESS':
				#Stop thread now, because we don't know when the mouse click will be released
				self.map.stop()
				#Get click mouse position and background image offset (if exist)
				self.x1, self.y1 = event.mouse_region_x, event.mouse_region_y
				if self.map.bkg is not None:
					self.offset_x = self.map.bkg.offset_x
					self.offset_y = self.map.bkg.offset_y
				#Tag that map is currently draging
				self.inMove = True
				
			if event.value == 'RELEASE':
				self.inMove = False
				#Compute final shift
				loc1 = self.mouseTo3d(context, self.x1, self.y1)
				loc2 = self.mouseTo3d(context, event.mouse_region_x, event.mouse_region_y)
				dx = (loc1.x - loc2.x) * self.map.scale
				dy = (loc1.y - loc2.y) * self.map.scale
				#Update map
				self.map.moveOrigin(dx,dy)
				self.map.get()


		if event.type in {'ESC'}:
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
			return {'CANCELLED'}

		if event.type in {'RET'}:
			self.map.stop()
			bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
			return {'FINISHED'}

		return {'RUNNING_MODAL'}


####################################
# Properties in scene

bpy.types.Scene.fontColor = FloatVectorProperty(name="Font color", subtype='COLOR', min=0, max=1, size=4, default=(0, 0, 0, 1))

bpy.types.Scene.cacheFolder = bpy.props.StringProperty(
      name = "Cache folder",
      default = "",
      description = "Define a folder where to store maptiles db",
      subtype = 'DIR_PATH'
      )


srcItems = []
for srckey, src in sources.items():
	for laykey, lay in src['layers'].items():
		mapkey = srckey + ':' + laykey
		name = src['name'] + " " + lay['name']
		#put each item in a tuple (key, label, tooltip)
		srcItems.append( (mapkey, name, src['description']) )



bpy.types.Scene.mapSource = EnumProperty(
			name = "Map",
			description = "Choose map service source",
			items = srcItems
			)

####################################

class MAP_PANEL(bpy.types.Panel):
	bl_category = "GIS"
	bl_label = "Basemap"
	bl_space_type = "VIEW_3D"
	bl_context = "objectmode"
	bl_region_type = "TOOLS"#"UI"
	

	def draw(self, context):
		layout = self.layout
		scn = context.scene
		layout.prop(scn, "cacheFolder")
		layout.prop(scn, "mapSource")		
		layout.operator("view3d.map_view")
		layout.prop(scn, "fontColor")




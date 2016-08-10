# -*- coding:utf-8 -*-

# This file is part of BlenderGIS

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


import struct


def getImgFormat(filepath):
	"""
	Read header of an image file and try to determine it's format
	no requirements, support JPEG, JPEG2000, PNG, GIF, BMP, TIFF, EXR
	"""
	format = None
	with open(filepath, 'rb') as fhandle:
		head = fhandle.read(32)
		# handle GIFs
		if head[:6] in (b'GIF87a', b'GIF89a'):
			format = 'GIF'
		# handle PNG
		elif head.startswith(b'\211PNG\r\n\032\n'):
			format = 'PNG'
		# handle JPEGs
		elif head[6:10] in (b'JFIF', b'Exif'):
			format = 'JPEG'
		# handle JPEG2000s
		elif head.startswith(b'\x00\x00\x00\x0cjP  \r\n\x87\n'):
			format = 'JPEG2000'
		# handle BMP
		elif head.startswith(b'BM'):
			format = 'BMP'
		# handle TIFF
		elif head[:2] in (b'MM', b'II'):
			format = 'TIFF'
		# handle EXR
		elif head.startswith(b'\x76\x2f\x31\x01'):
			format = 'EXR'
	return format



def getImgDim(filepath):
	"""
	Return (width, height) for a given img file content
	no requirements, support JPEG, JPEG2000, PNG, GIF, BMP
	"""
	width, height = None, None

	with open(filepath, 'rb') as fhandle:
		head = fhandle.read(32)
		# handle GIFs
		if head[:6] in (b'GIF87a', b'GIF89a'):
			try:
				width, height = struct.unpack("<hh", head[6:10])
			except struct.error:
				raise ValueError("Invalid GIF file")
		# handle PNG
		elif head.startswith(b'\211PNG\r\n\032\n'):
			try:
				width, height = struct.unpack(">LL", head[16:24])
			except struct.error:
				# Maybe this is for an older PNG version.
				try:
					width, height = struct.unpack(">LL", head[8:16])
				except struct.error:
					raise ValueError("Invalid PNG file")
		# handle JPEGs
		elif head[6:10] in (b'JFIF', b'Exif'):
			try:
				fhandle.seek(0) # Read 0xff next
				size = 2
				ftype = 0
				while not 0xc0 <= ftype <= 0xcf:
					fhandle.seek(size, 1)
					byte = fhandle.read(1)
					while ord(byte) == 0xff:
						byte = fhandle.read(1)
					ftype = ord(byte)
					size = struct.unpack('>H', fhandle.read(2))[0] - 2
				# We are at a SOFn block
				fhandle.seek(1, 1)  # Skip `precision' byte.
				height, width = struct.unpack('>HH', fhandle.read(4))
			except struct.error:
				raise ValueError("Invalid JPEG file")
		# handle JPEG2000s
		elif head.startswith(b'\x00\x00\x00\x0cjP  \r\n\x87\n'):
			fhandle.seek(48)
			try:
				height, width = struct.unpack('>LL', fhandle.read(8))
			except struct.error:
				raise ValueError("Invalid JPEG2000 file")
		# handle BMP
		elif head.startswith(b'BM'):
			imgtype = 'BMP'
			try:
				width, height = struct.unpack("<LL", head[18:26])
			except struct.error:
				raise ValueError("Invalid BMP file")

	return width, height


#####################################

import os
import io
import numpy as np
import imghdr
import random

try:
	from PIL import Image
	HAS_PIL = True
except:
	HAS_PIL = False
	
try:
	from osgeo import gdal
	HAS_GDAL = True
except:
	HAS_GDAL = False


from ..lib import imageio


def isValidStream(data):
	format = imghdr.what(None, data)
	if format is None:
		return False
	return True


class NpImage():
	'''Represent an image as Numpy array'''

	#Default interface
	IFACE = 'IMGIO' # PIL, IMGIO, GDAL
	#IFACE = 'PIL'
	#IFACE = 'GDAL'

	def __init__(self, data):
	
		#init from np array
		if isinstance(data, np.ndarray):
			self.data = data
		
		#init from bytes data
		elif isinstance(data, bytes):
			self.data = self.npFromBLOB(data)
		
		#init from file path
		elif isinstance(data, str):
			if os.path.exists(data):
				self.data = self.open(data) #TODO
	
		#init from another NpImage instance
		elif isinstance(data, NpImage):
			self.data = data.data

		#init from GDAL dataset instance
		elif HAS_GDAL:
			if isinstance(data, gdal.Dataset):
				self.data = self.npFromGDAL(data)

		#init from PIL Image instance
		'''
		elif HAS_PIL:
			if isinstance(data, Image):
				self.data = self.npFromPIL(data)
		'''

		#
		if len(self.data.shape) == 3:
			self.h, self.w, self.nbBands = self.data.shape
		else:
			raise ValueError('array shape error')
		self.size = (self.w, self.h)
		self.dtype = self.data.dtype

	#@property
	#def size(self):
		

	"""
	@classmethod
	def open(cls, path):
		if NpImage.IFACE == 'PIL':
			img = Image.open(data)
			if img.mode == 'P':
				img = img.convert('RGB')
			#pil img to np
			data = np.asarray(img)
		
		elif NpImage.IFACE == 'IMGIO':
			data = imageio.imread(data)
			
		elif NpImage.IFACE == 'GDAL':

		
		return cls(data)
	"""



	@classmethod
	def new(cls, w, h, bkgColor=(255,255,255,255)):
		r, g, b, a = bkgColor
		#return cls(np.zeros((h, w, 4), np.uint8))
		data = np.empty((h, w, 4), np.uint8)
		data[:,:,0] = r
		data[:,:,1] = g
		data[:,:,2] = b
		data[:,:,3] = a
		return cls(data)


	@staticmethod
	def npFromBLOB(data):
		'''Get Numpy array from Bytes data'''

		if not isinstance(data, bytes):
			raise ValueError('Not a valid stream')
		
		if NpImage.IFACE == 'PIL':
			#convert bytes object to bytesio (stream buffer) and open it with PIL
			img = Image.open(io.BytesIO(data))
			if img.mode == 'P':
				img = img.convert('RGB')
			#pil img to np
			data = np.asarray(img)
		
		elif NpImage.IFACE == 'IMGIO':
			data = imageio.imread(io.BytesIO(data))
			
		elif NpImage.IFACE == 'GDAL':
			#Use a virtual memory file to create gdal dataset from buffer
			vsipath = '/vsimem/img'
			gdal.FileFromMemBuffer(vsipath, data)
			ds = gdal.Open(vsipath)
			data = ds.ReadAsArray()
			if len(data.shape) == 3:
				data = np.rollaxis(data, 0, 3) # because first axis is band index
			else: #one band indexed color = palette = pseudo color table (pct)
				ctable = ds.GetRasterBand(1).GetColorTable()
				nbColors = ctable.GetCount()
				#Swap index values to their corresponding color (rgba)
				keys = np.array( [i for i in range(nbColors)] )
				values = np.array( [ctable.GetColorEntry(i) for i in range(nbColors)] )
				sortIdx = np.argsort(keys)
				idx = np.searchsorted(keys, data, sorter=sortIdx)
				data = values[sortIdx][idx]
			ds = None
			gdal.Unlink(vsipath)
							
		return data


	@staticmethod
	def npFromPIL(img):
		'''Get Numpy array from PIL Image instance'''
		return np.asarray(img)
		
	@staticmethod
	def npFromGDAL(ds):
		'''Get Numpy array from GDAL dataset instance'''
		data = ds.ReadAsArray()
		data = np.rollaxis(data, 0, 3) # because first axis is band index
		return data


	def toBLOB(self, ext='PNG'): #TODO support of PNG or JPEG
		if self.IFACE == 'PIL':
			b = io.BytesIO()
			img = Image.fromarray(self.data)
			img.save(b, format='PNG')
			data = b.getvalue() #convert bytesio to bytes	
		elif self.IFACE == 'IMGIO':
			data = imageio.imwrite(imageio.RETURN_BYTES, self.data, format='PNG')
		elif self.IFACE == 'GDAL':
			mem = self.toGDAL()
			name = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(5))
			vsiname = '/vsimem/' + name + '.png'
			out = gdal.GetDriverByName('PNG').CreateCopy(vsiname, mem)
			# Read /vsimem/output.png
			f = gdal.VSIFOpenL(vsiname, 'rb')
			gdal.VSIFSeekL(f, 0, 2) # seek to end
			size = gdal.VSIFTellL(f)
			gdal.VSIFSeekL(f, 0, 0) # seek to beginning
			data = gdal.VSIFReadL(1, size, f)
			gdal.VSIFCloseL(f)
			# Cleanup
			gdal.Unlink(vsiname) 
			mem = None
		
		return data
		


	def toPIL(self):
		return Image.fromarray(self.data)


	def toGDAL(self):
		'''Get GDAL memory driver dataset'''
		img_h, img_w, nbBands = self.data.shape
		mem = gdal.GetDriverByName('MEM').Create('', img_w, img_h, nbBands, gdal.GDT_Byte)
		for bandIdx in range(nbBands):
			bandArray = self.data[:,:,bandIdx]
			mem.GetRasterBand(bandIdx+1).WriteArray(bandArray)
		return mem


	def save(self, path):
		'''
		save the numpy array to a new image file
		output format is defined by path extension
		'''
		if self.IFACE == 'PIL':
			self.toPIL().save(path)
		elif self.IFACE == 'IMGIO':
			imageio.imwrite(path, self.data)
			#warn can't write alpha channel to jpg
		elif self.IFACE == 'GDAL':
			imgFormat = path[-3:]
			#_, imgFormat = os.path.splitext(path)
			if imgFormat == 'png':
				driver = 'PNG'
			elif imgFormat in ['jpg', 'jpeg']:
				driver = 'JPEG'
			elif imgFormat in ['tif', 'tiff']:
				driver = 'Gtiff'
			else:
				raise ValueError('Cannot write to '+ driver + ' image format')
			
			#Some format like jpg or png has no create method implemented
			#because we can't write data at random with these formats
			#so we must use an intermediate memory driver, write data to it 
			#and then write the output file with the createcopy method
			mem = self.toGDAL()
			out = gdal.GetDriverByName(driver).CreateCopy(path, mem)
			mem, out = None, None


	def paste(self, data, x, y):
		if isinstance(data, NpImage):
			data = data.data
		elif not isinstance(data, np.ndarray):
			raise		
		h, w, n = data.shape
		
		self.data[y:y+h, x:x+w, 0:n] = data


###


class GeoImage(NpImage):
	'''
	A quick class to represent a georeferenced image
	data is used to init NpImage parent class
	it can be bytes data, Numpy array, NpImage, PIL image or GDAL dataset
	Georef infos
		-ul = upper left coord (true corner of the pixel)
		-res = pixel resolution in map unit (no distinction between resx and resy)
		-no rotation parameters
	'''

	def __init__(self, data, ul, res):
		self.ul = ul #upper left geo coords (exact pixel ul corner)
		self.res = res #map unit / pixel
		NpImage.__init__(self, data)

	@property
	def origin(self):
		'''(x,y) geo coordinates of image center'''
		w, h = self.size
		xmin, ymax = self.ul
		ox = xmin + w/2 * self.res
		oy = ymax - h/2 * self.res
		return (ox, oy)

	@property
	def geoSize(self):
		'''raster dimensions (width, height) in map units'''
		w, h = self.size
		return (w * self.res, h * self.res)

	@property
	def bbox(self):
		'''Return a bbox class object'''
		w, h = self.size
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

	#Alias
	def geoFromPx(self, xPx, yPx):#, reverseY=False):
		return self.pxToGeo(xPx, yPx)
	def pxFromGeo(self, x, y, reverseY=False, round2Floor=False):
		return self.geoToPx(x, y, reverseY, round2Floor)

	def pxToGeo(self, xPx, yPx):
		"""
		Return geo coords of upper left corner of an given pixel
		Number of pixels is range from 0 (not 1) and counting from top left
		"""
		if reverseY:#y pixel position counting from bottom
			yPxRange = self.size[1] - 1
			yPx = yPxRange - yPx
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
		if reverseY:#y pixel position counting from bottom
			yPxRange = self.size[1] - 1#number of pixels is range from 0 (not 1)
			yPx = yPxRange - yPx
		if round2Floor:
			return (math.floor(xPx), math.floor(yPx))
		else:
			return (xPx, yPx)


###
import math
from .proj import reprojPt, reprojBbox, SRS



def reprojImg(crs1, crs2, geoimg, out_ul=None, out_size=None, out_res=None, resamplAlg='BL'):
	'''
	Use GDAL Python binding to reproject an image
	crs1, crs2 >> epsg code
	geoimg >> input GeoImage object (PIL image + georef infos)
	out_ul >> output raster top left coords (same as input if None)
	out_size >> output raster size (same as input is None)
	out_res >> output raster resolution (same as input if None)
	'''

	if not HAS_GDAL:
		raise NotImplementedError
	
	img_h, img_w, nbBands = geoimg.data.shape
	ds1 = geoimg.toGDAL()

	#Assign georef infos
	xmin, ymax = geoimg.ul
	res = geoimg.res
	geoTrans = (xmin, res, 0, ymax, 0, -res)
	ds1.SetGeoTransform(geoTrans)
	prj1 = SRS(crs1).getOgrSpatialRef()
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
	prj2 = SRS(crs2).getOgrSpatialRef()
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

	geoimg = GeoImage(ds2, (xmin, ymax), res)

	#Close gdal datasets
	ds1 = None
	ds2 = None

	return geoimg

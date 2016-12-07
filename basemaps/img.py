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



import os
import io
import numpy as np
import imghdr
import random
import math

from ..utils.proj import reprojPt, reprojBbox, SRS
from ..checkdeps import HAS_GDAL, HAS_PIL, HAS_IMGIO

if HAS_PIL:
	from PIL import Image
	
if HAS_GDAL:
	from osgeo import gdal

if HAS_IMGIO:
	from ..lib import imageio




def isValidStream(data):
	if data is None:
		return False
	format = imghdr.what(None, data)
	if format is None:
		return False
	return True




class NpImage():
	'''Represent an image as Numpy array'''

	#Default interface
	@property
	def IFACE(self):
		#return 'PIL' #for debug
		if HAS_GDAL:
			return 'GDAL'
		elif HAS_PIL:
			return 'PIL'
		elif HAS_IMGIO:
			return 'IMGIO'
		else:
			return None


	def __init__(self, data):
		"""init from file path, bytes data, Numpy array, NpImage, PIL Image or GDAL dataset"""

		if self.IFACE is None:
			raise ImportError("No image lib available")
		
		self.data = None

		#init from numpy array
		if isinstance(data, np.ndarray):
			self.data = data
		
		#init from bytes data
		if isinstance(data, bytes):
			self.data = self._npFromBLOB(data)
		
		#init from file path
		if isinstance(data, str):
			if os.path.exists(data):
				self.data = self._npFromPath(data)
			else:
				raise ValueError('Unable to load image data')
	
		#init from another NpImage instance
		if isinstance(data, NpImage):
			self.data = data.data

		#init from GDAL dataset instance
		if HAS_GDAL:
			if isinstance(data, gdal.Dataset):
				self.data = self._npFromGDAL(data)

		#init from PIL Image instance
		if HAS_PIL:
			if Image.isImageType(data):
				self.data = self._npFromPIL(data)
	
		if self.data is None:
			raise ValueError('Unable to load image data')


	@property
	def size(self):
		return (self.data.shape[1], self.data.shape[0])
	
	@property
	def nbBands(self):
		if len(self.data.shape) == 2:
			return 1
		elif len(self.data.shape) == 3:
			return self.data.shape[2]

	@property
	def hasAlpha(self):
		return self.nbBands == 4

	@property
	def isOneBand(self):
		return self.nbBands == 1
			
	@property
	def dtype(self):
		return self.data.dtype
		

	@classmethod
	def new(cls, w, h, bkgColor=(255,255,255,255)):
		r, g, b, a = bkgColor
		data = np.empty((h, w, 4), np.uint8)
		data[:,:,0] = r
		data[:,:,1] = g
		data[:,:,2] = b
		data[:,:,3] = a
		return cls(data)


	def _npFromPath(self, path):
		'''Get Numpy array from a file path'''
		if self.IFACE == 'PIL':
			img = Image.open(path)
			return self._npFromPIL(img)
		elif self.IFACE == 'IMGIO':
			return imageio.imread(path)
		elif self.IFACE == 'GDAL':
			ds = gdal.Open(path)
			return self._npFromGDAL(ds)


	def _npFromBLOB(self, data):
		'''Get Numpy array from Bytes data'''

		if self.IFACE == 'PIL':
			#convert bytes object to bytesio (stream buffer) and open it with PIL
			img = Image.open(io.BytesIO(data))
			data = self._npFromPIL(img)
		
		elif self.IFACE == 'IMGIO':
			data = imageio.imread(io.BytesIO(data))
			
		elif self.IFACE == 'GDAL':
			#Use a virtual memory file to create gdal dataset from buffer
			#build a random name to make the function thread safe
			vsipath = '/vsimem/' + ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(5))
			gdal.FileFromMemBuffer(vsipath, data)
			ds = gdal.Open(vsipath)
			data = self._npFromGDAL(ds)
			ds = None
			gdal.Unlink(vsipath)
							
		return data


	def _npFromPIL(self, img):
		'''Get Numpy array from PIL Image instance'''
		if img.mode == 'P': #palette (indexed color)
			img = img.convert('RGBA')
		data = np.asarray(img)
		data.setflags(write=True) #PIL return a non writable array
		return data
		
	def _npFromGDAL(self, ds):
		'''Get Numpy array from GDAL dataset instance'''
		data = ds.ReadAsArray()
		if len(data.shape) == 3: #multiband
			data = np.rollaxis(data, 0, 3) # because first axis is band index
		else: #one band raster or indexed color (= palette = pseudo color table (pct))
			ctable = ds.GetRasterBand(1).GetColorTable()
			if ctable is not None:
				#Swap index values to their corresponding color (rgba)
				nbColors = ctable.GetCount()
				keys = np.array( [i for i in range(nbColors)] )
				values = np.array( [ctable.GetColorEntry(i) for i in range(nbColors)] )
				sortIdx = np.argsort(keys)
				idx = np.searchsorted(keys, data, sorter=sortIdx)
				data = values[sortIdx][idx]
		return data




	def toBLOB(self, ext='PNG'):
		'''Get bytes raw data'''
		if ext == 'JPG':
			ext = 'JPEG'
		
		if self.IFACE == 'PIL':
			b = io.BytesIO()
			img = Image.fromarray(self.data)
			img.save(b, format=ext)
			data = b.getvalue() #convert bytesio to bytes
			
		elif self.IFACE == 'IMGIO':
			if ext == 'JPEG' and self.hasAlpha:
				self.removeAlpha()
			data = imageio.imwrite(imageio.RETURN_BYTES, self.data, format=ext)
		
		elif self.IFACE == 'GDAL':
			mem = self.toGDAL()
			#build a random name to make the function thread safe
			name = ''.join(random.choice('abcdefghijklmnopqrstuvwxyz') for i in range(5))
			vsiname = '/vsimem/' + name + '.png'
			out = gdal.GetDriverByName(ext).CreateCopy(vsiname, mem)
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
		'''Get PIL Image instance'''
		return Image.fromarray(self.data)


	def toGDAL(self):
		'''Get GDAL memory driver dataset'''
		w, h = self.size
		n = self.nbBands
		mem = gdal.GetDriverByName('MEM').Create('', w, h, n, gdal.GDT_Byte)
		for bandIdx in range(n):
			bandArray = self.data[:,:,bandIdx]
			mem.GetRasterBand(bandIdx+1).WriteArray(bandArray)
		return mem


	def removeAlpha(self):
		if self.hasAlpha:
			self.data = self.data[:, :, 0:3]

	def addAlpha(self, opacity=255):
		if self.nbBands == 3:
			w, h = self.size
			alpha = np.empty((h,w), dtype=self.dtype)
			alpha.fill(opacity)
			alpha = np.expand_dims(alpha, axis=2)
			self.data = np.append(self.data, alpha, axis=2)


	def save(self, path):
		'''
		save the numpy array to a new image file
		output format is defined by path extension
		'''
		
		imgFormat = path[-3:]	
		
		if self.IFACE == 'PIL':
			self.toPIL().save(path)
		elif self.IFACE == 'IMGIO':
			if imgFormat == 'jpg' and self.hasAlpha:
				self.removeAlpha()
			imageio.imwrite(path, self.data)		
		elif self.IFACE == 'GDAL':
			if imgFormat == 'png':
				driver = 'PNG'
			elif imgFormat == 'jpg':
				driver = 'JPEG'
			elif imgFormat == 'tif':
				driver = 'Gtiff'
			else:
				raise ValueError('Cannot write to '+ imgFormat + ' image format')
			#Some format like jpg or png has no create method implemented
			#because we can't write data at random with these formats
			#so we must use an intermediate memory driver, write data to it 
			#and then write the output file with the createcopy method
			mem = self.toGDAL()
			out = gdal.GetDriverByName(driver).CreateCopy(path, mem)
			mem = out = None


	def paste(self, data, x, y):

		img = NpImage(data)
		data = img.data
		w, h = img.size
		
		if img.isOneBand and self.isOneBand:
			self.data[y:y+h, x:x+w] = data
		elif (not img.isOneBand and self.isOneBand) or (img.isOneBand and not self.isOneBand):
			raise ValueError('Paste error, cannot mix one band with multiband')	

		if self.hasAlpha:
			n = img.nbBands
			self.data[y:y+h, x:x+w, 0:n] = data
		else:
			n = self.nbBands		
			self.data[y:y+h, x:x+w, :] = data[:, :, 0:n]

###


class GeoImage(NpImage):
	'''
	A quick class to represent a georeferenced image
	data is used to init NpImage parent class
	it can be a file path, bytes data, Numpy array, NpImage, PIL Image or GDAL Dataset
	Georef infos
		-ul = upper left coord (true corner of the pixel)
		-res = pixel resolution in map unit (no distinction between resx and resy)	
	Note that instead of GeoRaster class: 
	- pixel coords refers to upper left corner of the pixel and not pixel center
	- there is no support for rotation parameters
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
		(x,y) geo coordinates of image corners (true corner, not pixel center)
		(upper left, upper right, bottom right, bottom left)
		'''
		xmin, ymin, xmax, ymax = self.bbox
		return ( (xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin) )

	#Alias
	def geoFromPx(self, xPx, yPx, reverseY=False):
		return self.pxToGeo(xPx, yPx)
	def pxFromGeo(self, x, y, reverseY=False, round2Floor=False):
		return self.geoToPx(x, y, reverseY, round2Floor)

	def pxToGeo(self, xPx, yPx, reverseY=False):
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
	
	img_w, img_h = geoimg.size
	nbBands = geoimg.nbBands
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

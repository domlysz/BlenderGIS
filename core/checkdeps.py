import logging
log = logging.getLogger(__name__)

#GDAL
try:
	from osgeo import gdal
except:
	HAS_GDAL = False
	log.debug('GDAL Python binding unavailable')
else:
	HAS_GDAL = True
	log.debug('GDAL Python binding available')


#PyProj
try:
	import pyproj
except:
	HAS_PYPROJ = False
	log.debug('PyProj unavailable')
else:
	HAS_PYPROJ = True
	log.debug('PyProj available')


#PIL/Pillow
try:
	from PIL import Image
except:
	HAS_PIL = False
	log.debug('Pillow unavailable')
else:
	HAS_PIL = True
	log.debug('Pillow available')


#Imageio freeimage plugin
try:
	from .lib import imageio
	imageio.plugins._freeimage.get_freeimage_lib() #try to download freeimage lib
except Exception as e:
	log.error("Cannot install ImageIO's Freeimage plugin", exc_info=True)
	HAS_IMGIO = False
else:
	HAS_IMGIO = True
	log.debug('ImageIO Freeimage plugin available')

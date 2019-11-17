import os
import time

import logging
log = logging.getLogger(__name__)

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import bpy
import bmesh
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty

from ..geoscene import GeoScene
from .utils import adjust3Dview, getBBOX, isTopView
from ..core.proj import SRS, reprojBbox

from ..core.settings import getSetting

USER_AGENT = getSetting('user_agent')


class IMPORTGIS_OT_srtm_query(Operator):
	"""Import NASA SRTM elevation data from OpenTopography RESTful Web service"""

	bl_idname = "importgis.srtm_query"
	bl_description = 'Query for NASA SRTM elevation data covering the current view3d area'
	bl_label = "Get SRTM"
	bl_options = {"UNDO"}

	def invoke(self, context, event):

		#check georef
		geoscn = GeoScene(context.scene)
		if not geoscn.isGeoref:
				self.report({'ERROR'}, "Scene is not georef")
				return {'CANCELLED'}
		if geoscn.isBroken:
				self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
				return {'CANCELLED'}

		return self.execute(context)#context.window_manager.invoke_props_dialog(self)

	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'

	def execute(self, context):

		scn = context.scene
		geoscn = GeoScene(scn)
		crs = SRS(geoscn.crs)

		#Validate selection
		objs = bpy.context.selected_objects
		aObj = context.active_object
		if len(objs) == 1 and aObj.type == 'MESH':
			onMesh = True
			bbox = getBBOX.fromObj(aObj).toGeo(geoscn)
		elif isTopView(context):
			onMesh = False
			bbox = getBBOX.fromTopView(context).toGeo(geoscn)
		else:
			self.report({'ERROR'}, "Please define the query extent in orthographic top view or by selecting a reference object")
			return {'CANCELLED'}

		if bbox.dimensions.x > 1000000 or bbox.dimensions.y > 1000000:
			self.report({'ERROR'}, "Too large extent")
			return {'CANCELLED'}

		bbox = reprojBbox(geoscn.crs, 4326, bbox)

		if bbox.ymin > 60:
			self.report({'ERROR'}, "SRTM is not available beyond 60 degrees north")
			return {'CANCELLED'}
		if bbox.ymax < -56:
			self.report({'ERROR'}, "SRTM is not available below 56 degrees south")
			return {'CANCELLED'}

		#Set cursor representation to 'loading' icon
		w = context.window
		w.cursor_set('WAIT')

		#url template
		#http://opentopo.sdsc.edu/otr/getdem?demtype=SRTMGL3&west=-120.168457&south=36.738884&east=-118.465576&north=38.091337&outputFormat=GTiff
		e = 0.002 #opentopo service does not always respect the entire bbox, so request for a little more
		xmin, xmax = bbox.xmin - e, bbox.xmax + e
		ymin, ymax = bbox.ymin - e, bbox.ymax + e
		w = 'west={}'.format(xmin)
		e = 'east={}'.format(xmax)
		s = 'south={}'.format(ymin)
		n = 'north={}'.format(ymax)
		url = 'http://opentopo.sdsc.edu/otr/getdem?demtype=SRTMGL3&' + '&'.join([w,e,s,n]) + '&outputFormat=GTiff'
		log.debug(url)

		# Download the file from url and save it locally
		# opentopo return a geotiff object in wgs84
		if bpy.data.is_saved:
			filePath = os.path.join(os.path.dirname(bpy.data.filepath), 'srtm.tif')
		else:
			filePath = os.path.join(bpy.app.tempdir, 'srtm.tif')

		#we can directly init NpImg from blob but if gdal is not used as image engine then georef will not be extracted
		#Alternatively, we can save on disk, open with GeoRaster class (will use tyf if gdal not available)
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		try:
			with urlopen(rq) as response, open(filePath, 'wb') as outFile:
				data = response.read() # a `bytes` object
				outFile.write(data) #
		except (URLError, HTTPError) as err:
			log.error('Http request fails url:{}, code:{}, error:{}'.format(url, err.code, err.reason))
			self.report({'ERROR'}, "Cannot reach OpenTopography web service, check logs for more infos")
			return {'CANCELLED'}

		if not onMesh:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			reprojection = True,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf')
		else:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			reprojection = True,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf',
			demOnMesh = True,
			objectsLst = [str(i) for i, obj in enumerate(scn.collection.objects) if obj.name == bpy.context.active_object.name][0],
			clip = False,
			fillNodata = False)

		bbox = getBBOX.fromScn(scn)
		adjust3Dview(context, bbox, zoomToSelect=False)

		return {'FINISHED'}


def register():
	try:
		bpy.utils.register_class(IMPORTGIS_OT_srtm_query)
	except ValueError as e:
		log.warning('{} is already registered, now unregister and retry... '.format(cls))
		unregister()
		bpy.utils.register_class(IMPORTGIS_OT_srtm_query)

def unregister():
	bpy.utils.unregister_class(IMPORTGIS_OT_srtm_query)

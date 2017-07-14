import os
import time

import urllib.request

import bpy
import bmesh
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty

from ..geoscene import GeoScene
from .utils import adjust3Dview, getBBOX
from ..core.proj import SRS, reprojBbox

from ..core.settings import getSetting

USER_AGENT = getSetting('user_agent')


class SRTM_QUERY(Operator):
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
				return {'FINISHED'}
		if geoscn.isBroken:
				self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
				return {'FINISHED'}

		return self.execute(context)#context.window_manager.invoke_props_dialog(self)


	def execute(self, context):

		scn = context.scene
		geoscn = GeoScene(scn)
		crs = SRS(geoscn.crs)

		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass

		#Validate selection
		objs = bpy.context.selected_objects
		if not objs:
			onMesh = False
			#check if 3dview is top ortho
			reg3d = context.region_data
			if reg3d.view_perspective != 'ORTHO' or tuple(reg3d.view_matrix.to_euler()) != (0,0,0):
				self.report({'ERROR'}, "View3d must be in top ortho")
				return {'FINISHED'}
			bbox = getBBOX.fromTopView(context).toGeo(geoscn)
		elif len(objs) > 2 or (len(objs) == 1 and not objs[0].type == 'MESH'):
			self.report({'ERROR'}, "Pre-selection is incorrect")
			return {'CANCELLED'}
		else:
			onMesh = True
			bbox = getBBOX.fromObj(objs[0]).toGeo(geoscn)

		if bbox.dimensions.x > 20000 or bbox.dimensions.y > 20000:
			self.report({'ERROR'}, "Too large extent")
			return {'FINISHED'}

		bbox = reprojBbox(geoscn.crs, 4326, bbox)

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

		# Download the file from url and save it locally
		# opentopo return a geotiff object in wgs84
		filePath = bpy.app.tempdir + 'srtm.tif'

		#we can directly init NpImg from blob but if gdal is not used as image engine then georef will not be extracted
		#Alternatively, we can save on disk, open with GeoRaster class (will use tyf if gdal not available)
		rq = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
		with urllib.request.urlopen(rq) as response, open(filePath, 'wb') as outFile:
			data = response.read() # a `bytes` object
			outFile.write(data) #

		if not onMesh:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf')
		else:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf',
			demOnMesh = True,
			objectsLst = [str(i) for i, obj in enumerate(scn.objects) if obj.name == bpy.context.active_object.name][0],
			clip = False,
			fillNodata = False)

		bbox = getBBOX.fromScn(scn)
		adjust3Dview(context, bbox, zoomToSelect=False)

		return {'FINISHED'}

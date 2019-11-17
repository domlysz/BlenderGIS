# -*- coding:utf-8 -*-
import os
import bpy
import bmesh
import mathutils

import logging
log = logging.getLogger(__name__)

from ..core.lib.shapefile import Writer as shpWriter
from ..core.lib.shapefile import POINTZ, POLYLINEZ, POLYGONZ, MULTIPOINTZ

from bpy_extras.io_utils import ExportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator

from ..geoscene import GeoScene

from ..core.proj import SRS

class EXPORTGIS_OT_shapefile(Operator, ExportHelper):
	"""Export from ESRI shapefile file format (.shp)"""
	bl_idname = "exportgis.shapefile" # important since its how bpy.ops.import.shapefile is constructed (allows calling operator from python console or another script)
	#bl_idname rules: must contain one '.' (dot) charactere, no capital letters, no reserved words (like 'import')
	bl_description = 'export to ESRI shapefile file format (.shp)'
	bl_label = "Export SHP"
	bl_options = {"UNDO"}


	# ExportHelper class properties
	filename_ext = ".shp"
	filter_glob: StringProperty(
			default="*.shp",
			options={'HIDDEN'},
			)

	exportType: EnumProperty(
			name="Feature type",
			description="Select feature type",
			items=[ ('POINTZ', 'Point', ""),
			('POLYLINEZ', 'Line', ""),
			('POLYGONZ', 'Polygon', "")]
			)

	mode: EnumProperty(
			name="Mode",
			description="Select the export strategy",
			items=[ ('COLLEC', 'Collection', "Export a collection of object"),
			('OBJ', 'Single object', "Export a single mesh")],
			default='OBJ'
			)

	def listCollections(self, context):
		return [(c.name, c.name, "Collection") for c in bpy.data.collections]

	selectedColl: EnumProperty(
		name = "Collection",
		description = "Select the collection to export",
		items = listCollections)

	def listObjects(self, context):
		objs = []
		for index, object in enumerate(bpy.context.scene.objects):
			if object.type == 'MESH':
				#put each object in a tuple (key, label, tooltip) and add this to the objects list
				objs.append((str(index), object.name, "Object named " + object.name))
		return objs

	selectedObj: EnumProperty(
		name = "Object",
		description = "Select the object to export",
		items = listObjects )


	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'

	def draw(self, context):
		#Function used by blender to draw the panel.
		layout = self.layout
		layout.prop(self, 'mode')
		if self.mode == 'OBJ':
			layout.prop(self, 'selectedObj')
		elif self.mode == 'COLLEC':
			layout.prop(self, 'selectedColl')
		layout.prop(self, 'exportType')

	def execute(self, context):
		filePath = self.filepath
		folder = os.path.dirname(filePath)
		scn = context.scene
		geoscn = GeoScene(scn)

		'''
		#Get selected obj
		objs = bpy.context.selected_objects
		if len(objs) == 0 or len(objs)>1:
			self.report({'INFO'}, "Selection is empty or too much object selected")
			return {'CANCELLED'}
		obj = objs[0]
		if obj.type != 'MESH':
			self.report({'INFO'}, "Selection isn't a mesh")
			return {'CANCELLED'}
		'''

		if not self.selectedObj or not self.selectedColl:
			self.report({'ERROR'}, "Nothing to export")
			return {'CANCELLED'}

		if geoscn.isGeoref:
			dx, dy = geoscn.getOriginPrj()
			crs = SRS(geoscn.crs)
			try:
				wkt = crs.getWKT()
			except Exception as e:
				log.warning('Cannot convert crs to wkt', exc_info=True)
				wkt = None
		elif geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
			return {'CANCELLED'}
		else:
			dx, dy = (0, 0)
			wkt = None


		if self.mode == 'OBJ':
			objects = [scn.objects[int(self.selectedObj)]]
		elif self.mode == 'COLLEC':
			objects = bpy.data.collections[self.selectedColl].all_objects
			objects = [obj for obj in objects if obj.type == 'MESH']
			if not objects:
				self.report({'ERROR'}, "Nothing to export")
				return {'CANCELLED'}

		if len(objects) == 0:
			self.report({'ERROR'}, "No object to export")
			return {'CANCELLED'}

		outShp = shpWriter(filePath)
		if self.exportType == 'POLYGONZ':
			outShp.shapeType = POLYGONZ #15
		if self.exportType == 'POLYLINEZ':
			outShp.shapeType = POLYLINEZ #13
		if self.exportType == 'POINTZ' and self.mode == 'OBJ':
			outShp.shapeType = POINTZ
		if self.exportType == 'POINTZ' and self.mode == 'COLLEC':
			outShp.shapeType = MULTIPOINTZ

		#create fields (all needed fields sould be created before adding any new record)
		#TODO more robust evaluation, and check for boolean and date types
		cLen = 255 #string fields default length
		nLen = 20 #numeric fields default length
		dLen = 5 #numeric fields default decimal precision
		maxFieldNameLen = 8 #shp capabilities limit field name length to 8 characters
		outShp.field('bid','N', nLen) #export id
		for obj in objects:
			for k, v in obj.items():
				k = k[0:maxFieldNameLen]
				if k not in [f[0] for f in outShp.fields]:
					#evaluate the field type with the first value
					if v.lstrip("-+").isdigit():
						v = int(v)
						fieldType = 'N'
					else:
						try:
							v = float(v)
						except ValueError:
							fieldType = 'C'
						else:
							fieldType = 'N'
					if fieldType == 'C':
						outShp.field(k, fieldType, cLen)
					elif fieldType == 'N':
						if isinstance(v, int):
							outShp.field(k, fieldType, nLen, 0)
						else:
							outShp.field(k, fieldType, nLen, dLen)

		for i, obj in enumerate(objects):

			loc = obj.location
			bm = bmesh.new()
			bm.from_object(obj, context.evaluated_depsgraph_get(), deform=True) #'deform' allows to consider modifier deformation
			bm.transform(obj.matrix_world)

			if self.exportType == 'POINTZ':
				if len(bm.verts) == 0:
					continue
					'''
					self.report({'ERROR'}, "No vertice to export")
					return {'CANCELLED'}
					'''

				#Extract coords & adjust values against georef deltas
				pts = [[v.co.x+dx, v.co.y+dy, v.co.z] for v in bm.verts]

				if self.mode == 'OBJ':
					for j, pt in enumerate(pts):
						outShp.pointz(*pt)
						outShp.record(bid=j)

				if self.mode == 'COLLEC':
					outShp.multipointz(pts)
					attributes = {'bid':i}


			if self.exportType == 'POLYLINEZ':

				if len(bm.edges) == 0:
					continue
					'''
					self.report({'ERROR'}, "No edge to export")
					return {'CANCELLED'}
					'''

				lines = []
				for edge in bm.edges:
					#Extract coords & adjust values against georef deltas
					line = [(vert.co.x+dx, vert.co.y+dy, vert.co.z) for vert in edge.verts]
					lines.append(line)

				if self.mode == 'OBJ':
					for j, line in enumerate(lines):
						outShp.linez([line])
						outShp.record(bid=j)

				if self.mode == 'COLLEC':
					outShp.linez(lines)
					attributes = {'bid':i}


			if self.exportType == 'POLYGONZ':

				if len(bm.faces) == 0:
					continue
					'''
					self.report({'ERROR'}, "No face to export")
					return {'CANCELLED'}
					'''

				#build geom
				polygons = []
				for face in bm.faces:
					#Extract coords & adjust values against georef deltas
					poly = [(vert.co.x+dx, vert.co.y+dy, vert.co.z) for vert in face.verts]
					poly.append(poly[0])#close poly
					#In Blender face is up if points are in anticlockwise order
					#for shapefiles, face's up with clockwise order
					poly.reverse()
					polygons.append(poly)

				if self.mode == 'OBJ':
					for j, polygon in enumerate(polygons):
						outShp.polyz([polygon])
						outShp.record(bid=j)
				if self.mode == 'COLLEC':
					outShp.polyz(polygons)


			#Writing attributes Data
			if self.mode == 'COLLEC':
				attributes = {'bid':i}
				#attributes.update({k[0:maxFieldNameLen]:v for k, v in dict(obj).items()})
				for k, v in dict(obj).items():
					k = k[0:maxFieldNameLen]
					fType = next( (f[1] for f in outShp.fields if f[0] == k) )
					if fType in ('N', 'F'):
						try:
							v = float(v)
						except ValueError:
							log.info('Cannot cast value {} to float for appending field {}, NULL value will be inserted instead'.format(v, k))
							v = None
					attributes[k] = v
				attributes.update({f[0]:None for f in outShp.fields if f[0] not in attributes.keys()})
				outShp.record(**attributes)


		outShp.close()

		if wkt is not None:
			prjPath = os.path.splitext(filePath)[0] + '.prj'
			prj = open(prjPath, "w")
			prj.write(wkt)
			prj.close()

		self.report({'INFO'}, "Export complete")

		return {'FINISHED'}


def register():
	try:
		bpy.utils.register_class(EXPORTGIS_OT_shapefile)
	except ValueError as e:
		log.warning('{} is already registered, now unregister and retry... '.format(cls))
		unregister()
		bpy.utils.register_class(EXPORTGIS_OT_shapefile)

def unregister():
	bpy.utils.unregister_class(EXPORTGIS_OT_shapefile)

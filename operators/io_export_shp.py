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
			default = "*.shp",
			options = {'HIDDEN'},
			)

	exportType: EnumProperty(
			name = "Feature type",
			description = "Select feature type",
			items = [
				('POINTZ', 'Point', ""),
				('POLYLINEZ', 'Line', ""),
				('POLYGONZ', 'Polygon', "")
			])

	objectsSource: EnumProperty(
			name = "Objects",
			description = "Objects to export",
			items = [
				('COLLEC', 'Collection', "Export a collection of objects"),
				('SELECTED', 'Selected objects', "Export the current selection")
			],
			default = 'SELECTED'
			)

	def listCollections(self, context):
		return [(c.name, c.name, "Collection") for c in bpy.data.collections]

	selectedColl: EnumProperty(
		name = "Collection",
		description = "Select the collection to export",
		items = listCollections)

	mode: EnumProperty(
			name = "Mode",
			description = "Select the export strategy",
			items = [
				('OBJ2FEAT', 'Objects to features', "Create one multipart feature per object"),
				('MESH2FEAT', 'Mesh to features', "Decompose mesh primitives to separate features")
			],
			default = 'OBJ2FEAT'
			)


	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'

	def draw(self, context):
		#Function used by blender to draw the panel.
		layout = self.layout
		layout.prop(self, 'objectsSource')
		if self.objectsSource == 'COLLEC':
			layout.prop(self, 'selectedColl')
		layout.prop(self, 'mode')
		layout.prop(self, 'exportType')

	def execute(self, context):
		filePath = self.filepath
		folder = os.path.dirname(filePath)
		scn = context.scene
		geoscn = GeoScene(scn)

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

		if self.objectsSource == 'SELECTED':
			objects = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
		elif self.objectsSource == 'COLLEC':
			objects = bpy.data.collections[self.selectedColl].all_objects
			objects = [obj for obj in objects if obj.type == 'MESH']

		if not objects:
			self.report({'ERROR'}, "Selection is empty or does not contain any mesh")
			return {'CANCELLED'}


		outShp = shpWriter(filePath)
		if self.exportType == 'POLYGONZ':
			outShp.shapeType = POLYGONZ #15
		if self.exportType == 'POLYLINEZ':
			outShp.shapeType = POLYLINEZ #13
		if self.exportType == 'POINTZ' and self.mode == 'MESH2FEAT':
			outShp.shapeType = POINTZ
		if self.exportType == 'POINTZ' and self.mode == 'OBJ2FEAT':
			outShp.shapeType = MULTIPOINTZ

		#create fields (all needed fields sould be created before adding any new record)
		#TODO more robust evaluation, and check for boolean and date types
		cLen = 255 #string fields default length
		nLen = 20 #numeric fields default length
		dLen = 5 #numeric fields default decimal precision
		maxFieldNameLen = 8 #shp capabilities limit field name length to 8 characters
		outShp.field('objId','N', nLen) #export id
		for obj in objects:
			for k, v in obj.items():
				k = k[0:maxFieldNameLen]
				#evaluate the field type with the first value
				if k not in [f[0] for f in outShp.fields]:
					if isinstance(v, float) or isinstance(v, int):
						fieldType = 'N'
					elif isinstance(v, str):
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
					else:
						continue

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

			nFeat = 1

			if self.exportType == 'POINTZ':
				if len(bm.verts) == 0:
					continue

				#Extract coords & adjust values against georef deltas
				pts = [[v.co.x+dx, v.co.y+dy, v.co.z] for v in bm.verts]


				if self.mode == 'MESH2FEAT':
					for j, pt in enumerate(pts):
						outShp.pointz(*pt)
					nFeat = len(pts)
				elif self.mode == 'OBJ2FEAT':
					outShp.multipointz(pts)


			if self.exportType == 'POLYLINEZ':

				if len(bm.edges) == 0:
					continue

				lines = []
				for edge in bm.edges:
					#Extract coords & adjust values against georef deltas
					line = [(vert.co.x+dx, vert.co.y+dy, vert.co.z) for vert in edge.verts]
					lines.append(line)

				if self.mode == 'MESH2FEAT':
					for j, line in enumerate(lines):
						outShp.linez([line])
					nFeat = len(lines)
				elif self.mode == 'OBJ2FEAT':
					outShp.linez(lines)


			if self.exportType == 'POLYGONZ':

				if len(bm.faces) == 0:
					continue

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

				if self.mode == 'MESH2FEAT':
					for j, polygon in enumerate(polygons):
						outShp.polyz([polygon])
					nFeat = len(polygons)
				elif self.mode == 'OBJ2FEAT':
					outShp.polyz(polygons)


			#Writing attributes Data
			attributes = {'objId':i}
			for k, v in obj.items():
				k = k[0:maxFieldNameLen]
				if not any([f[0] == k for f in outShp.fields]):
					continue
				fType = next( (f[1] for f in outShp.fields if f[0] == k) )
				if fType in ('N', 'F'):
					try:
						v = float(v)
					except ValueError:
						log.info('Cannot cast value {} to float for appending field {}, NULL value will be inserted instead'.format(v, k))
						v = None
				attributes[k] = v
			#assign None to orphans shp fields (if the key does not exists in the custom props of this object)
			attributes.update({f[0]:None for f in outShp.fields if f[0] not in attributes.keys()})
			#Write
			for n in range(nFeat):
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
		log.warning('{} is already registered, now unregister and retry... '.format(EXPORTGIS_OT_shapefile))
		unregister()
		bpy.utils.register_class(EXPORTGIS_OT_shapefile)

def unregister():
	bpy.utils.unregister_class(EXPORTGIS_OT_shapefile)

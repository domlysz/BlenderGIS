# -*- coding:utf-8 -*-
import os, sys
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator
import bmesh
import math
import mathutils
from .shapefile import Reader as shpReader

from geoscene.geoscn import GeoScene
from geoscene.addon import PredefCRS, georefManagerLayout
from geoscene.proj import reprojPt, Reproj

featureType={
0:'Null',
1:'Point',
3:'PolyLine',
5:'Polygon',
8:'MultiPoint',
11:'PointZ',
13:'PolyLineZ',
15:'PolygonZ',
18:'MultiPointZ',
21:'PointM',
23:'PolyLineM',
25:'PolygonM',
28:'MultiPointM',
31:'MultiPatch'
}


"""
dbf fields type:
	C is ASCII characters
	N is a double precision integer limited to around 18 characters in length
	D is for dates in the YYYYMMDD format, with no spaces or hyphens between the sections
	F is for floating point numbers with the same length limits as N
	L is for logical data which is stored in the shapefile's attribute table as a short integer as a 1 (true) or a 0 (false).
	The values it can receive are 1, 0, y, n, Y, N, T, F or the python builtins True and False
"""


class IMPORT_SHP_FILE_DIALOG(Operator):
	"""Select shp file, loads the fields and start importgis.shapefile_props_dialog operator"""

	bl_idname = "importgis.shapefile_file_dialog"
	bl_label = "Import SHP"
	bl_options = {'INTERNAL'}

	# Import dialog properties
	filepath = StringProperty(
		name="File Path",
		description="Filepath used for importing the file",
		maxlen=1024,
		subtype='FILE_PATH' )

	filename_ext = ".shp"

	filter_glob = StringProperty(
			default = "*.shp",
			options = {'HIDDEN'} )

	def invoke(self, context, event):
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}

	def draw(self, context):
		layout = self.layout
		layout.label("Options will be available")
		layout.label("after selecting a file")

	def execute(self, context):
		if os.path.exists(self.filepath):
			bpy.ops.importgis.shapefile_props_dialog('INVOKE_DEFAULT', filepath=self.filepath)
		else:
			self.report({'ERROR'}, "Invalid file")
		return{'FINISHED'}



class IMPORT_SHP_PROPS_DIALOG(Operator):
	"""Shapefile importer properties dialog"""

	bl_idname = "importgis.shapefile_props_dialog"
	bl_description = 'Import from ESRI shapefile file format (.shp)'
	bl_label = "Import SHP"
	bl_options = {"INTERNAL"}

	filepath = StringProperty()

	#special function to auto redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True

	def listFields(self, context):
		fieldsItems = []
		try:
			shp = shpReader(self.filepath)
		except:
			self.report({'ERROR'}, "Unable to read shapefile")
			return fieldsItems
		fields = [field for field in shp.fields if field[0] != 'DeletionFlag'] #ignore default DeletionFlag field
		for i, field in enumerate(fields):
			#put each item in a tuple (key, label, tooltip)
			fieldsItems.append( (field[0], field[0], '') )
		return fieldsItems


	# Shapefile CRS definition
	def listPredefCRS(self, context):
		return PredefCRS.getEnumItems()

	shpCRS = EnumProperty(
		name = "Shapefile CRS",
		description = "Choose a Coordinate Reference System",
		items = listPredefCRS )

	# Elevation field
	useFieldElev = BoolProperty(
			name="Elevation from field",
			description="Extract z elevation value from an attribute field",
			default=False )
	fieldElevName = EnumProperty(
		name = "Field",
		description = "Choose field",
		items = listFields )

	#Extrusion field
	useFieldExtrude = BoolProperty(
			name="Extrusion from field",
			description="Extract z extrusion value from an attribute field",
			default=False )
	fieldExtrudeName = EnumProperty(
		name = "Field",
		description = "Choose field",
		items = listFields )

	#Extrusion axis
	extrusionAxis = EnumProperty(
			name="Extrude along",
			description="Select extrusion axis",
			items=[ ('Z', 'z axis', "Extrude along Z axis"),
			('NORMAL', 'Normal', "Extrude along normal")] )

	#Create separate objects
	separateObjects = BoolProperty(
			name="Separate objects",
			description="Import to separate objects instead one large object",
			default=False )

	#Name objects from field
	useFieldName = BoolProperty(
			name="Object name from field",
			description="Extract name for created objects from an attribute field",
			default=False )
	fieldObjName = EnumProperty(
		name = "Field",
		description = "Choose field",
		items = listFields )


	def draw(self, context):
		#Function used by blender to draw the panel.
		scn = context.scene
		layout = self.layout

		#
		layout.prop(self, 'useFieldElev')
		if self.useFieldElev:
			layout.prop(self, 'fieldElevName')
		#
		layout.prop(self, 'useFieldExtrude')
		if self.useFieldExtrude:
			layout.prop(self, 'fieldExtrudeName')
			layout.prop(self, 'extrusionAxis')
		#
		layout.prop(self, 'separateObjects')
		if self.separateObjects:
			layout.prop(self, 'useFieldName')
		else:
			self.useFieldName = False
		if self.separateObjects and self.useFieldName:
			layout.prop(self, 'fieldObjName')
		#
		#geoscnPrefs = context.user_preferences.addons['geoscene'].preferences
		row = layout.row(align=True)
		#row.prop(self, "shpCRS", text='CRS')
		split = row.split(percentage=0.35, align=True)
		split.label('CRS:')
		split.prop(self, "shpCRS", text='')
		row.operator("geoscene.add_predef_crs", text='', icon='ZOOMIN')
		#
		geoscn = GeoScene()
		if geoscn.isPartiallyGeoref:
			georefManagerLayout(self, context)


	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):

		elevField = self.fieldElevName if self.useFieldElev else ""
		extrudField = self.fieldExtrudeName if self.useFieldExtrude else ""
		nameField = self.fieldObjName if self.useFieldName else ""

		bpy.ops.importgis.shapefile('INVOKE_DEFAULT', filepath=self.filepath, shpCRS=self.shpCRS,
			fieldElevName=elevField, fieldExtrudeName=extrudField, fieldObjName=nameField,
			extrusionAxis=self.extrusionAxis, separateObjects=self.separateObjects)

		return{'FINISHED'}




class IMPORT_SHP(Operator):
	"""Import from ESRI shapefile file format (.shp)"""

	bl_idname = "importgis.shapefile" # important since its how bpy.ops.import.shapefile is constructed (allows calling operator from python console or another script)
	#bl_idname rules: must contain one '.' (dot) charactere, no capital letters, no reserved words (like 'import')
	bl_description = 'Import from ESRI shapefile file format (.shp)'
	bl_label = "Import SHP"
	bl_options = {"UNDO"}

	filepath = StringProperty()

	shpCRS = StringProperty(name = "Shapefile CRS", description = "Coordinate Reference System")

	fieldElevName = StringProperty(name = "Field", description = "Field name")
	fieldExtrudeName = StringProperty(name = "Field", description = "Field name")
	fieldObjName = StringProperty(name = "Field", description = "Field name")

	#Extrusion axis
	extrusionAxis = EnumProperty(
			name="Extrude along",
			description="Select extrusion axis",
			items=[ ('Z', 'z axis', "Extrude along Z axis"),
			('NORMAL', 'Normal', "Extrude along normal")]
			)
	#Create separate objects
	separateObjects = BoolProperty(
			name="Separate objects",
			description="Import to separate objects instead one large object",
			default=False
			)



	def execute(self, context):

		#Set cursor representation to 'loading' icon
		w = context.window
		w.cursor_set('WAIT')

		#Toogle object mode and deselect all
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass

		bpy.ops.object.select_all(action='DESELECT')

		#Path
		shpName = os.path.basename(self.filepath)[:-4]

		#Get shp reader
		print("Read shapefile...")
		try:
			shp = shpReader(self.filepath)
		except:
			self.report({'ERROR'}, "Unable to read shapefile")
			print("Unable to read shapefile")
			return {'FINISHED'}

		#Check shape type
		shpType = featureType[shp.shapeType]
		print('Feature type : '+shpType)
		if shpType not in ['Point','PolyLine','Polygon','PointZ','PolyLineZ','PolygonZ']:
			self.report({'ERROR'}, "Cannot process multipoint, multipointZ, pointM, polylineM, polygonM and multipatch feature type")
			return {'FINISHED'}

		#Get fields
		fields = [field for field in shp.fields if field[0] != 'DeletionFlag'] #ignore default DeletionFlag field
		fieldsNames = [field[0] for field in fields]
		#print("DBF fields : "+str(fieldsNames))

		if self.fieldElevName or self.fieldElevName or self.fieldExtrudeName:
			self.useDbf = True
		else:
			self.useDbf = False

		if self.fieldObjName and self.separateObjects:
			try:
				nameFieldIdx = fieldsNames.index(self.fieldObjName)
			except:
				self.report({'ERROR'}, "Unable to find name field")
				return {'FINISHED'}

		if self.fieldElevName:
			try:
				zFieldIdx = fieldsNames.index(self.fieldElevName)
			except:
				self.report({'ERROR'}, "Unable to find elevation field")
				return {'FINISHED'}

			if fields[zFieldIdx][1] not in ['N', 'F', 'L'] :
				self.report({'ERROR'}, "Elevation field do not contains numeric values")
				return {'FINISHED'}

		if self.fieldExtrudeName:
			try:
				extrudeFieldIdx = fieldsNames.index(self.fieldExtrudeName)
			except ValueError:
				self.report({'ERROR'}, "Unable to find extrusion field")
				return {'FINISHED'}

			if fields[extrudeFieldIdx][1] not in ['N', 'F', 'L'] :
				self.report({'ERROR'}, "Extrusion field do not contains numeric values")
				return {'FINISHED'}

		#Get shp and scene georef infos
		shpCRS = self.shpCRS
		geoscn = GeoScene()
		if geoscn.isBroken:
				self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
				return {'FINISHED'}
		scale = geoscn.scale #TODO
		if not geoscn.hasCRS:
			try:
				geoscn.crs = shpCRS
			except Exception as e:
				self.report({'ERROR'}, str(e))
				return {'FINISHED'}

		#Init reprojector class
		if geoscn.crs != shpCRS:
			print("Data will be reprojected from " + shpCRS + " to " + geoscn.crs)
			rprj = Reproj(shpCRS, geoscn.crs)

		#Get bbox
		if geoscn.crs != shpCRS:
			xmin, ymin, xmax, ymax = rprj.bbox(shp.bbox)
		else:
			xmin, ymin, xmax, ymax = shp.bbox
		bbox_dx = xmax-xmin
		bbox_dy = ymax-ymin
		center = (xmin+bbox_dx/2, ymin+bbox_dy/2)

		#Get or set georef dx, dy
		if not geoscn.isGeoref:
			dx, dy = center[0], center[1]
			geoscn.setOriginPrj(dx, dy)
		else:
			dx, dy = geoscn.getOriginPrj()

		#Tag if z will be extracted from shp geoms
		if shpType[-1] == 'Z' and not self.fieldElevName:
			self.useZGeom = True
		else:
			self.useZGeom = False

		#Get reader iterator (using iterator avoids loading all data in memory)
		#warn, shp with zero field will return an empty shapeRecords() iterator
		#to prevent this issue, iter only on shapes if there is no field required
		if self.useDbf:
			#Note: using shapeRecord solve the issue where number of shapes does not match number of table records
			#because it iter only on features with geom and record
			shpIter = shp.iterShapeRecords()
		else:
			shpIter = shp.iterShapes()
		nbFeats = shp.numRecords

		#Init Python lists expected by from_pydata() function
		if not self.separateObjects:
			meshVerts = []
			meshEdges = []
			meshFaces = []

		progress = -1

		#For each feature create a new bmesh
		#using an intermediate bmesh object allows some extra operation like extrusion
		#then extract bmesh data to python list formated as required by from_pydata function
		#using from_pydata is the fastest way to produce a large mesh (appending all geom to the same bmesh is exponentially slow)
		for i, feat in enumerate(shpIter):

			if self.useDbf:
				shape = feat.shape
				record = feat.record
			else:
				shape = feat

			#Progress infos
			pourcent = round(((i+1)*100)/nbFeats)
			if pourcent in list(range(0, 110, 10)) and pourcent != progress:
				progress = pourcent
				if pourcent == 100:
					print(str(pourcent)+'%')
				else:
					print(str(pourcent), end="%, ")
				sys.stdout.flush() #we need to flush or it won't print anything until after the loop has finished

			#Deal with multipart features
			#If the shape record has multiple parts, the 'parts' attribute will contains the index of
			#the first point of each part. If there is only one part then a list containing 0 is returned
			if (shpType == 'PointZ' or shpType == 'Point'): #point layer has no attribute 'parts'
				partsIdx = [0]
			else:
				try: #prevent "_shape object has no attribute parts" error
					partsIdx = shape.parts
				except:
					partsIdx = [0]
			nbParts = len(partsIdx)

			#Get list of shape's points
			pts = shape.points
			nbPts = len(pts)

			#Skip null geom
			if nbPts == 0:
				continue #go to next iteration of the loop

			#Reproj geom
			if geoscn.crs != shpCRS:
				pts = rprj.pts(pts)

			#Get extrusion offset
			if self.fieldExtrudeName:
				try:
					offset = float(record[extrudeFieldIdx])

				except:
					offset = 0 #null values will be set to zero

			#Create an empty BMesh
			bm = bmesh.new()

			#Iter over parts
			for j in range(nbParts):

				# EXTRACT 3D GEOM

				geom = [] #will contains a list of 3d points

				#Find first and last part index
				idx1 = partsIdx[j]
				if j+1 == nbParts:
					idx2 = nbPts
				else:
					idx2 = partsIdx[j+1]

				#Build 3d geom
				for k, pt in enumerate(pts[idx1:idx2]):
					if self.fieldElevName:
						try:
							z = float(record[zFieldIdx])
						except:
							z = 0 #null values will be set to zero
					elif self.useZGeom:
						z = shape.z[idx1:idx2][k]
					else:
						z = 0
					geom.append((pt[0], pt[1], z))

				#Shift coords
				geom = [(pt[0]-dx, pt[1]-dy, pt[2]) for pt in geom]

				# BUILD BMESH

				# POINTS
				if (shpType == 'PointZ' or shpType == 'Point'):
					vert = [bm.verts.new(pt) for pt in geom]
					#Extrusion
					if self.fieldExtrudeName and offset > 0:
						vect = (0, 0, offset) #along Z
						result = bmesh.ops.extrude_vert_indiv(bm, verts=vert)
						verts = result['verts']
						bmesh.ops.translate(bm, verts=verts, vec=vect)

				# LINES
				if (shpType == 'PolyLine' or shpType == 'PolyLineZ'):
					#Split polyline to lines
					n = len(geom)
					lines = [ (geom[i], geom[i+1]) for i in range(n) if i < n-1 ]
					#Build edges
					edges = []
					for line in lines:
						verts = [bm.verts.new(pt) for pt in line]
						edge = bm.edges.new(verts)
						edges.append(edge)
					#Extrusion
					if self.fieldExtrudeName and offset > 0:
						vect = (0, 0, offset) # along Z
						result = bmesh.ops.extrude_edge_only(bm, edges=edges)
						verts = [elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMVert)]
						bmesh.ops.translate(bm, verts=verts, vec=vect)

				# NGONS
				if (shpType == 'Polygon' or shpType == 'PolygonZ'):
					#According to the shapefile spec, polygons points are clockwise and polygon holes are counterclockwise
					#in Blender face is up if points are in anticlockwise order
					geom.reverse() #face up
					geom.pop() #exlude last point because it's the same as first pt
					if len(geom) >= 3: #needs 3 points to get a valid face
						verts = [bm.verts.new(pt) for pt in geom]
						face = bm.faces.new(verts)
						if face.normal < 0: #this is a polygon hole, bmesh cannot handle polygon hole
							pass #TODO
						#Extrusion
						if self.fieldExtrudeName and offset > 0:
							#update normal to avoid null vector
							bm.normal_update()
							#build translate vector
							if self.extrusionAxis == 'NORMAL':
								normal = face.normal
								vect = normal*offset
							elif self.extrusionAxis == 'Z':
								vect=(0, 0, offset)
							faces = bmesh.ops.extrude_discrete_faces(bm, faces=[face], use_select_history=False) #{'faces': [BMFace]}
							verts = faces['faces'][0].verts
							bmesh.ops.translate(bm, verts=verts, vec=vect)

			#Clean up and update the bmesh
			bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
			bm.verts.index_update()
			bm.edges.index_update()
			bm.faces.index_update()

			if self.separateObjects:

				if self.fieldObjName:
					try:
						name = record[nameFieldIdx]
					except:
						name = ''
					# null values will return a bytes object containing a blank string of length equal to fields length definition
					if isinstance(name, bytes):
						name = ''
					else:
						name = str(name)
				else:
					name = shpName

				#Calc bmesh bbox
				_xmin = min([pt.co.x for pt in bm.verts])
				_xmax = max([pt.co.x for pt in bm.verts])
				_ymin = min([pt.co.y for pt in bm.verts])
				_ymax = max([pt.co.y for pt in bm.verts])
				_zmin = min([pt.co.z for pt in bm.verts])
				_zmax = max([pt.co.z for pt in bm.verts])

				#Calc bmesh geometry origin and translate coords according to it
				#then object location will be set to initial bmesh origin
				#its a work around to bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
				ox = (_xmin + ((_xmax - _xmin) / 2))
				oy = (_ymin + ((_ymax - _ymin) / 2))
				oz = _zmin
				bmesh.ops.translate(bm, verts=bm.verts, vec=(-ox, -oy, -oz))

				#Create new mesh from bmesh
				mesh = bpy.data.meshes.new(name)
				bm.to_mesh(mesh)

				#Validate new mesh
				if mesh.validate():
					print('Imported mesh had some problem, check the result!')

				#Place obj
				obj = bpy.data.objects.new(name, mesh)
				context.scene.objects.link(obj)
				context.scene.objects.active = obj
				obj.select = True
				obj.location = (ox, oy, oz)

				# bpy operators can be very cumbersome when scene contains lot of objects
				# because it cause implicit scene updates calls
				# so we must avoid using operators when created many objects with the 'separate objects' option)
				##bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')

			else:
				#Extent lists with bmesh data
				offset = len(meshVerts)
				meshVerts.extend(v.co[:] for v in bm.verts)
				meshEdges.extend([[v.index + offset for v in e.verts] for e in bm.edges])
				meshFaces.extend([[v.index + offset for v in f.verts] for f in bm.faces])

			bm.free()

		#using from_pydata to create the final mesh
		if not self.separateObjects:

			mesh = bpy.data.meshes.new(shpName)
			mesh.from_pydata(meshVerts, meshEdges, meshFaces)

			#Validate new mesh
			if mesh.validate():
				print('Imported mesh had some problem, check the result!')

			obj = bpy.data.objects.new(shpName, mesh)
			context.scene.objects.link(obj)
			context.scene.objects.active = obj
			obj.select = True

			bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')



		#Adjust grid size
		# get object(s) bbox in 3dview from previously computed shapefile bbox
		xmin -= dx
		xmax -= dx
		ymin -= dy
		ymax -= dy
		# grid size and clip distance
		dstMax = round(max(abs(xmax), abs(xmin), abs(ymax), abs(ymin)))*2
		nbDigit = len(str(dstMax))
		scale = 10**(nbDigit-2)#1 digits --> 0.1m, 2 --> 1m, 3 --> 10m, 4 --> 100m, , 5 --> 1000m
		nbLines = round(dstMax/scale)
		targetDst = nbLines*scale
		# set each 3d view
		areas = context.screen.areas
		for area in areas:
			if area.type == 'VIEW_3D':
				space = area.spaces.active
				#Adjust floor grid and clip distance if the new obj is largest than actual settings
				if space.grid_lines*space.grid_scale < targetDst:
					space.grid_lines = nbLines
					space.grid_scale = scale
					space.clip_end = targetDst*10 #10x more than necessary
				#Zoom to selected
				overrideContext = {'area': area, 'region':area.regions[-1]}
				bpy.ops.view3d.view_selected(overrideContext)


		return {'FINISHED'}

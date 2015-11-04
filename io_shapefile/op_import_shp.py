# -*- coding:utf-8 -*-
import os
import bpy
import bmesh
import math
import mathutils
from .shapefile import Reader as shpReader

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

class ellps():
	"""ellipsoid"""
	def __init__(self, a, b):
		self.a =  a#equatorial radius in meters
		self.b =  b#polar radius in meters
		self.f = (self.a-self.b)/self.a#inverse flat
		self.perimeter = (2*math.pi*self.a)#perimeter at equator

ellpsGRS80 = ellps(6378137, 6356752.314245)#ellipsoid GRS80

def dd2meters(val):
	"""
	Convert decimal degrees to meters
	Correct at equator only but it's the way that "plate carré" works, we all know these horizontal distortions...
	"""
	global ellpsGRS80
	return val*(ellpsGRS80.perimeter/360)

def getFeaturesType(shapes):
	shpType=shapes[0].shapeType#Shapetype of first feature, if this feature is null then shapefile will not be process...
	#nt: Point features layer cannot be multipart
	return featureType[shpType]

def buildGeoms(meshName, shapes, shpType, zValues, dx, dy, zExtrude, extrudeAxis, angCoords=False):
	print("Process geometry...")
	zGeom=False
	mesh=False

	if (shpType == 'PointZ' or shpType == 'Point'):
		if zValues:#Z attributes data are user-defined priority
			pts=([(pt[0],pt[1],zValues[i]) for i, shape in enumerate(shapes) for pt in shape.points])
		elif shpType[-1] == 'Z':
			pts=([(pt[0],pt[1],shape.z[0]) for shape in shapes for pt in shape.points])
		else:
			z=0
			pts=([(pt[0],pt[1],z) for shape in shapes for pt in shape.points])
		if angCoords:
			pts = [(dd2meters(pt[0])-dx, dd2meters(pt[1])-dy, pt[2]) for pt in pts]#shift coords & convert dd to meters
		else:
			pts = [(pt[0]-dx, pt[1]-dy, pt[2]) for pt in pts]#shift coords
		mesh=addMesh(meshName, pts, shpType, zExtrude)

	elif (shpType == 'PolyLine' or shpType == 'PolyLineZ'):
		if shpType[-1] == 'Z' and not zValues:
			zGeom=True
		geoms=extractGeoms(shapes, zGeom, zFieldValues=zValues)
		shiftGeom(geoms, dx, dy, angCoords)
		#edges, initialGeoFeatureIdx = polylinesToLines(geoms)
		mesh=addMesh(meshName, geoms, shpType, zExtrude, extrudeAxis)

	elif (shpType == 'Polygon' or shpType == 'PolygonZ'):
		if shpType[-1] == 'Z' and not zValues:
			zGeom=True
		geoms=extractGeoms(shapes, zGeom, zFieldValues=zValues, polygon=True)
		shiftGeom(geoms, dx, dy, angCoords)
		mesh=addMesh(meshName, geoms, shpType, zExtrude, extrudeAxis)

	print("Mesh created")
	return mesh

def extractGeoms(shapes, zGeom=False, zFieldValues=False, polygon=False):
	geoms=[]
	for i, geom in enumerate(shapes):
		#Deal with multipart features
		try:
			partsIdx = geom.parts
			#If the shape record has multiple parts this attribute contains the index of the first point of each part.
			#If there is only one part then a list containing 0 is returned
		except:#prevent "_shape object has no attribute parts" error
			partsIdx = [0]
		nbParts=len(partsIdx)
		geomPts=geom.points
		nbPts=len(geomPts)
		#Get Z values --> attributes data are user-defined priority
		if zFieldValues:
			z=zFieldValues[i]
		elif zGeom:
			zValues=geom.z
		for j in range(nbParts):
			pts=[]
			#find first and last part index
			firstIdx=partsIdx[j]
			if j+1 == nbParts:
				lastIdx=nbPts
			else:
				lastIdx=partsIdx[j+1]
			#
			if zGeom and not zFieldValues:
				z=zValues[firstIdx:lastIdx]
			for k, pt in enumerate(geomPts[firstIdx:lastIdx]):
				if zFieldValues:#attributes data are user-defined priority
					thisZ=z
				elif zGeom:
					thisZ=z[k]
				else:
					thisZ=0
				pts.append((pt[0], pt[1], thisZ))
			if polygon:
				#According to the shapefile spec, polygons points are clockwise and polygon holes are counterclockwise
				#in Blender face is up if points are in anticlockwise order
				pts.reverse()#face up
				geoms.append(pts[:-1])#exlude last point because it's the same of first pt
			else:
				geoms.append(pts)
	return geoms

def shiftGeom(geoms, dx, dy, angCoords=False):
	for i, geom in enumerate(geoms):
		if angCoords:
			pts = [(dd2meters(pt[0])-dx, dd2meters(pt[1])-dy, pt[2]) for pt in geom]#shift coords & convert dd to meters
		else:
			pts = [(pt[0]-dx, pt[1]-dy, pt[2]) for pt in geom]
		geoms[i]=pts

def polylinesToLines(geom):
	edges=[]
	nbPts=len(geom)
	for i in range(nbPts):
		if i < nbPts-1:
			edges.append([geom[i],geom[i+1]])
	return edges

def addMesh(name, geoms, shpType, extrudeValues, extrudeAxis):
	print("Create mesh...")
	#Create an empty BMesh
	bm = bmesh.new()
	#Build bmesh
	nbGeoms=len(geoms)
	progress=-1
	for i, geom in enumerate(geoms):
		#progress bar
		pourcent=round(((i+1)*100)/nbGeoms)
		if pourcent in list(range(0,110,10)) and pourcent != progress:
			progress=pourcent
			print(str(pourcent)+'%')
		#build geom
		#POINT
		if (shpType == 'PointZ' or shpType == 'Point'):
			vert = bm.verts.new(geom)
			#Extrusion
			if extrudeValues:
				offset = extrudeValues[i]
				vect=(0,0,offset)#normal = Z
				result=bmesh.ops.extrude_vert_indiv(bm, verts=[vert])
				#verts=[elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMVert)]
				verts=result['verts']
				#translate
				bmesh.ops.translate(bm, verts=verts, vec=vect)
		#LINES
		if (shpType == 'PolyLine' or shpType == 'PolyLineZ'):
			#Split polyline to lines
			lines = polylinesToLines(geom)
			#build edges
			edges = []
			##edgesVerts = []
			for line in lines:
				verts = [bm.verts.new(pt) for pt in line]
				edge = bm.edges.new(verts)
				edges.append(edge)
				##edgesVerts.extend(verts)
			#Extrusion
			if extrudeValues:
				extrudeValue = extrudeValues[i]
				if not extrudeValue:
					extrudeValue = 0
				verts = extrudeEdgesBm(bm, edges, extrudeValue, extrudeAxis)
				##edgesVerts.extend(verts)
			#Merge edges to retrieve polyline
			##bmesh.ops.remove_doubles(bm, verts=edgesVerts, dist=0.0001)
		#NGONS
		if (shpType == 'Polygon' or shpType == 'PolygonZ'):
			if len(geom) >= 3:#needs 3 points to get face
				pts= [bm.verts.new(pt) for pt in geom]
				f = bm.faces.new(pts)
				#if f.normal < 0: #this is a polygon hole, bmesh cannot handle polygon hole
				#Extrusion
				if extrudeValues:
					extrudeValue = extrudeValues[i]
					if not extrudeValue:
						extrudeValue = 0
					extrudeFacesBm(bm, f, extrudeValue, extrudeAxis)
	#Finish up, write the bmesh to a new mesh
	bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
	mesh = bpy.data.meshes.new(name)
	bm.to_mesh(mesh)
	bm.free()
	return mesh


def extrudeEdgesBm(bm, edges, offset, axis):#Blender >= 2.65
	#if axis == 'NORMAL'
	#elif axis == 'Z':
	vect = (0,0,offset)#normal = Z
	result = bmesh.ops.extrude_edge_only(bm, edges=edges)
	#geom type filter
	verts = [elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMVert)]
	#translate
	bmesh.ops.translate(bm, verts=verts, vec=vect)
	return verts

def extrudeFacesBm(bm, face, offset, axis):#Blender >= 2.65
	#update normal to avoid null vector
	bm.normal_update()
	#build translate vector
	if axis == 'NORMAL':
		normal=face.normal
		vect=normal*offset
	elif axis == 'Z':
		vect=(0,0,offset)
	#make geom list for bmesh ops input --> [BMVert, BMEdge, BMFace]
	geom = list(face.verts)+list(face.edges)+[face]
	#extrude
	result = bmesh.ops.extrude_face_region(bm, geom=geom)#return dict {"geom":[BMVert, BMEdge, BMFace]}
	#geom type filter
	verts = [elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMVert)]
	##edges=[elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMEdge)]
	##faces=[elem for elem in result['geom'] if isinstance(elem, bmesh.types.BMFace)]
	#translate
	bmesh.ops.translate(bm, verts=verts, vec=vect)


def placeObj(shpMesh, objName):
	bpy.ops.object.select_all(action='DESELECT')
	#create an object with that mesh
	obj = bpy.data.objects.new(objName, shpMesh)
	# Link object to scene
	bpy.context.scene.objects.link(obj)
	bpy.context.scene.objects.active = obj
	obj.select = True
	bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
	return obj


def update3dViews(nbLines, scaleSize):
	targetDst=nbLines*scaleSize
	wms=bpy.data.window_managers
	for wm in wms:
		for window in wm.windows:
			for area in window.screen.areas:
				if area.type == 'VIEW_3D':
					for space in area.spaces:
						if space.type == 'VIEW_3D':
							if space.grid_lines*space.grid_scale < targetDst:
								space.grid_lines=nbLines
								space.grid_scale=scaleSize
								space.clip_end=targetDst*10#10x more than necessary
	#bpy.ops.view3d.view_all()#wrong context

#------------------------------------------------------------------------

from bpy_extras.io_utils import ImportHelper #helper class defines filename and invoke() function which calls the file selector
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator


class IMPORT_SHP(Operator, ImportHelper):
	"""Import from ESRI shapefile file format (.shp)"""
	bl_idname = "importgis.shapefile" # important since its how bpy.ops.import.shapefile is constructed (allows calling operator from python console or another script)
	#bl_idname rules: must contain one '.' (dot) charactere, no capital letters, no reserved words (like 'import')
	bl_description = 'Import from ESRI shapefile file format (.shp)'
	bl_label = "Import SHP"
	bl_options = {"UNDO"}

	# ImportHelper class properties
	filename_ext = ".shp"
	filter_glob = StringProperty(
			default="*.shp",
			options={'HIDDEN'},
			)

	# List of operator properties, the attributes will be assigned
	# to the class instance from the operator settings before calling.

	# Elevation field
	useFieldElev = BoolProperty(
			name="Elevation from field",
			description="Extract z elevation value from an attribute field",
			default=False
			)
	fieldElevName = StringProperty(name = "Field name")
	#Extrusion field
	useFieldExtrude = BoolProperty(
			name="Extrusion from field",
			description="Extract z extrusion value from an attribute field",
			default=False
			)
	fieldExtrudeName = StringProperty(name = "Field name")
	#Extrusion axis
	extrusionAxis = EnumProperty(
			name="Extrude along",
			description="Select extrusion axis",
			items=[ ('Z', 'z axis', "Extrude along Z axis"),
			('NORMAL', 'Normal', "Extrude along normal")]
			)
	#Use previous object translation
	useGeoref = BoolProperty(
			name="Consider georeferencing",
			description="Adjust position next to previous import",
			default=True
			)
	#Decimal degrees to meters
	angCoords = BoolProperty(
			name="Angular coords",
			description="Will convert decimal degrees coordinates to meters",
			default=False
			)
	#Adjust grid size
	adjust3dView = BoolProperty(
			name="Adjust 3D view",
			description="Adjust grid floor and clip distances",
			default=True
			)
	#Create separate objects
	separateObjects = BoolProperty(
			name="Separate objects",
			description="Import to separate objects instead one large object",
			default=False
			)
	#Name objects from field
	useFieldName = BoolProperty(
			name="Object name from field",
			description="Extract name for created objects from an attribute field",
			default=False
			)
	fieldObjName = StringProperty(name = "Field name")


	def draw(self, context):
		#Function used by blender to draw the panel.
		scn = bpy.context.scene
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
		if self.separateObjects and self.useFieldName:
			layout.prop(self, 'fieldObjName')
		#
		if "Georef X" in scn and "Georef Y" in scn:
			isGeoref = True
		else:
			isGeoref = False
		if isGeoref:
			layout.prop(self, 'useGeoref')
		else:
			self.useGeoref = False
		#
		layout.prop(self, 'angCoords')
		#
		layout.prop(self, 'adjust3dView')


	def execute(self, context):
		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		#Default values
		elevValues=False
		extrudeValues=False
		#Path
		filePath = self.filepath
		name=os.path.basename(filePath)[:-4]
		#Read shp
		print("Read shapefile...")
		try:
			shp=shpReader(filePath)
			#Get fields names
			fields = shp.fields #3 values tuple (nom, type, longueur, précision)
			fieldsNames=[field[0].lower() for field in fields if field[0] != 'DeletionFlag']#lower() allows case-insensitive
			print("DBF fields : "+str(fieldsNames))
		except:
			self.report({'ERROR'}, "Unable to read shapefile")
			print("Unable to read shapefile")
			return {'FINISHED'}
		#Extract geoms
		try:
			shapes=shp.shapes()
			shpType = getFeaturesType(shapes)
		except:
			self.report({'ERROR'}, "Unable to extract geometry")
			print("Unable to extract geometry")
			return {'FINISHED'}
		#Extract data
		if self.useFieldElev or self.useFieldExtrude or self.useFieldName:
			try:
				records=shp.records()
			except:
				self.report({'ERROR'}, "Unable to read DBF table")
				print("Unable to read DBF table")
				return {'FINISHED'}
		#Purge null geom
		nbFeatures = len(shapes)
		if self.useFieldElev or self.useFieldExtrude or self.useFieldName:
			try:
				shapes, records = zip(*[(shape, records[i]) for i, shape in enumerate(shapes)])# if len(shape.points) > 0])
			except IndexError:
				self.report({'ERROR'}, "Shapefiles reading error: number of shapes does not match number of table records.")
				print("Shapefiles reading error: number of shapes does not match number of table records")
				return {'FINISHED'}				
		else:
			shapes = [shape for shape in shapes if len(shape.points) > 0]
		print(str(nbFeatures-len(shapes))+' null features ignored')
		#Check shape type
		print('Feature type : '+shpType)
		if shpType not in ['Point','PolyLine','Polygon','PointZ','PolyLineZ','PolygonZ']:
			self.report({'ERROR'}, "Cannot process multipoint, multipointZ, pointM, polylineM, polygonM and multipatch feature type")
			print("Cannot process multipoint, multipointZ, pointM, polylineM, polygonM and multipatch feature type")
			return {'FINISHED'}
		#Calculate XY bbox
		if (shpType == 'PointZ' or shpType == 'Point'):
			pts=([pt for shape in shapes for pt in shape.points])
			xmin, xmax, ymin, ymax = min([pt[0] for pt in pts]), max([pt[0] for pt in pts]), min([pt[1] for pt in pts]), max([pt[1] for pt in pts])
		else:
			bbox = [shape.bbox for shape in shapes] #xmin, ymin, xmax, ymax
			xmin=min([box[0] for box in bbox])
			xmax=max([box[2] for box in bbox])
			ymin=min([box[1] for box in bbox])
			ymax=max([box[3] for box in bbox])
		if self.angCoords:
			xmin, xmax, ymin, ymax = dd2meters(xmin), dd2meters(xmax), dd2meters(ymin), dd2meters(ymax)
		bbox_dx=xmax-xmin
		bbox_dy=ymax-ymin
		center=(xmin+bbox_dx/2, ymin+bbox_dy/2)
		#Get obj names from field
		if self.useFieldName:
			try:
				fieldIdx = fieldsNames.index(self.fieldObjName.lower())
			except:
				self.report({'ERROR'}, "Unable to find name field")
				print("Unable to find name field");
				return {'FINISHED'}
			nameValues = [str(record[fieldIdx]) for record in records]
		#Get Elevation Values
		if self.useFieldElev:
			try:
				fieldIdx=fieldsNames.index(self.fieldElevName.lower())
			except:
				self.report({'ERROR'}, "Unable to find elevation field")
				print("Unable to find elevation field")
				return {'FINISHED'}
			#Get Z values
			if (shpType == 'PointZ' or shpType == 'Point'): #point layer has no attribute 'parts'
				try:
					elevValues=[float(record[fieldIdx]) for record in records]
				except ValueError:
					self.report({'ERROR'}, "Elevation values aren't numeric")
					print("Elevation values aren't numeric")
					return {'FINISHED'}
			else:
				try:
					#elevValues=[float(record[fieldIdx]) for i, record in enumerate(records) for part in range(len(shapes[i].parts))]
					#finally extractGeom funtion doesn't needs elevValues splited by parts
					elevValues=[float(record[fieldIdx]) for i, record in enumerate(records)]
				except ValueError:
					self.report({'ERROR'}, "Elevation values aren't numeric")
					print("Elevation values aren't numeric")
					return {'FINISHED'}
				except AttributeError:#no attribute 'parts'
					self.report({'ERROR'}, "Shapefiles reading error")
					print("Shapefiles reading error")
					return {'FINISHED'}
		#Get Extrusion Values
		if self.useFieldExtrude:
			try:
				fieldIdx=fieldsNames.index(self.fieldExtrudeName.lower())
			except ValueError:
				self.report({'ERROR'}, "Unable to find extrusion field")
				print("Unable to find extrusion field")
				return {'FINISHED'}
			except AttributeError:
				self.report({'ERROR'}, "No attribute parts")
				print("No attribute parts")
				return {'FINISHED'}
			#Get extrude values
			if (shpType == 'PointZ' or shpType == 'Point'): #point layer has no attribute 'parts'
				try:
					extrudeValues=[float(record[fieldIdx]) for record in records]
				except ValueError:
					self.report({'ERROR'}, "Elevation values aren't numeric")
					print("Elevation values aren't numeric")
					return {'FINISHED'}
			else:
				try:
					extrudeValues=[float(record[fieldIdx]) for i, record in enumerate(records) for part in range(len(shapes[i].parts))]
				except ValueError:
					self.report({'ERROR'}, "Elevation values aren't numeric")
					print("Elevation values aren't numeric")
					return {'FINISHED'}
				except AttributeError:#no attribute 'parts'
					self.report({'ERROR'}, "Shapefiles reading error")
					print("Shapefiles reading error")
					return {'FINISHED'}
		#Get dx, dy
		scn = bpy.context.scene
		if self.useGeoref:
			dx, dy = scn["Georef X"], scn["Georef Y"]
		else:
			dx, dy = center[0], center[1]
		#Launch geometry builder
		if not self.separateObjects:#create one object
			mesh = buildGeoms(name, shapes, shpType, elevValues, dx, dy, extrudeValues, self.extrusionAxis, self.angCoords)
			if not mesh:
				print("Cannot process multipoint, multipointZ, pointM, polylineM, polygonM and multipatch feature type")
				return {'FINISHED'}
			#Place the mesh
			obj = placeObj(mesh, name)
		else:#create multiple objects
			for i, shape in enumerate(shapes):
				#get obj name
				if self.useFieldName:
					objName = nameValues[i]
				else:
					objName = name
				#get elevation value
				if self.useFieldElev:
					elevValue = [elevValues[i]]
				else:
					elevValue = False
				#get extrusion value
				if self.useFieldExtrude:
					extrudeValue = [extrudeValues[i]]
				else:
					extrudeValue = False
				#build geom &place obj
				mesh = buildGeoms(objName, [shape], shpType, elevValue, dx, dy, extrudeValue, self.extrusionAxis, self.angCoords)
				if not mesh:
					print("Cannot process multipoint, multipointZ, pointM, polylineM, polygonM and multipatch feature type")
					return {'FINISHED'}
				obj = placeObj(mesh, objName)
		#Add custom properties define x & y translation to retrieve georeferenced model
		scn["Georef X"], scn["Georef Y"] = dx, dy
		#Adjust grid size
		if self.adjust3dView:
			#bbox = obj.bound_box
			#xmin=min([pt[0] for pt in bbox])
			#xmax=max([pt[0] for pt in bbox])
			#ymin=min([pt[1] for pt in bbox])
			#ymax=max([pt[1] for pt in bbox])
			xmin-=dx
			xmax-=dx
			ymin-=dy
			ymax-=dy
			#la coordonnée x ou y la + éloignée de l'origin = la distance d'un demi coté du carré --> fois 2 pr avoir la longueur d'un coté
			dstMax=round(max(abs(xmax), abs(xmin), abs(ymax), abs(ymin)))*2
			nbDigit=len(str(dstMax))
			scale=10**(nbDigit-2)#1 digits --> 0.1m, 2 --> 1m, 3 --> 10m, 4 --> 100m, , 5 --> 1000m
			nbLines=round(dstMax/scale)
			update3dViews(nbLines, scale)
		print("Finish")
		return {'FINISHED'}


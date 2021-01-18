import os
import time
import json
import random

import logging
log = logging.getLogger(__name__)

import bpy
import bmesh
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty

from .lib.osm import overpy

from ..geoscene import GeoScene
from .utils import adjust3Dview, getBBOX, DropToGround, isTopView

from ..core.proj import Reproj, reprojBbox, reprojPt, utm
from ..core.utils import perf_clock

from ..core import settings
USER_AGENT = settings.user_agent

PKG, SUBPKG = __package__.split('.', maxsplit=1)

#WARNING: There is a known bug with using an enum property with a callback, Python must keep a reference to the strings returned
#https://developer.blender.org/T48873
#https://developer.blender.org/T38489
def getTags():
	prefs = bpy.context.preferences.addons[PKG].preferences
	tags = json.loads(prefs.osmTagsJson)
	return tags

#Global variable that will be seed by getTags() at each operator invoke
#then callback of dynamic enum will use this global variable
OSMTAGS = []



closedWaysArePolygons = ['aeroway', 'amenity', 'boundary', 'building', 'craft', 'geological', 'historic', 'landuse', 'leisure', 'military', 'natural', 'office', 'place', 'shop' , 'sport', 'tourism']
closedWaysAreExtruded = ['building']


def queryBuilder(bbox, tags=['building', 'highway'], types=['node', 'way', 'relation'], format='json'):

		'''
		QL template syntax :
		[out:json][bbox:ymin,xmin,ymax,xmax];(node[tag1];node[tag2];((way[tag1];way[tag2];);>;);relation;);out;
		'''

		#s,w,n,e <--> ymin,xmin,ymax,xmax
		bboxStr = ','.join(map(str, bbox.toLatlon()))

		if not types:
			#if no type filter is defined then just select all kind of type
			types = ['node', 'way', 'relation']

		head = "[out:"+format+"][bbox:"+bboxStr+"];"

		union = '('
		#all tagged nodes
		if 'node' in types:
			if tags:
				union += ';'.join( ['node['+tag+']' for tag in tags] ) + ';'
			else:
				union += 'node;'
		#all tagged ways with all their nodes (recurse down)
		if 'way' in types:
			union += '(('
			if tags:
				union += ';'.join( ['way['+tag+']' for tag in tags] ) + ';);'
			else:
				union += 'way;);'
			union += '>;);'
		#all relations (no filter tag applied)
		if 'relation' in types or 'rel' in types:
			union += 'relation;'
		union += ')'

		output = ';out;'
		qry = head + union + output

		return qry





########################
def joinBmesh(src_bm, dest_bm):
	'''
	Hack to join a bmesh to another
	TODO: replace this function by bmesh.ops.duplicate when 'dest' argument will be implemented
	'''
	buff = bpy.data.meshes.new(".temp")
	src_bm.to_mesh(buff)
	dest_bm.from_mesh(buff)
	bpy.data.meshes.remove(buff)





class OSM_IMPORT():
	"""Import from Open Street Map"""

	def enumTags(self, context):
		items = []
		##prefs = context.preferences.addons[PKG].preferences
		##osmTags = json.loads(prefs.osmTagsJson)
		#we need to use a global variable as workaround to enum callback bug (T48873, T38489)
		for tag in OSMTAGS:
			#put each item in a tuple (key, label, tooltip)
			items.append( (tag, tag, tag) )
		return items

	filterTags: EnumProperty(
			name = "Tags",
			description = "Select tags to include",
			items = enumTags,
			options = {"ENUM_FLAG"})

	featureType: EnumProperty(
			name = "Type",
			description = "Select types to include",
			items = [
				('node', 'Nodes', 'Request all nodes'),
				('way', 'Ways', 'Request all ways'),
				('relation', 'Relations', 'Request all relations')
			],
			default = {'way'},
			options = {"ENUM_FLAG"}
			)

	# Elevation object
	def listObjects(self, context):
		objs = []
		for index, object in enumerate(bpy.context.scene.objects):
			if object.type == 'MESH':
				#put each object in a tuple (key, label, tooltip) and add this to the objects list
				objs.append((str(index), object.name, "Object named " + object.name))
		return objs

	objElevLst: EnumProperty(
		name="Elev. object",
		description="Choose the mesh from which extract z elevation",
		items=listObjects )

	useElevObj: BoolProperty(
			name="Elevation from object",
			description="Get z elevation value from an existing ground mesh",
			default=False )

	separate: BoolProperty(name='Separate objects', description='Warning : can be very slow with lot of features', default=False)

	buildingsExtrusion: BoolProperty(name='Buildings extrusion', description='', default=True)
	defaultHeight: FloatProperty(name='Default Height', description='Set the height value using for extrude building when the tag is missing', default=20)
	levelHeight: FloatProperty(name='Level height', description='Set a height for a building level, using for compute extrude height based on number of levels', default=3)
	randomHeightThreshold: FloatProperty(name='Random height threshold', description='Threshold value for randomize default height', default=0)

	def draw(self, context):
		layout = self.layout
		row = layout.row()
		row.prop(self, "featureType", expand=True)
		row = layout.row()
		col = row.column()
		col.prop(self, "filterTags", expand=True)
		layout.prop(self, 'useElevObj')
		if self.useElevObj:
			layout.prop(self, 'objElevLst')
		layout.prop(self, 'buildingsExtrusion')
		if self.buildingsExtrusion:
			layout.prop(self, 'defaultHeight')
			layout.prop(self, 'randomHeightThreshold')
			layout.prop(self, 'levelHeight')
		layout.prop(self, 'separate')


	def build(self, context, result, dstCRS):
		prefs = context.preferences.addons[PKG].preferences
		scn = context.scene
		geoscn = GeoScene(scn)
		scale = geoscn.scale #TODO

		#Init reprojector class
		try:
			rprj = Reproj(4326, dstCRS)
		except Exception as e:
			log.error('Unable to reproject data', exc_info=True)
			self.report({'ERROR'}, "Unable to reproject data ckeck logs for more infos")
			return {'FINISHED'}

		if self.useElevObj:
			if not self.objElevLst:
				log.error('There is no elevation object in the scene to get elevation from')
				self.report({'ERROR'}, "There is no elevation object in the scene to get elevation from")
				return {'FINISHED'}
			elevObj = scn.objects[int(self.objElevLst)]
			rayCaster = DropToGround(scn, elevObj)

		bmeshes = {}
		vgroupsObj = {}

		#######
		def seed(id, tags, pts):
			'''
			Sub funtion :
				1. create a bmesh from [pts]
				2. seed a global bmesh or create a new object
			'''
			if len(pts) > 1:
				if pts[0] == pts[-1] and any(tag in closedWaysArePolygons for tag in tags):
					type = 'Areas'
					closed = True
					pts.pop() #exclude last duplicate node
				else:
					type = 'Ways'
					closed = False
			else:
				type = 'Nodes'
				closed = False

			#reproj and shift coords
			pts = rprj.pts(pts)
			dx, dy = geoscn.crsx, geoscn.crsy

			if self.useElevObj:
				#pts = [rayCaster.rayCast(v[0]-dx, v[1]-dy).loc for v in pts]
				pts = [rayCaster.rayCast(v[0]-dx, v[1]-dy) for v in pts]
				hits = [pt.hit for pt in pts]
				if not all(hits) and any(hits):
					zs = [p.loc.z for p in pts if p.hit]
					meanZ = sum(zs) / len(zs)
					for v in pts:
						if not v.hit:
							v.loc.z = meanZ
				pts = [pt.loc for pt in pts]
			else:
				pts = [ (v[0]-dx, v[1]-dy, 0) for v in pts]

			#Create a new bmesh
			#>using an intermediate bmesh object allows some extra operation like extrusion
			bm = bmesh.new()

			if len(pts) == 1:
				verts = [bm.verts.new(pt) for pt in pts]

			elif closed: #faces
				verts = [bm.verts.new(pt) for pt in pts]
				face = bm.faces.new(verts)
				#ensure face is up (anticlockwise order)
				#because in OSM there is no particular order for closed ways
				face.normal_update()
				if face.normal.z < 0:
					face.normal_flip()

				if self.buildingsExtrusion and any(tag in closedWaysAreExtruded for tag in tags):
					offset = None
					if "height" in tags:
							htag = tags["height"]
							htag.replace(',', '.')
							try:
								offset = int(htag)
							except:
								try:
									offset = float(htag)
								except:
									for i, c in enumerate(htag):
										if not c.isdigit():
											try:
												offset, unit = float(htag[:i]), htag[i:].strip()
												#todo : parse unit  25, 25m, 25 ft, etc.
											except:
												offset = None
					elif "building:levels" in tags:
						try:
							offset = int(tags["building:levels"]) * self.levelHeight
						except ValueError as e:
							offset = None

					if offset is None:
						minH = self.defaultHeight - self.randomHeightThreshold
						if minH < 0 :
							minH = 0
						maxH = self.defaultHeight + self.randomHeightThreshold
						offset = random.randint(minH, maxH)

					#Extrude
					"""
					if self.extrusionAxis == 'NORMAL':
						normal = face.normal
						vect = normal * offset
					elif self.extrusionAxis == 'Z':
					"""
					vect = (0, 0, offset)
					faces = bmesh.ops.extrude_discrete_faces(bm, faces=[face]) #return {'faces': [BMFace]}
					verts = faces['faces'][0].verts
					if self.useElevObj:
						#Making flat roof
						z = max([v.co.z for v in verts]) + offset #get max z coord
						for v in verts:
							v.co.z = z
					else:
						bmesh.ops.translate(bm, verts=verts, vec=vect)


			elif len(pts) > 1: #edge
				verts = [bm.verts.new(pt) for pt in pts]
				for i in range(len(pts)-1):
					edge = bm.edges.new( [verts[i], verts[i+1] ])


			if self.separate:

				name = tags.get('name', str(id))

				mesh = bpy.data.meshes.new(name)
				bm.to_mesh(mesh)
				mesh.update()
				mesh.validate()

				obj = bpy.data.objects.new(name, mesh)

				#Assign tags to custom props
				obj['id'] = str(id) #cast to str to avoid overflow error "Python int too large to convert to C int"
				for key in tags.keys():
					obj[key] = tags[key]

				#Put object in right collection
				if self.filterTags:
					tagsList = self.filterTags
				else:
					tagsList = OSMTAGS
				if any(tag in tagsList for tag in tags):
					for k in tagsList:
						if k in tags:
							try:
								tagCollec = layer.children[k]
							except KeyError:
								tagCollec = bpy.data.collections.new(k)
								layer.children.link(tagCollec)
							tagCollec.objects.link(obj)
							break
				else:
					layer.objects.link(obj)

				obj.select_set(True)


			else:
				#Grouping

				bm.verts.index_update()
				#bm.edges.index_update()
				#bm.faces.index_update()

				if self.filterTags:

					#group by tags (there could be some duplicates)
					for k in self.filterTags:

						if k in extags: #
							objName = type + ':' + k
							kbm = bmeshes.setdefault(objName, bmesh.new())
							offset = len(kbm.verts)
							joinBmesh(bm, kbm)

				else:
					#group all into one unique mesh
					objName = type
					_bm = bmeshes.setdefault(objName, bmesh.new())
					offset = len(_bm.verts)
					joinBmesh(bm, _bm)


				#vertex group
				name = tags.get('name', None)
				vidx = [v.index + offset for v in bm.verts]
				vgroups = vgroupsObj.setdefault(objName, {})

				for tag in extags:
					#if tag in osmTags:#filter
					if not tag.startswith('name'):
						vgroup = vgroups.setdefault('Tag:'+tag, [])
						vgroup.extend(vidx)

				if name is not None:
					#vgroup['Name:'+name] = [vidx]
					vgroup = vgroups.setdefault('Name:'+name, [])
					vgroup.extend(vidx)

				if 'relation' in self.featureType:
					for rel in result.relations:
						name = rel.tags.get('name', str(rel.id))
						for member in rel.members:
							#todo: remove duplicate members
							if id == member.ref:
								vgroup = vgroups.setdefault('Relation:'+name, [])
								vgroup.extend(vidx)



			bm.free()


		######

		if self.separate:
			layer = bpy.data.collections.new('OSM')
			context.scene.collection.children.link(layer)

		#Build mesh
		waysNodesId = [node.id for way in result.ways for node in way.nodes]

		if 'node' in self.featureType:

			for node in result.nodes:

				#extended tags list
				extags = list(node.tags.keys()) + [k + '=' + v for k, v in node.tags.items()]

				if node.id in waysNodesId:
					continue

				if self.filterTags and not any(tag in self.filterTags for tag in extags):
					continue

				pt = (float(node.lon), float(node.lat))
				seed(node.id, node.tags, [pt])


		if 'way' in self.featureType:

			for way in result.ways:

				extags = list(way.tags.keys()) + [k + '=' + v for k, v in way.tags.items()]

				if self.filterTags and not any(tag in self.filterTags for tag in extags):
					continue

				pts = [(float(node.lon), float(node.lat)) for node in way.nodes]
				seed(way.id, way.tags, pts)



		if not self.separate:

			for name, bm in bmeshes.items():
				if prefs.mergeDoubles:
					bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
				mesh = bpy.data.meshes.new(name)
				bm.to_mesh(mesh)
				bm.free()

				mesh.update()#calc_edges=True)
				mesh.validate()
				obj = bpy.data.objects.new(name, mesh)
				scn.collection.objects.link(obj)
				obj.select_set(True)

				vgroups = vgroupsObj.get(name, None)
				if vgroups is not None:
					#for vgroupName, vgroupIdx in vgroups.items():
					for vgroupName in sorted(vgroups.keys()):
						vgroupIdx = vgroups[vgroupName]
						g = obj.vertex_groups.new(name=vgroupName)
						g.add(vgroupIdx, weight=1, type='ADD')


		elif 'relation' in self.featureType:

			relations = bpy.data.collections.new('Relations')
			bpy.data.collections['OSM'].children.link(relations)
			importedObjects = bpy.data.collections['OSM'].objects

			for rel in result.relations:

				name = rel.tags.get('name', str(rel.id))
				try:
					relation = relations.children[name] #or bpy.data.collections[name]
				except KeyError:
					relation = bpy.data.collections.new(name)
					relations.children.link(relation)

				for member in rel.members:

					#todo: remove duplicate members

					for obj in importedObjects:
						#id = int(obj.get('id', -1))
						try:
							id = int(obj['id'])
						except:
							id = None
						if id == member.ref:
							try:
								relation.objects.link(obj)
							except Exception as e:
								log.error('Object {} already in group {}'.format(obj.name, name), exc_info=True)

				#cleanup
				if not relation.objects:
					bpy.data.collections.remove(relation)





#######################

class IMPORTGIS_OT_osm_file(Operator, OSM_IMPORT):

	bl_idname = "importgis.osm_file"
	bl_description = 'Select and import osm xml file'
	bl_label = "Import OSM"
	bl_options = {"UNDO"}

	# Import dialog properties
	filepath: StringProperty(
		name="File Path",
		description="Filepath used for importing the file",
		maxlen=1024,
		subtype='FILE_PATH' )

	filename_ext = ".osm"

	filter_glob: StringProperty(
			default = "*.osm",
			options = {'HIDDEN'} )

	def invoke(self, context, event):
		#workaround to enum callback bug (T48873, T38489)
		global OSMTAGS
		OSMTAGS = getTags()
		#open file browser
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}

	def execute(self, context):

		scn = context.scene

		if not os.path.exists(self.filepath):
			self.report({'ERROR'}, "Invalid file")
			return{'CANCELLED'}

		try:
			bpy.ops.object.mode_set(mode='OBJECT')
		except:
			pass
		bpy.ops.object.select_all(action='DESELECT')

		#Set cursor representation to 'loading' icon
		w = context.window
		w.cursor_set('WAIT')

		#Spatial ref system
		geoscn = GeoScene(scn)
		if geoscn.isBroken:
			self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
			return {'CANCELLED'}

		#Parse file
		t0 = perf_clock()
		api = overpy.Overpass()
		#with open(self.filepath, "r", encoding"utf-8") as f:
		#	result = api.parse_xml(f.read()) #WARNING read() load all the file into memory
		result = api.parse_xml(self.filepath)
		t = perf_clock() - t0
		log.info('File parsed in {} seconds'.format(round(t, 2)))

		#Get bbox
		bounds = result.bounds
		lon = (bounds["minlon"] + bounds["maxlon"])/2
		lat = (bounds["minlat"] + bounds["maxlat"])/2
		#Set CRS
		if not geoscn.hasCRS:
			try:
				geoscn.crs = utm.lonlat_to_epsg(lon, lat)
			except Exception as e:
				log.error("Cannot set UTM CRS", exc_info=True)
				self.report({'ERROR'}, "Cannot set UTM CRS, ckeck logs for more infos")
				return {'CANCELLED'}
		#Set scene origin georef
		if not geoscn.hasOriginPrj:
			x, y = reprojPt(4326, geoscn.crs, lon, lat)
			geoscn.setOriginPrj(x, y)

		#Build meshes
		t0 = perf_clock()
		self.build(context, result, geoscn.crs)
		t = perf_clock() - t0
		log.info('Mesh build in {} seconds'.format(round(t, 2)))

		bbox = getBBOX.fromScn(scn)
		adjust3Dview(context, bbox)

		return{'FINISHED'}




########################

class IMPORTGIS_OT_osm_query(Operator, OSM_IMPORT):
	"""Import from Open Street Map"""

	bl_idname = "importgis.osm_query"
	bl_description = 'Query for Open Street Map data covering the current view3d area'
	bl_label = "Get OSM"
	bl_options = {"UNDO"}

	#special function to auto redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True


	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'


	def invoke(self, context, event):
		#workaround to enum callback bug (T48873, T38489)
		global OSMTAGS
		OSMTAGS = getTags()

		return context.window_manager.invoke_props_dialog(self)


	def execute(self, context):

		prefs = bpy.context.preferences.addons[PKG].preferences
		scn = context.scene
		geoscn = GeoScene(scn)
		objs = context.selected_objects
		aObj = context.active_object

		if not geoscn.isGeoref:
				self.report({'ERROR'}, "Scene is not georef")
				return {'CANCELLED'}
		elif geoscn.isBroken:
				self.report({'ERROR'}, "Scene georef is broken, please fix it beforehand")
				return {'CANCELLED'}

		if len(objs) == 1 and aObj.type == 'MESH':
			bbox = getBBOX.fromObj(aObj).toGeo(geoscn)
		elif isTopView(context):
			bbox = getBBOX.fromTopView(context).toGeo(geoscn)
		else:
			self.report({'ERROR'}, "Please define the query extent in orthographic top view or by selecting a reference object")
			return {'CANCELLED'}

		if bbox.dimensions.x > 20000 or bbox.dimensions.y > 20000:
			self.report({'ERROR'}, "Too large extent")
			return {'CANCELLED'}

		#Get view3d bbox in lonlat
		bbox = reprojBbox(geoscn.crs, 4326, bbox)

		#Set cursor representation to 'loading' icon
		w = context.window
		w.cursor_set('WAIT')

		#Download from overpass api
		log.debug('Requests overpass server : {}'.format(prefs.overpassServer))
		api = overpy.Overpass(overpass_server=prefs.overpassServer, user_agent=USER_AGENT)
		query = queryBuilder(bbox, tags=list(self.filterTags), types=list(self.featureType), format='xml')
		log.debug('Overpass query : {}'.format(query)) # can fails with non utf8 chars

		try:
			result = api.query(query)
		except Exception as e:
			log.error("Overpass query failed", exc_info=True)
			self.report({'ERROR'}, "Overpass query failed, ckeck logs for more infos.")
			return {'CANCELLED'}
		else:
			log.info('Overpass query successful')

		self.build(context, result, geoscn.crs)

		bbox = getBBOX.fromScn(scn)
		adjust3Dview(context, bbox, zoomToSelect=False)

		return {'FINISHED'}

classes = [
	IMPORTGIS_OT_osm_file,
	IMPORTGIS_OT_osm_query
]

def register():
	for cls in classes:
		try:
			bpy.utils.register_class(cls)
		except ValueError as e:
			log.warning('{} is already registered, now unregister and retry... '.format(cls))
			bpy.utils.unregister_class(cls)
			bpy.utils.register_class(cls)

def unregister():
	for cls in classes:
		bpy.utils.unregister_class(cls)

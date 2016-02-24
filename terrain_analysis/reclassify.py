# -*- coding:utf-8 -*-

import os
import bpy
import math
from mathutils import Vector
#import numpy as np
from .utils.misc import getBBox, scale
from .utils.kmeans1D import kmeans1d, getBreaks
#from .utils.jenks_caspall import jenksCaspall
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, CollectionProperty, FloatVectorProperty
from bpy.types import PropertyGroup, UIList, Panel, Operator
from bpy.app.handlers import persistent
from .gradient import Color, Stop, Gradient



#Global var
########################################
#These variables are the bounds values of the topographic property represented
#this is an altitude (zmin & zmax) in meters if material represents a height map
#or a slope in degrees if material represents a slope map
#bounds values are used to scale user input (altitude or slope) between 0 and 1
#then scale values are used to setup color ramp node
inMin = 0
inMax = 0
# other global for handler check
scn = None
obj = None
mat = None
node = None

#Set up a propertyGroup and populate a CollectionProperty
#########################################
class CustomItem(PropertyGroup):

	#Define update function for FloatProperty
	def updStop(item, context):
		#first arg is the container of the prop to update, here a customItem
		if context.space_data is not None:
			if context.space_data.type == 'NODE_EDITOR':
				v = item.val
				i = item.idx
				node = context.active_node
				cr = node.color_ramp
				stops = cr.elements
				newPos = scale(v, inMin, inMax, 0, 1)
				#limit move between previous and next stops
				if i+1 == len(stops):#this is the last stop
					nextPos = 1
				else:
					nextPos = stops[i+1].position
				if i == 0:#this is the first stop
					prevPos = 0
				else:
					prevPos = stops[i-1].position
				#
				if newPos > nextPos:
					stops[i].position = nextPos
					item.val = scale(nextPos, 0, 1, inMin, inMax)
				elif newPos < prevPos:
					stops[i].position = prevPos
					item.val = scale(prevPos, 0, 1, inMin, inMax)
				else:
					stops[i].position = newPos

	#Define update function for color property
	def updColor(item, context):
		if context.space_data is not None:
			if context.space_data.type == 'NODE_EDITOR':
				color = item.color
				i = item.idx
				node = context.active_node
				cr = node.color_ramp
				stops = cr.elements
				stops[i].color = color

	#Properties in the group
	idx = IntProperty()
	val = FloatProperty(update=updStop)
	color = FloatVectorProperty(subtype='COLOR', min=0, max=1, update=updColor, size=4)


#Create and register ui list collection in scene properties
#PropertyGroup class need to be register before
bpy.utils.register_class(CustomItem)
bpy.types.Scene.uiListCollec = CollectionProperty(type=CustomItem)
#This one store the index of the selected item in the uilist
bpy.types.Scene.uiListIndex = IntProperty()

#POPULATE
#Make function to populate collection
def populateList(colorRampNode):
	setBounds()
	if colorRampNode is not None:
		if colorRampNode.bl_idname == 'ShaderNodeValToRGB':
			bpy.context.scene.uiListCollec.clear()
			cr = colorRampNode.color_ramp
			for i, stop in enumerate(cr.elements):
				v = scale(stop.position, 0, 1, inMin, inMax, )
				item = bpy.context.scene.uiListCollec.add()
				item.idx = i #warn. : assign idx before val because idx is used in property update function
				item.val = v #warn. : causes exec. of property update function
				item.color = stop.color



#Set others properties in scene and their update functions
#########################################
def updateAnalysisMode(scn, context):
	if context.space_data.type == 'NODE_EDITOR':
		#refresh
		node = context.active_node
		populateList(node)


bpy.types.Scene.analysisMode = EnumProperty(
			name = "Mode",
			description = "Choose the type of analysis this material do",
			items = [('HEIGHT', 'Height', "Height analysis"),
			('SLOPE', 'Slope', "Slope analysis"),
			('ASPECT', 'Aspect', "Aspect analysis")],
			update = updateAnalysisMode
			)

def setBounds():
	scn = bpy.context.scene
	mode = scn.analysisMode
	global inMin
	global inMax
	global obj
	if mode == 'HEIGHT':
		obj = scn.objects.active
		bbox = getBBox(obj)
		inMin = bbox['zmin']
		inMax = bbox['zmax']
	elif mode == 'SLOPE':
		#slope of a terrain won't exceed vertical plane (90°)
		#so for easiest calculation we consider slope between 0 and 100°
		inMin = 0
		inMax = 100
	elif mode == 'ASPECT':
		inMin = 0
		inMax = 360


#Handler to refresh ui list when user
# > select another obj
# > change active material
# > move, delete or add stop on the node
# > select another color ramp node
#########################################
@persistent
def scene_update(scn):
	global obj
	global mat
	global node
	#print(node.bl_idname)
	activeObj = scn.objects.active
	if activeObj is not None:
		activeMat = activeObj.active_material
		if activeMat is not None and activeMat.use_nodes:
			activeNode = activeMat.node_tree.nodes.active
			#check color ramp node edits
			if activeMat.is_updated:
				#if activeNode.bl_idname == 'ShaderNodeValToRGB':
				populateList(activeNode)
			#check selected obj
			if obj != activeObj:
				obj = activeObj
				populateList(activeNode)
			#check active material
			if mat != activeMat:
				mat = activeMat
				populateList(activeNode)
			#check selected node
			if node != activeNode:
				node = activeNode
				populateList(activeNode)


bpy.app.handlers.scene_update_post.append(scene_update)


#Set up ui list
#########################################
class Reclass_uilist(UIList):

	def getAspectLabels(self):
		vals = [round(item.val,2) for item in bpy.context.scene.uiListCollec]
		if vals == [0, 45, 135, 225, 315]:
			return ['N', 'E', 'S', 'W', 'N']
		elif vals == [0, 22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]:
			return ['N', 'N-E', 'E', 'S-E', 'S', 'S-W', 'W', 'N-W', 'N']
		elif vals == [0, 30, 90, 150, 210, 270, 330]:
			return ['N', 'N-E', 'S-E', 'S', 'S-W', 'N-W', 'N']
		elif vals == [0, 60, 120, 180, 240, 300, 360]:
			return ['N-E', 'E', 'S-E', 'S-W', 'W', 'N-W', 'N-E']
		elif vals == [0, 90, 270]:
			return ['N', 'S', 'N']
		elif vals == [0, 180]:
			return ['E', 'W']
		else:
			return False

	def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
		'''
		called for each item of the collection visible in the list
		must handle the three layout types 'DEFAULT', 'COMPACT' and 'GRID'
		data is the object containing the collection (in our case, the scene)
		item is the current drawn item of the collection (in our case a propertyGroup "customItem")
		index is index of the current item in the collection (optional)
		'''
		scn = bpy.context.scene
		mode = scn.analysisMode
		self.use_filter_show = False
		if self.layout_type in {'DEFAULT', 'COMPACT'}:
			if mode == 'ASPECT':
				aspectLabels = self.getAspectLabels()
				split = layout.split(percentage=0.2)
				if aspectLabels:
					split.label(aspectLabels[item.idx])
				else:
					split.label(str(item.idx+1))
				split = split.split(percentage=0.4)
				split.prop(item, "color", text="")
				split.prop(item, "val", text="")
			else:
				split = layout.split(percentage=0.2)
				#split.label(str(index))
				split.label(str(item.idx+1))
				split = split.split(percentage=0.4)
				split.prop(item, "color", text="")
				split.prop(item, "val", text="")
		elif self.layout_type in {'GRID'}:
			layout.alignment = 'CENTER'


#Make a Panel
#########################################
class Reclass_panel(Panel):
	"""Creates a panel in the properties of node editor"""
	bl_label = "Reclassify"
	bl_idname = "reclass_panel"
	bl_space_type = 'NODE_EDITOR'
	bl_region_type = 'UI'

	def draw(self, context):
		node = context.active_node
		if node is not None:
			if node.bl_idname == 'ShaderNodeValToRGB':
				layout = self.layout
				scn = context.scene
				layout.prop(scn, "analysisMode")
				row = layout.row()
				#Draw ui list with template_list function
				row.template_list("Reclass_uilist", "", scn, "uiListCollec", scn, "uiListIndex", rows=10)
				#Draw side tools
				col = row.column(align=True)
				col.operator("reclass.list_add", text="", icon='ZOOMIN')
				col.operator("reclass.list_rm", text="", icon='ZOOMOUT')
				col.operator("reclass.list_clear", text="", icon='FILE_PARENT')
				col.separator()
				col.operator("reclass.list_refresh", text="", icon='FILE_REFRESH')
				col.separator()
				col.operator("reclass.switch_interpolation", text="", icon='SMOOTHCURVE')
				col.operator("reclass.flip", text="", icon='ARROW_LEFTRIGHT')
				col.operator("reclass.gradient2", text="", icon="COLOR")
				col.operator("reclass.gradient3", text="", icon="GROUP_VCOL")
				col.operator("reclass.exportsvg", text="", icon="FORWARD")
				col.separator()
				col.operator("reclass.auto", text="", icon='FULLSCREEN_ENTER')
				##col.separator()
				##col.operator("reclass.settings", text="", icon='SCRIPTWIN')
				#Draw infos
				#row = layout.row()
				#row.label(scn.objects.active.name)
				row = layout.row()
				row.label("min = " + str(round(inMin,2)))
				row.label("max = " + str(round(inMax,2)))
				row = layout.row()
				row.label("delta = " + str(round(inMax-inMin,2)))


#Make Operators to manage ui list
#########################################

class Reclass_switchInterpolation(Operator):
	'''Switch color interpolation (continuous / discrete)'''
	bl_idname = "reclass.switch_interpolation"
	bl_label = "Switch color interpolation (continuous or discrete)"

	def execute(self, context):
		node = context.active_node
		cr = node.color_ramp
		cr.color_mode = 'RGB'
		if cr.interpolation != 'CONSTANT':
			cr.interpolation = 'CONSTANT'
		else:
			cr.interpolation = 'LINEAR'
		return {'FINISHED'}

class Reclass_flip(Operator):
	'''Flip color ramp'''
	bl_idname = "reclass.flip"
	bl_label = "Flip color ramp"

	def execute(self, context):
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		#buid reversed color ramp
		revStops = []
		for i, stop in reversed(list(enumerate(stops))):
			revPos = 1-stop.position
			color = tuple(stop.color)
			revStops.append((revPos, color))
		#assign new position and color
		for i, stop in enumerate(stops):
			#stop.position = newStops[i][0]
			stop.color = revStops[i][1]
		#refresh
		populateList(node)
		return {'FINISHED'}

class Reclass_refresh(Operator):
	"""Refresh list to match node setting"""
	bl_idname = "reclass.list_refresh"
	bl_label = "Populate list"

	def execute(self, context):
		node = context.active_node
		populateList(node)
		return {'FINISHED'}


class Reclass_clear(Operator):
	"""Clear color ramp"""
	bl_idname = "reclass.list_clear"
	bl_label = "Clear list"

	def execute(self, context):
		#bpy.context.scene.uiListCollec.clear()
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		#remove stops from color ramp
		for stop in reversed(stops):
			if len(stops) > 1:#cannot remove last element
				stops.remove(stop)
			else:
				stop.position = 0
		#refresh ui list
		populateList(node)
		return{'FINISHED'}


class Reclass_addStop(bpy.types.Operator):
	"""Add stop"""
	bl_idname = "reclass.list_add"
	bl_label = "Add stop"

	def execute(self, context):
		lst = bpy.context.scene.uiListCollec
		currentIdx = bpy.context.scene.uiListIndex
		if currentIdx > len(lst)-1:
			#return {'FINISHED'}
			currentIdx = 0 #move ui selection to first idx
		#lst.add()
		#
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		if len(stops) >=32:
			self.report({'ERROR'}, "Ramp is limited to 32 colors")
			return {'FINISHED'}
		currentPos = stops[currentIdx].position
		if currentIdx == len(stops)-1:#last stop
			nextPos = 1.0
		else:
			nextPos = stops[currentIdx+1].position
		newPos = currentPos + ((nextPos-currentPos)/2)
		stops.new(newPos)
		#Refresh list
		populateList(node)
		#Move selection in ui list
		bpy.context.scene.uiListIndex = currentIdx+1
		return {'FINISHED'}


class Reclass_rmStop(bpy.types.Operator):
	"""Remove stop"""
	bl_idname = "reclass.list_rm"
	bl_label = "Remove Stop"

	def execute(self, context):
		currentIdx = bpy.context.scene.uiListIndex
		lst = bpy.context.scene.uiListCollec
		if currentIdx > len(lst)-1:
			return {'FINISHED'}
		#lst.remove(currentIdx)
		#
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		if len(stops) > 1: #cannot remove last element
			stops.remove(stops[currentIdx])
		#Refresh list
		populateList(node)
		#Move selecton in ui list if last element has been removed
		if currentIdx > len(lst)-1:
			bpy.context.scene.uiListIndex = currentIdx-1
		return {'FINISHED'}



#Make Operators to auto reclassify
#########################################

def clearRamp(stops, startColor=(0,0,0,1), endColor=(1,1,1,1), startPos=0, endPos=1):
	#clear actual color ramp
	for stop in reversed(stops):
		if len(stops) > 1:#cannot remove last element
			stops.remove(stop)
		else:#move last element to first position
			first = stop
			first.position = startPos
			first.color = startColor
	#Add last stop
	last = stops.new(endPos)
	last.color = endColor
	return (first, last)

def getValues():
	'''Return mesh data values (z, slope or az) for classification'''
	scn = bpy.context.scene
	obj = scn.objects.active
	#make a temp mesh with modifiers apply
	#mesh = obj.data #modifiers not apply
	mesh = obj.to_mesh(scn, apply_modifiers=True, settings='PREVIEW')
	mesh.transform(obj.matrix_world)
	#
	mode = scn.analysisMode
	if mode == 'HEIGHT':
		values = [vertex.co.z for vertex in mesh.vertices]
	elif mode == 'SLOPE':
		z = Vector((0,0,1))
		m = obj.matrix_world
		values =  [math.degrees(z.angle(m * face.normal)) for face in mesh.polygons]
	elif mode == 'ASPECT':
		y = Vector((0,1,0))
		m = obj.matrix_world
		#values =  [math.degrees(y.angle(m * face.normal)) for face in mesh.polygons]
		values = []
		for face in mesh.polygons:
			normal = face.normal.copy()
			normal.z = 0 #project vector into XY plane
			try:
				a = math.degrees(y.angle(m * normal))
			except ValueError:
				pass#zero length vector as no angle
			else:
				#returned angle is between 0° (north) to 180° (south)
				#we must correct it to get angle between 0 to 360°
				if normal.x <0:
					a = 360 - a
				values.append(a)
	values.sort()
	#remove temp mesh
	bpy.data.meshes.remove(mesh)

	return values


class Reclass_auto(Operator):
	'''Auto reclass by equal interval or fixed classe number'''
	bl_idname = "reclass.auto"
	bl_label = "Reclass by equal interval or fixed classe number"

	autoReclassMode = EnumProperty(
			name="Mode",
			description="Select auto reclassify mode",
			items=[
			('CLASSES_NB', 'Fixed classes number', "Define the expected number of classes"),
			('EQUAL_STEP', 'Equal interval value', "Define step value between classes"),
			('TARGET_STEP', 'Target interval value', "Define target step value that stops will match"),
			('QUANTILE', 'Quantile', 'Assigns the same number of data values to each class.'),
			('1DKMEANS', 'Natural breaks', 'kmeans clustering optimized for one dimensional data'),
			('ASPECT', 'Aspect reclassification', "Value define the number of azimuth")]
			)
	color1 = FloatVectorProperty(name="Start color", subtype='COLOR', min=0, max=1, size=4)
	color2 = FloatVectorProperty(name="End color", subtype='COLOR', min=0, max=1, size=4)
	value = IntProperty(name="Value", default=4)

	def invoke(self, context, event):
		#Set color to actual ramp
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		self.color1 = stops[0].color
		self.color2 = stops[len(stops)-1].color
		#Show dialog with operator properties
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def execute(self, context):
		node = context.active_node
		cr = node.color_ramp
		#switch to linear so new stops will have correctly evaluate color
		cr.color_mode = 'RGB'
		cr.interpolation = 'LINEAR'
		stops = cr.elements
		#Get colors
		startColor = self.color1
		endColor = self.color2

		if self.autoReclassMode == 'TARGET_STEP':
			interval = self.value
			delta = inMax-inMin
			nbClasses = math.ceil(delta/interval)
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			clearRamp(stops, startColor, endColor)
			nextStop = inMin + interval - (inMin % interval)
			while nextStop < inMax:
				position = scale(nextStop, inMin, inMax, 0, 1)
				stop = stops.new(position)
				nextStop += interval

		if self.autoReclassMode == 'EQUAL_STEP':
			interval = self.value
			delta = inMax-inMin
			nbClasses = math.ceil(delta/interval)
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			clearRamp(stops, startColor, endColor)
			val = inMin
			for i in range(nbClasses-1):
				val += interval
				position = scale(val, inMin, inMax, 0, 1)
				stop = stops.new(position)

		if self.autoReclassMode == 'CLASSES_NB':
			nbClasses = self.value
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			delta = inMax-inMin
			if nbClasses >= delta:
				self.report({'ERROR'}, "Too many classes")
				return {'FINISHED'}
			clearRamp(stops, startColor, endColor)
			interval = delta/nbClasses
			val = inMin
			for i in range(nbClasses-1):
				val += interval
				position = scale(val, inMin, inMax, 0, 1)
				stop = stops.new(position)

		if self.autoReclassMode == 'ASPECT':
			bpy.context.scene.analysisMode = 'ASPECT'
			delta = inMax-inMin #360°
			interval = 360 / self.value
			nbClasses = self.value #math.ceil(delta/interval)
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			first, last = clearRamp(stops, startColor, endColor)
			offset = interval/2
			intervalNorm = scale(interval, inMin, inMax, 0, 1)
			offsetNorm = scale(offset, inMin, inMax, 0, 1)
			#move actual last stop to before last position
			last.position -= intervalNorm + offsetNorm
			#add intermediates stops
			val = 0
			for i in range(nbClasses-2):
				if i == 0:
					val += offset
				else:
					val += interval
				position = scale(val, inMin, inMax, 0, 1)
				stop = stops.new(position)
			#add last
			stop = stops.new(1-offsetNorm)
			stop.color = first.color
			cr.interpolation = 'CONSTANT'

		if self.autoReclassMode == 'QUANTILE':
			nbClasses = self.value
			values = getValues()
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			if nbClasses >= len(values):
				self.report({'ERROR'}, "Too many classes")
				return {'FINISHED'}
			clearRamp(stops, startColor, endColor)
			n = len(values)
			q = int(n/nbClasses) #number of value per quantile
			cumulative_q = q
			previousVal = scale(0, 0, 1, inMin, inMax)
			for i in range(nbClasses-1):
				val = values[cumulative_q]
				if val != previousVal:
					position = scale(val, inMin, inMax, 0, 1)
					stop = stops.new(position)
					previousVal = val
				cumulative_q += q

		if self.autoReclassMode == '1DKMEANS':
			nbClasses = self.value
			values = getValues()
			if nbClasses >= 32:
				self.report({'ERROR'}, "Ramp is limited to 32 colors")
				return {'FINISHED'}
			if nbClasses >= len(values):
				self.report({'ERROR'}, "Too many classes")
				return {'FINISHED'}
			clearRamp(stops, startColor, endColor)
			#compute clusters
			#clusters = jenksCaspall(values, nbClasses, 4)
			#for val in clusters.breaks:
			clusters = kmeans1d(values, nbClasses)
			for val in getBreaks(values, clusters):
				position = scale(val, inMin, inMax, 0, 1)
				stop = stops.new(position)

		#refresh
		populateList(node)
		return {'FINISHED'}


#Operator to change color ramp
#########################################

colorSpaces = [('RGB', 'RGB', "RGB color space"),
		('HSV', 'HSV', "HSV color space")]

interpoMethods = [('LINEAR', 'Linear', "Linear interpolation"),
		('SPLINE', 'Spline', "Spline interpolation (Akima's method)"),
		('DISCRETE', 'Discrete', "No interpolation (return previous color)"),
		('NEAREST', 'Nearest', "No interpolation (return nearest color)") ]


##not used
class Reclass_gradient(Operator):
	'''Define colors gradient between two colors'''
	bl_idname = "reclass.gradient"
	bl_label = "Define colors gradient between two colors"

	color1 = FloatVectorProperty(name="Start color", subtype='COLOR', min=0, max=1, size=4)
	color2 = FloatVectorProperty(name="End color", subtype='COLOR', min=0, max=1, size=4)

	def invoke(self, context, event):
		#Set color to actual ramp
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		self.color1 = stops[0].color
		self.color2 = stops[len(stops)-1].color
		#Show dialog with operator properties
		wm = context.window_manager
		return wm.invoke_props_dialog(self)

	def execute(self, context):
		node = context.active_node
		cr = node.color_ramp
		cr.color_mode = 'RGB'
		cr.interpolation = 'LINEAR'
		stops = cr.elements
		positions = [stop.position for stop in stops]
		#clear actual color ramp
		clearRamp(stops, self.color1, self.color2, positions[0], positions[-1])
		#Add intermediate stops
		for pos in positions[1:len(positions)-1]:
			stops.new(pos)
		#refresh
		populateList(node)
		return {'FINISHED'}




#Multiple stop
class ColorList(PropertyGroup):
	color = FloatVectorProperty(subtype='COLOR', min=0, max=1, size=4)

bpy.utils.register_class(ColorList)
bpy.types.Scene.colorRampPreview = CollectionProperty(type=ColorList)


class Reclass_gradient2(Operator):
	'''Quick colors gradient edit'''
	bl_idname = "reclass.gradient2"
	bl_label = "Quick colors gradient edit"

	colorSpace = EnumProperty(
			name="Space",
			description="Select interpolation color space",
			items = colorSpaces)

	method = EnumProperty(
			name="Method",
			description="Select interpolation method",
			items = interpoMethods)

	#special function to redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True

	def updatePreview(self, context):
		#feed colors collection for preview
		context.scene.colorRampPreview.clear()
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		if self.fitGradient:
			minPos, maxPos = stops[0].position, stops[-1].position
			delta = maxPos-minPos
		else:
			delta = 1
		offset = delta/(self.nbColors-1)
		position = 0
		for i in range(self.nbColors):
			item = bpy.context.scene.colorRampPreview.add()
			item.color = cr.evaluate(position)
			position += offset
		return

	fitGradient = BoolProperty(update=updatePreview)

	nbColors = IntProperty(
			name="Number of colors",
			description="Set the number of colors needed to define the quick quadient",
			min=2, default=4, update=updatePreview)

	def invoke(self, context, event):
		#update collection of colors preview
		self.updatePreview(context)
		#Show dialog with operator properties
		wm = context.window_manager
		return wm.invoke_props_dialog(self, width=200, height=200)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, "colorSpace", text='Space')
		layout.prop(self, "method", text='Method')
		layout.prop(self, "fitGradient", text="Fit gradient to min/max positions")
		layout.prop(self, "nbColors", text='Number of colors')
		row = layout.row(align=True)
		colorItems = context.scene.colorRampPreview
		for i in range(self.nbColors):
			colorItem = colorItems[i]
			row.prop(colorItem, 'color', text='')

	def execute(self, context):
		#build gradient
		colorList = context.scene.colorRampPreview
		colorRamp = Gradient()
		nbColors = len(colorList)
		offset = 1/(nbColors-1)
		position = 0
		for i, item in enumerate(colorList):
			color = Color(list(item.color), 'rgb')
			colorRamp.addStop(round(position,4), color)
			position += offset
		#get color ramp node
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		#rescale
		if self.fitGradient:
			minPos, maxPos = stops[0].position, stops[-1].position
			colorRamp.rescale(minPos, maxPos)
		#update colors
		for stop in stops:
			stop.color = colorRamp.evaluate(stop.position, self.colorSpace, self.method).rgba
		#
		if self.colorSpace == 'HSV':
			cr.color_mode = 'HSV'
		else:
			cr.color_mode = 'RGB'
		#refresh
		populateList(node)
		return {'FINISHED'}

#SVG COLOR RAMP
def filesList(inFolder, ext):
	lst = os.listdir(inFolder)
	extLst=[elem for elem in lst if os.path.splitext(elem)[1]==ext]
	extLst.sort()
	return extLst

folder = os.path.dirname(os.path.realpath(__file__)) + os.sep + "gradients" + os.sep
if not os.path.exists(folder):
	os.makedirs(folder)
svgFiles = filesList(folder, '.svg')

colorPreviewRange = 20

class Reclass_gradient3(Operator):
	'''Define colors gradient with presets'''
	bl_idname = "reclass.gradient3"
	bl_label = "Define colors gradient with presets"

	def listSVG(self, context):
		#Function used to update the gradient list used by the dropdown box.
		svgs = [] #list containing tuples of each object
		for index, svg in enumerate(svgFiles): #iterate over all objects
			svgs.append((str(index), os.path.splitext(svg)[0], folder+svg)) #tuple (key, label, tooltip)
		return svgs

	def updatePreview(self, context):
		if len(self.colorPresets) == 0:
			return
		#build gradient
		enumIdx = int(self.colorPresets)
		path = folder+svgFiles[enumIdx]
		colorRamp = Gradient(path)
		#make preview
		nbColors = colorPreviewRange
		interpoGradient = colorRamp.getRangeColor(nbColors, self.colorSpace, self.method)
		for i, stop in enumerate(interpoGradient.stops):
			item = bpy.context.scene.colorRampPreview[i]
			item.color = stop.color.rgba
		return

	colorPresets = EnumProperty(
			name="preset",
			description="Select a color ramp preset",
			items=listSVG,
			update=updatePreview
			)

	colorSpace = EnumProperty(
			name="Space",
			description="Select interpolation color space",
			items = colorSpaces,
			update = updatePreview
			)

	method = EnumProperty(
			name="Method",
			description="Select interpolation method",
			items = interpoMethods,
			update = updatePreview
			)

	fitGradient = BoolProperty()

	def invoke(self, context, event):
		#clear collection
		context.scene.colorRampPreview.clear()
		#feed collection
		for i in range(colorPreviewRange):
			bpy.context.scene.colorRampPreview.add()
		#update colors preview
		self.updatePreview(context)
		#Show dialog with operator properties
		wm = context.window_manager
		return wm.invoke_props_dialog(self, width=200, height=200)

	def draw(self, context):#layout for invoke props modal dialog
		#operator.draw() is different from panel.draw()
		#because it's only called once (when the pop-up is created)
		layout = self.layout
		layout.prop(self, "colorSpace")
		layout.prop(self, "method")
		layout.prop(self, "colorPresets", text='')
		row = layout.row(align=True)
		row.enabled = False
		for item in context.scene.colorRampPreview:
			row.prop(item, 'color', text='')
		row = layout.row()
		row.prop(self, "fitGradient", text="Fit gradient to min/max positions")

	def execute(self, context):
		if len(self.colorPresets) == 0:
			return {'FINISHED'}
		#build gradient
		enumIdx = int(self.colorPresets)
		path = folder+svgFiles[enumIdx]
		colorRamp = Gradient(path)
		#get color ramp node
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		#rescale
		if self.fitGradient:
			minPos, maxPos = stops[0].position, stops[-1].position
			colorRamp.rescale(minPos, maxPos)
		#update colors
		for stop in stops:
			stop.color = colorRamp.evaluate(stop.position, self.colorSpace, self.method).rgba
		#
		if self.colorSpace == 'HSV':
			cr.color_mode = 'HSV'
		else:
			cr.color_mode = 'RGB'
		#refresh
		populateList(node)
		return {'FINISHED'}


class Reclass_exportSVG(Operator):
	'''Export current gradient to SVG file'''
	bl_idname = "reclass.exportsvg"
	bl_label = "Export current gradient to SVG file"

	name = StringProperty(description="Put name of SVG file")
	n = IntProperty(default=5, description="Select expected number of interpolate colors")

	gradientType = EnumProperty(
			name="Build method",
			description="Select methods to build gradient",
			items = [('SELF_STOPS', 'Use actual stops', ""),
			('INTERPOLATE', 'Interpolate n colors', "")]
			)

	makeDiscrete = BoolProperty(name="Make discrete", description="Build discrete svg gradient")

	colorSpace = EnumProperty(
			name="Color space",
			description="Select interpolation color space",
			items = colorSpaces)

	method = EnumProperty(
			name="Interp. method",
			description="Select interpolation method",
			items = interpoMethods)

	#special function to redraw an operator popup called through invoke_props_dialog
	def check(self, context):
		return True

	def invoke(self, context, event):
		#Show dialog with operator properties
		wm = context.window_manager
		return wm.invoke_props_dialog(self, width=250, height=200)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, "name", text='Name')
		layout.prop(self, "gradientType")
		layout.prop(self, "makeDiscrete")
		if self.gradientType == "INTERPOLATE":
			layout.separator()
			layout.label('Interpolation options')
			layout.prop(self, "colorSpace", text='Color space')
			layout.prop(self, "method", text='Method')
			layout.prop(self, "n", text="Number of colors")

	def execute(self, context):
		#Get node color ramp
		node = context.active_node
		cr = node.color_ramp
		stops = cr.elements
		#Build gradient class
		colorRamp = Gradient()
		for stop in stops:
			color = Color(list(stop.color), 'rgba')
			colorRamp.addStop(stop.position, color)
		#write svg
		svgPath = folder + self.name + '.svg'
		if self.gradientType == "INTERPOLATE":
			interpoGradient = colorRamp.getRangeColor(self.n, self.colorSpace, self.method)
			interpoGradient.exportSVG(svgPath, self.makeDiscrete)
		elif self.gradientType == "SELF_STOPS":
			colorRamp.exportSVG(svgPath, self.makeDiscrete)
		#update svg files list
		global svgFiles
		svgFiles = filesList(folder, '.svg')
		return {'FINISHED'}

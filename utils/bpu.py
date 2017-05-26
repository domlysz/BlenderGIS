
'''Blender Python Utilities (bpu)'''

import bpy


def adjust3Dview(context, bbox, zoomToSelect=True):

	# grid size and clip distance
	dstMax = round(max(abs(bbox.xmax), abs(bbox.xmin), abs(bbox.ymax), abs(bbox.ymin)))*2
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
			if zoomToSelect:
				overrideContext = context.copy()
				overrideContext['area'] = area
				overrideContext['region'] = area.regions[-1]
				bpy.ops.view3d.view_selected(overrideContext)


def showTextures(context):
	'''Force view mode with textures'''
	scn = context.scene
	for area in context.screen.areas:
		if area.type == 'VIEW_3D':
			space = area.spaces.active
			space.show_textured_solid = True
			if scn.render.engine == 'CYCLES':
				area.spaces.active.viewport_shade = 'TEXTURED'
			elif scn.render.engine == 'BLENDER_RENDER':
				area.spaces.active.viewport_shade = 'SOLID'

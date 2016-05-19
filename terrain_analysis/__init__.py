# -*- coding:utf-8 -*-

#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****

bl_info = {
	"name": "[bgis] Terrain analysis",
	"description": "Analyse height, slope and aspect of a terrain mesh",
	"author": "This script is public domain",
	'license': 'GPL',
	'deps': '',
	"version": (1, 0),
	"blender": (2, 7, 0),
	"location": "3D View > GIS Tools || Node editor > Properties",
	"warning": "",
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	"category": "Node Editor"}

#http://wiki.blender.org/index.php/Dev:Py/Scripts/Cookbook/Code_snippets/Multi-File_packages
#Work with F8 but doesn't work when user disable/enable addon in user prefs (in this cas 'bpy' in locals() return False)
if "bpy" in locals():
	import importlib
	if "reclassify" in locals():
		importlib.reload(reclassify)
	if "nodes_builder" in locals():
		importlib.reload(nodes_builder)
else:
	from . import reclassify, nodes_builder

import bpy

	
def register():
	bpy.utils.register_module(__name__)
	#bpy.utils.register_class(Reclass_panel)

def unregister():
	bpy.utils.unregister_module(__name__)
	# > clear existing ui list
	del bpy.types.Scene.uiListCollec
	del bpy.types.Scene.uiListIndex
	del bpy.types.Scene.colorRampPreview
	# > clear existing handlers
	bpy.app.handlers.scene_update_post.clear()

if __name__ == "__main__":
	register()

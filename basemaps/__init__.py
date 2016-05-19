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
	'name': '[bgis] Basemaps',
	'description': 'Display map service (TMS, WMS, WMTS) in Blender',
	'author': 'domLysz',
	'license': 'GPL',
	'deps': '',
	'version': (0, 3),
	'blender': (2, 7, 6),
	'location': 'View3D > Tools > GIS',
	'warning': '',
	'wiki_url': 'https://github.com/domlysz/BlenderGIS/wiki',
	'tracker_url': '',
	'link': '',
	'support': 'COMMUNITY',
	'category': '3D View'
	}

import bpy
from .mapviewer import *


def register():
	bpy.utils.register_module(__name__)
	wm = bpy.context.window_manager
	km = wm.keyconfigs.active.keymaps['3D View']
	kmi = km.keymap_items.new(idname='view3d.map_start', value='PRESS', type='NUMPAD_ASTERIX', ctrl=False, alt=False, shift=False, oskey=False)

def unregister():
	wm = bpy.context.window_manager
	km = wm.keyconfigs.active.keymaps['3D View']
	kmi = km.keymap_items.remove(km.keymap_items['view3d.map_start'])
	bpy.utils.unregister_module(__name__)


if __name__ == "__main__":
	register()

# -*- coding:utf-8 -*-

import math

####################################

#        Tiles maxtrix definitions

####################################

# Three ways to define a grid (inpired by http://mapproxy.org/docs/1.8.0/configuration.html#id6):
# - submit a list of resolutions > "resolutions": [32,16,8,4] (This parameters override the others)
# - submit just "resFactor", initial res is computed such as at zoom level zero, 1 tile covers whole bounding box
# - submit "resFactor" and "initRes"


# About Web Mercator
# Technically, the Mercator projection is defined for any latitude up to (but not including)
# 90 degrees, but it makes sense to cut it off sooner because it grows exponentially with
# increasing latitude. The logic behind this particular cutoff value, which is the one used
# by Google Maps, is that it makes the projection square. That is, the rectangle is equal in
# the X and Y directions. In this case the maximum latitude attained must correspond to y = w/2.
# y = 2*pi*R / 2 = pi*R --> y/R = pi
# lat = atan(sinh(y/R)) = atan(sinh(pi))
# wm_origin = (-20037508, 20037508) with 20037508 = GRS80.perimeter / 2

cutoff_lat = math.atan(math.sinh(math.pi)) * 180/math.pi #= 85.05112°


GRIDS = {


	"WM" : {
		"name" : 'Web Mercator',
		"description" : 'Global grid in web mercator projection',
		"CRS": 'EPSG:3857',
		"bbox": [-180, -cutoff_lat, 180, cutoff_lat], #w,s,e,n
		"bboxCRS": 'EPSG:4326',
		#"bbox": [-20037508, -20037508, 20037508, 20037508],
		#"bboxCRS": 3857,
		"tileSize": 256,
		"originLoc": "NW", #North West or South West
		"resFactor" : 2
	},


	"WGS84" : {
		"name" : 'WGS84',
		"description" : 'Global grid in wgs84 projection',
		"CRS": 'EPSG:4326',
		"bbox": [-180, -90, 180, 90], #w,s,e,n
		"bboxCRS": 'EPSG:4326',
		"tileSize": 256,
		"originLoc": "NW", #North West or South West
		"resFactor" : 2
	},

	#this one produce valid MBtiles files, because origin is bottom left
	"WM_SW" : {
		"name" : 'Web Mercator TMS',
		"description" : 'Global grid in web mercator projection, origin South West',
		"CRS": 'EPSG:3857',
		"bbox": [-180, -cutoff_lat, 180, cutoff_lat], #w,s,e,n
		"bboxCRS": 'EPSG:4326',
		#"bbox": [-20037508, -20037508, 20037508, 20037508],
		#"bboxCRS": 'EPSG:3857',
		"tileSize": 256,
		"originLoc": "SW", #North West or South West
		"resFactor" : 2
	},


	#####################
	#Custom grid example
	######################

	# >> France Lambert 93
	"LB93" : {
		"name" : 'Fr Lambert 93',
		"description" : 'Local grid in French Lambert 93 projection',
		"CRS": 'EPSG:2154',
		"bbox": [99200, 6049600, 1242500, 7110500], #w,s,e,n
		"bboxCRS": 'EPSG:2154',
		"tileSize": 256,
		"originLoc": "NW", #North West or South West
		"resFactor" : 2
	},

	# >> Another France Lambert 93 (submited list of resolution)
	"LB93_2" : {
		"name" : 'Fr Lambert 93 v2',
		"description" : 'Local grid in French Lambert 93 projection',
		"CRS": 'EPSG:2154',
		"bbox": [99200, 6049600, 1242500, 7110500], #w,s,e,n
		"bboxCRS": 'EPSG:2154',
		"tileSize": 256,
		"originLoc": "SW", #North West or South West
		"resolutions" : [4000, 2000, 1000, 500, 250, 100, 50, 25, 10, 5, 2, 1, 0.5, 0.25, 0.1] #15 levels
	},


	# >> France Lambert 93 used by CRAIG WMTS
	# WMTS resolution = ScaleDenominator * 0.00028
	# (0.28 mm = physical distance of a pixel (WMTS assumes a DPI 90.7)
	"LB93_CRAIG" : {
		"name" : 'Fr Lambert 93 CRAIG',
		"description" : 'Local grid in French Lambert 93 projection',
		"CRS": 'EPSG:2154',
		"bbox": [-357823.23, 6037001.46, 1313634.34, 7230727.37], #w,s,e,n
		"bboxCRS": 'EPSG:2154',
		"tileSize": 256,
		"originLoc": "NW",
		"initRes": 1354.666,
		"resFactor" : 2
	},

}


####################################

#        Sources definitions

####################################

#With TMS or WMTS, grid must match the one used by the service
#With WMS you can use any grid you want but the grid CRS must
#match one of those provided by the WMS service

#The grid associated to the source define the CRS
#A source can have multiple layers but have only one grid
#so to support multiple grid it's necessary to duplicate source definition

SOURCES = {


	###############
	# TMS examples
	###############


	"GOOGLE" : {
		"name" : 'Google',
		"description" : 'Google map',
		"service": 'TMS',
		"grid": 'WM',
		"quadTree": False,
		"layers" : {
			"SAT" : {"urlKey" : 's', "name" : 'Satellite', "description" : '', "format" : 'jpeg', "zmin" : 0, "zmax" : 22},
			"MAP" : {"urlKey" : 'm', "name" : 'Map', "description" : '', "format" : 'png', "zmin" : 0, "zmax" : 22}
		},
		"urlTemplate": "http://mt0.google.com/vt/lyrs={LAY}&x={X}&y={Y}&z={Z}",
		"referer": "https://www.google.com/maps"
	},


	"OSM" : {
		"name" : 'OSM',
		"description" : 'Open Street Map',
		"service": 'TMS',
		"grid": 'WM',
		"quadTree": False,
		"layers" : {
			"MAPNIK" : {"urlKey" : '', "name" : 'Mapnik', "description" : '', "format" : 'png', "zmin" : 0, "zmax" : 19}
		},
		"urlTemplate": "http://tile.openstreetmap.org/{Z}/{X}/{Y}.png",
		"referer": "http://www.openstreetmap.org"
	},


	"BING" : {
		"name" : 'Bing',
		"description" : 'Microsoft Bing Map',
		"service": 'TMS',
		"grid": 'WM',
		"quadTree": True,
		"layers" : {
			"SAT" : {"urlKey" : 'A', "name" : 'Satellite', "description" : '', "format" : 'jpeg', "zmin" : 0, "zmax" : 22},
			"MAP" : {"urlKey" : 'G', "name" : 'Map', "description" : '', "format" : 'png', "zmin" : 0, "zmax" : 22}
		},
		"urlTemplate": "http://ak.dynamic.t0.tiles.virtualearth.net/comp/ch/{QUADKEY}?it={LAY}",
		"referer": "http://www.bing.com/maps"
	},


	###############
	# WMS examples
	###############

	#with WMS you can set source grid as you want, the only condition is that the grid
	#crs must match one on crs provided by WMS


	"OSM_WMS" : {
		"name" : 'OSM WMS',
		"description" : 'Open Street Map WMS',
		"service": 'WMS',
		"grid": 'WM',
		"layers" : {
			"WRLD" : {"urlKey" : 'osm_auto:all', "name" : 'WMS', "description" : '', "format" : 'png', "style" : '', "zmin" : 0, "zmax" : 20}
		},
		"urlTemplate": {
			"BASE_URL" : 'http://129.206.228.72/cached/osm?',
			"SERVICE" : 'WMS',
			"VERSION" : '1.1.1',
			"REQUEST" : 'GetMap',
			"SRS" : '{CRS}', #EPSG:xxxx
			"LAYERS" : '{LAY}',
			"FORMAT" : 'image/{FORMAT}',
			"STYLES" : '{STYLE}',
			"BBOX" : '{BBOX}', #xmin,ymin,xmax,ymax, in "SRS" projection
			"WIDTH" : '{WIDTH}',
			"HEIGHT" : '{HEIGHT}',
			"TRANSPARENT" : "False"
			},
		"referer": "http://www.osm-wms.de/"
	},


}
"""
	#http://wms.craig.fr/ortho?SERVICE=WMS&REQUEST=GetCapabilities
	# example of valid location in Auvergne : lat 45.77 long 3.082
	"CRAIG_WMS" : {
		"name" : 'CRAIG WMS',
		"description" : "Centre Régional Auvergnat de l'Information Géographique",
		"service": 'WMS',
		"grid": 'LB93',
		"layers" : {
			"ORTHO" : {"urlKey" : 'auvergne', "name" : 'Auv25cm_2013', "description" : '', "format" : 'png', "style" : 'default', "zmin" : 0, "zmax" : 22}
		},
		"urlTemplate": {
			"BASE_URL" : 'http://wms.craig.fr/ortho?',
			"SERVICE" : 'WMS',
			"VERSION" : '1.3.0',
			"REQUEST" : 'GetMap',
			"CRS" : 'EPSG:{CRS}',
			"LAYERS" : '{LAY}',
			"FORMAT" : 'image/{FORMAT}',
			"STYLES" : '{STYLE}',
			"BBOX" : '{BBOX}', #xmin,ymin,xmax,ymax, in "SRS" projection
			"WIDTH" : '{WIDTH}',
			"HEIGHT" : '{HEIGHT}',
			"TRANSPARENT" : "False"
			},
		"referer": "http://www.craig.fr/"
	},


	###############
	# WMTS examples
	###############


	# http://tiles.craig.fr/ortho/service?service=WMTS&REQUEST=GetCapabilities
	# example of valid location in Auvergne : lat 45.77 long 3.082
	"CRAIG_WMTS93" : {
		"name" : 'CRAIG WMTS93',
		"description" : "Centre Régional Auvergnat de l'Information Géographique",
		"service": 'WMTS',
		"grid": 'LB93_CRAIG',
		"matrix" : 'lambert93',
		"layers" : {
			"ORTHO" : {"urlKey" : 'ortho_2013', "name" : 'Auv25cm_2013', "description" : '',
				"format" : 'jpeg', "style" : 'default', "zmin" : 0, "zmax" : 15}
		},
		"urlTemplate": {
			"BASE_URL" : 'http://tiles.craig.fr/ortho/service?',
			"SERVICE" : 'WMTS',
			"VERSION" : '1.0.0',
			"REQUEST" : 'GetTile',
			"LAYER" : '{LAY}',
			"STYLE" : '{STYLE}',
			"FORMAT" : 'image/{FORMAT}',
			"TILEMATRIXSET" : '{MATRIX}',
			"TILEMATRIX" : '{Z}',
			"TILEROW" : '{Y}',
			"TILECOL" : '{X}'
			},
		"referer": "http://www.craig.fr/"
	},


	"GEOPORTAIL" : {
		"name" : 'Geoportail',
		"description" : 'Geoportail.fr',
		"service": 'WMTS',
		"grid": 'WM',
		"matrix" : 'PM',
		"layers" : {
			"ORTHO" : {"urlKey" : 'ORTHOIMAGERY.ORTHOPHOTOS', "name" : 'Orthophotos', "description" : '',
				"format" : 'jpeg', "style" : 'normal', "zmin" : 0, "zmax" : 22},
			"SCAN" : {"urlKey" : 'GEOGRAPHICALGRIDSYSTEMS.MAPS', "name" : 'Scan', "description" : '',
				"format" : 'jpeg', "style" : 'normal', "zmin" : 0, "zmax" : 22},
			"CAD" : {"urlKey" : 'CADASTRALPARCELS.PARCELS', "name" : 'Cadastre', "description" : '',
				"format" : 'png', "style" : 'bdparcellaire', "zmin" : 0, "zmax" : 22}
		},
		"urlTemplate": {
			"BASE_URL" : 'http://gpp3-wxs.ign.fr/yvmoikafaddadzmxvh6sdmjb/wmts?',
			"SERVICE" : 'WMTS',
			"VERSION" : '1.0.0',
			"REQUEST" : 'GetTile',
			"LAYER" : '{LAY}',
			"STYLE" : '{STYLE}',
			"FORMAT" : 'image/{FORMAT}',
			"TILEMATRIXSET" : '{MATRIX}',
			"TILEMATRIX" : '{Z}',
			"TILEROW" : '{Y}',
			"TILECOL" : '{X}'
			},
		"referer": "http://www.geoportail.gouv.fr/accueil"
	},


}
"""

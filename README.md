Blender GIS
==========


ESRI Shapefile importer
--------------------

Import point, pointZ, polyline, polylineZ, polygon, polygonZ feature class. Actually cannot import multipoint, multipointZ, pointM, polylineM, polygonM and multipatch.

The script can uses data contain in dbf file to define Z elevation values or Z extrusion values. You need to know & manually enter the name of the field that contains the values.


Troubles:

This script depends on pyshp library that is in beta version, so sometimes it cannot process the shapefile. Typically, if you got "Unable to read shapefile", "Unable to extract geometry" or "Unable to read DBF table" error, these are pyShp issues. In this case:

1. Try to check if there is any update of [pyshp lib](http://code.google.com/p/pyshp/downloads/list).

2. If there is no update available or if update doesn't correct the problem, try to open and re-export the shapefile with any GIS software. You can also try to clean/repair geometry, delete unnecessary fields...

For polygons import, if you see faces which seem to be strangely filled try to remove duplicate vertex on the mesh (modify tolerance distance if necessary) 


ESRI Shapefile exporter
--------------------

Export a mesh to pointZ, polylineZ or polygonZ shapefile. If the mesh has georef data then this will be considered.

Note that Blender cannot handle attribute data include in dbase file linked to the shapefile. So if you want import a shapefile for edit it into Blender and then re-export it, you will lose attribute data.


Georeferenced raster importer
--------------------

Import common image format associated with a [world file](http://en.wikipedia.org/wiki/World_file) that describes the location, scale and rotation of the raster in a geographic coordinate system.

You can import as a plane mesh, as backgound image for orthographic view, as UV texture mapping on a mesh or as DEM for warp a mesh with the displace modifier.


Georeferenced render output
--------------------

This is a tool to create a new camera correctly setup for produce a map render. Georeferencing data (worldfile) are writing in text file accessible from the Blender text editor.


Georeferencing management
--------------------

Because Blender (and most of 3d software) cannot strongly handle objects that are far away scene origin, and because coordinates values are limited to 7 significant figures, it's necessary to create the mesh near to the scene origin. For avoid georeferencing lost, when you import a shapefile or a georaster, the script creates custom properties to the scene. Theses properties represent the shift values operate in X and Y axis. When you try to import a shapefile or a georaster, if the scene contains these custom properties, you have the possibility to use them to adjust the position of the new imported object.

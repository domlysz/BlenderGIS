[GDAL](http://gdal.org/) is a popular and powerful geospatial data processing library. GDAL is available as a set of commandline utilities (ready to use binaries files). The developer oriented library is available as a C/C++ API. Bindings in other languages, including Python, are also available.

Actually installing binary files is good enought to get the addon working as well. You can also use GDAL Python API but in this case you need to install the binding.

### Windows

**Binaries (executables)**

Core binary file can be downloaded from [gisinternals.com](http://www.gisinternals.com/sdk/). Scroll down to *release versions* table and click on the relevant link in the *Downloads* column (32 or 64 bit). From the new page download the GDAL core file (*gdal-[version]-[build]-core.msi*).

Using binary files needs to edit environmental variables like this:

![](https://raw.githubusercontent.com/wiki/domlysz/blenderGIS/images/varEnvGDAL.jpg)

**Python binding**

Installing Python binding from setup file requires that Python exists on your computer. So the first step is to install [Python](https://www.python.org/downloads/). Choose the version that match the one delivered with Blender.

Python binding is available from gisinternals.com, but this package isn't compiled accross Numpy. Without Numpy, the binding will not have all of its functionality and can not be used with the addon.

Fortunately other Python packages can be found [here](http://www.lfd.uci.edu/~gohlke/pythonlibs/#gdal). Note that this distribution also includes GDAL binary files.

GDAL Python binding installer creates a new folder named osgeo in *C:\Python33\Lib\site-packages*. If you already installed binary files you can delete \*.exe and \*.dll files from osgeo folder, they will not be used.

Finally, to get GDAL working in Blender, just copy osgeo folder in Python tree folder of Blender (*C:\Program Files\Blender Foundation\Blender\2.70\python\lib\site-packages*). 

Note that Numpy version uses to compile GDAL binding needs to match the version ship with Blender.

To test the install open Blender Python console and type:

`from osgeo import gdal`

`from osgeo import gdalnumeric`

These statements should not return error.


### Mac Osx

*Tested on Yosemite 10.10 and Blender 2.74*

**1) Install Xcode and Macports from this link :**
 https://www.macports.org/install.php

**2) Install gdal and gdal python bindings**
Open a terminal from spotlight or from Applications => Utilities => Terminal
Then type with administratives rights : 
> sudo port install gdal py34-gdal

**3) Copy osgeo folder from python bindings to blender**
> cp -rf /opt/local/Library/Frameworks/Python.framework/Versions/3.4/lib/python3.4/site-packages/osgeo /**where_you_put_blender_on_your_mac**/Blender/blender.app/Contents/Resources/2.74/scripts/modules/

Replace **where_you_put_blender_on_your_mac** with the path where you run or install Blender

Test it in Blender Python console like windows installation.

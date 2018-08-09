# -*- coding:utf-8 -*-

import os
import colorsys
from xml.dom.minidom import parse, parseString
from xml.etree import ElementTree as etree
from ..maths.interpo import scale, linearInterpo
from ..maths import akima


class Color(object):

	def __init__(self, values=None, space='RGBA'):
		#color data is stored as rgba vector (values range from 0 to 1)
		self.data = None
		#
		if type(values) == dict:
			#find correct space
			if all(key in 'RGBA' for key in values.keys()):
				space = 'RGBA'
			elif all(key in 'rgba' for key in values.keys()):
				space = 'rgba'
			elif all(key in 'HSVA' for key in values.keys()):
				space = 'HSVA'
			elif all(key in 'hsva' for key in values.keys()):
				space = 'hsva'
			else:
				space = None
		#
		if values is not None and space is not None:
			if type(values) not in (tuple, list, dict) or space not in ('RGB', 'RGBA', 'rgb', 'rgba', 'HSV', 'HSVA', 'hsv', 'hsva'):
				raise ValueError("Wrong parameters")
			#
			if space in ['RGB', 'RGBA']:
				if type(values) == dict:
					self.from_RGB(**values)
				elif type(values) in [tuple, list]:
					self.from_RGB(*values)
			elif space in ['rgb', 'rgba']:
				if type(values) == dict:
					self.from_rgb(**values)
				elif type(values) in [tuple, list]:
					self.from_rgb(*values)
			#
			if space in ['HSV', 'HSVA']:
				if type(values) == dict:
					self.from_HSV(**values)
				elif type(values) in [tuple, list]:
					self.from_HSV(*values)
			elif space in ['hsv', 'hsva']:
				if type(values) == dict:
					self.from_hsv(**values)
				elif type(values) in [tuple, list]:
					self.from_hsv(*values)

	def __str__(self):
		if self.data is not None:
			strRGB = 'RGB ' + str(self.RGB)
			strHSV = 'HSV ' + str(self.HSV)
			strAlpha = 'Alpha ' + str(self.alpha)
			return strRGB + ' - ' + strHSV + ' - ' + strAlpha
		else:
			return "No color defined"

	def __eq__(self, other):
		return self.data == other.data

	#All properties will be computed from rgba vector data
	@property
	def alpha(self):
		if self.data is not None:
			return self.rgba[-1]#range from 0 to 1
		else:
			return None
	@property
	def hex(self):
		if self.data is not None:
			return "#"+"".join(["0{0:x}".format(v) if v < 16 else "{0:x}".format(v) for v in self.RGB])
		else:
			return None
	## props with alpha
	@property
	def RGBA(self): #values range from 0 to 255
		if self.data is not None:
			return tuple([int(v*255) for v in self.rgba])
		else:
			return None
	@property
	def rgba(self): #values range from 0 to 1
		if self.data is not None:
			return tuple(self.data)
		else:
			return None
	@property
	def HSVA(self): #H ranges from 0° to 360°. Other values range from 0 to 100%
		if self.data is not None:
			h, s, v, a = self.hsva
			return tuple([h*360, s*100, v*100, a*100])
		else:
			return None
	@property
	def hsva(self): #values range from 0 to 1
		if self.data is not None:
			return self.hsv + tuple([self.alpha])
		else:
			return None
	## props without alpha
	@property
	def RGB(self):
		if self.data is not None:
			return tuple(self.RGBA[:-1])
		else:
			return None
	@property
	def rgb(self):
		if self.data is not None:
			return tuple(self.rgba[:-1])
		else:
			return None
	@property
	def HSV(self):
		if self.data is not None:
			h, s, v = self.hsv
			return tuple([h*360, s*100, v*100])
		else:
			return None
	@property
	def hsv(self):
		if self.data is not None:
			return colorsys.rgb_to_hsv(*self.rgb)
		else:
			return None

	#another way to get color value (dictionary output possible)
	def getColor(self, space='RGB', asDict=False):
		if space == 'RGB':
			if asDict:
				return {key:self.RGB[i] for i, key in enumerate(space)}
			else:
				return self.RGB
		elif space == 'RGBA':
			if asDict:
				return {key:self.RGBA[i] for i, key in enumerate(space)}
			else:
				return self.RGBA
		elif space == 'rgba':
			if asDict:
				return {key:self.rgba[i] for i, key in enumerate(space)}
			else:
				return self.rgba
		elif space == 'rgb':
			if asDict:
				return {key:self.rgb[i] for i, key in enumerate(space)}
			else:
				return self.rgb
		if space == 'HSV':
			if asDict:
				return {key:self.HSV[i] for i, key in enumerate(space)}
			else:
				return self.HSV
		elif space == 'HSVA':
			if asDict:
				return {key:self.HSVA[i] for i, key in enumerate(space)}
			else:
				return self.HSVA
		elif space == 'hsva':
			if asDict:
				return {key:self.hsva[i] for i, key in enumerate(space)}
			else:
				return self.hsva
		elif space == 'hsv':
			if asDict:
				return {key:self.hsv[i] for i, key in enumerate(space)}
			else:
				return self.hsv

	#You can create Color object in many ways:
	# Color.from_rgb(0, 1, 1, 1) - passing arguments
	# Color.from_rgb(r=0, g=1, b=1, a=1) - passing keywords arguments
	# Color.from_rgb(*[0, 1, 1, 1]) - unpacking a list or a tuple (or a generic iterable)
	# Color.from_rgb(**{'r':0, 'g':1, 'b':1, 'a':1}) - unpacking a dictionary

	def from_RGB(self, R, G, B, A=255):
		if all(0<=v<=255 for v in (R, G, B, A)):
			self.data = [ v/255 for v in (R, G, B, A) ]
		else:
			raise ValueError("RGB values must range from 0 to 255")

	def from_rgb(self, r, g, b, a=1):
		if all(0<=v<=1 for v in (r, g, b, a)):
			self.data = [r, g, b, a]
		else:
			raise ValueError("rgb values must range from 0 to 1")

	def from_HSV(self, H, S, V, A=1):
		if 0<=H<=360 and 0<=S<=100 and 0<=V<=100:
			self.data = list(colorsys.hsv_to_rgb(H/360, S/100, V/100))
			self.data.append(A)
		else:
			raise ValueError("Hue must range from 0 to 360°. S and V must range from 0 to 100%")

	def from_hsv(self, h, s, v, a=1):
		if all(0<=v<=1 for v in (h, s, v, a)):
			self.data = list(colorsys.hsv_to_rgb(h, s, v))
			self.data.append(a)
		else:
			raise ValueError("hsv values must range from 0 to 1")

	def from_hex(self, hex):
		R,G,B = [int(hex[i:i+2], 16) for i in range(1,6,2)]
		self.data = [ v/255 for v in (R, G, B, 255) ]



class Stop():
	def __init__(self, position, color):
		self.position = position
		self.color = color

	def __lt__(self, other):
		return self.position < other.position


class Gradient():

	def __init__(self, svg=False, permissive=False):
		self.stops = []
		#permissive rules allows duplicate position and same color for two followings stops
		#this option is useful when define discrete ramp
		self.permissive = permissive
		if svg:
			self.__readSVG(svg)

	def __str__(self):
		return str(self.asList())

	def __readSVG(self, svg):
		try:
			domData = parse(svg)
		except Exception as e:
			print("Cannot parse svg file : " + str(e))
			return False
		linearGradients = domData.getElementsByTagName('linearGradient')
		nbGradients = len(linearGradients)
		if nbGradients == 0:
			print("No gradient in this SVG")
			return False
		elif nbGradients > 1:
			print('Only the first gradient will be imported')
		linearGradient = linearGradients[0]
		stops = linearGradient.getElementsByTagName('stop')
		if len(stops) <= 1:
			print('No enough stops')
			return False
		#begin import
		for stop in stops:
			positionStr = stop.getAttribute('offset') # "33.5%"
			position = float(positionStr[:-1])/100
			colorStr = stop.getAttribute('stop-color') # "rgb(51, 188, 207)"
			alpha = float(stop.getAttribute('stop-opacity')) #value between 0-1
			if ', ' in colorStr:
				rgba = colorStr[4:-1].split(', ')
			else:
				rgba = colorStr[4:-1].split(',')
			rgba = [int(c)/255 for c in rgba]
			rgba.append(alpha)
			color = Color()
			color.from_rgb(*rgba)
			self.addStop(position, color, reorder=False)
		#finish
		self.sortStops()
		domData.unlink()
		return True


	@property
	def positions(self):
		return [stop.position for stop in self.stops]
	@property
	def colors(self):
		return [stop.color for stop in self.stops]


	def asList(self, space='RGBA'):
		return [(round(stop.position,2), stop.color.getColor(space)) for stop in self.stops]

	def asDict(self, space='RGBA'):
		return {round(stop.position,2):stop.color.getColor(space, asDict=True) for stop in self.stops}


	def addStop(self, position, color, reorder=True):
		if not self.permissive: #permissive option allows discrete color ramp definition
			#avoid same color in two following stops
			if len(self.colors) >= 1:
				if color == self.colors[-1]:
					return False
			#avoid duplicate position
			if position in self.positions:
				return False
		#check if position is between 0-1
		if not 0<=position<=1:
			return False
		#check color
		if type(color) != Color:
			return False
		stop = Stop(position, color)
		self.stops.append(stop)
		if reorder:
			self.sortStops()
		return True

	def addStops(self, positions, colors):
		if len(positions) != len(colors):
			return False
		for i, pos in enumerate(positions):
			self.addStop(pos, colors[i], reorder=False)
		self.sortStops()
		return True

	def sortStops(self):
		self.stops.sort() #sort(key=attrgetter('position'))

	def rmColor(self, color):
		if type(color) != Color:
			return False
		try:
			idx = self.colors.index(color)
		except ValueError as e :
			print('Cannot remove color from this gradient : {}'.format(e))
			return False
		else:
			self.stops.pop(idx)
			return True

	def rmPosition(self, pos):
		try:
			idx = self.positions.index(pos)
		except ValueError as e:
			print('Cannot remove position from this gradient : {}'.format(e))
			return False
		else:
			self.stops.pop(idx)
			return True

	def rescale(self, toMin, toMax):
		fromMin = min(self.positions)
		fromMax = max(self.positions)
		for stop in self.stops:
			stop.position = scale(stop.position, fromMin, fromMax, toMin, toMax)

	def evaluate(self, pos, colorSpace = 'RGB', method='LINEAR'):
		#check interpo method
		if method not in ['DISCRETE', 'NEAREST', 'LINEAR', 'SPLINE']:
			method = 'LINEAR'
		#check color space
		if colorSpace in ['RGB', 'RGBA', 'rgb', 'rgba']:
			colorSpace = 'rgba' #we will work with normalized values
		elif colorSpace in ['HSV', 'HSVA', 'hsv', 'hsva']:
			colorSpace = 'hsva'
		else:
			colorSpace = 'rgba' #default
		#check position
		self.sortStops()
		positions = self.positions
		#if pos already exist return it's color
		if pos in positions:
			idx = positions.index(pos)
			return self.stops[idx].color
		#if pos is first or last stop, return corresponding color (no extrapolation)
		if pos < positions[0]:
			return self.stops[0].color
		elif pos > positions[-1]:
			return self.stops[-1].color
		#find previous and next stops
		for i, p in enumerate(positions):
			if p<pos<positions[i+1]:
				prevStop = self.stops[i]
				nextStop = self.stops[i+1]
				break

		if method == 'DISCRETE':
			return prevStop.color

		elif method == 'NEAREST':
			if (pos - prevStop.position) < (nextStop.position - pos):
				return prevStop.color
			else:
				return nextStop.color

		elif method == 'LINEAR':
			x1, x2 = prevStop.position, nextStop.position
			interpolateValues = []
			for i in range(4): #4 channels (rgba or hsva)
				y1, y2 = prevStop.color.getColor(colorSpace)[i], nextStop.color.getColor(colorSpace)[i]
				dy = y2-y1
				if colorSpace == 'hsva' and i == 0 and abs(dy) > 0.5: # hue values with delta > 180°
					# Hue is cyclic
					# > interpolation must be done through the shortest path (clockwise or counterclockwise)
					# > to interpolate CCW, add 180° to all hue values, then compute modulo 360° on interpolate result
					y1, y2 = [hue+0.5 if hue<0 else hue-0.5 for hue in (y1, y2)]
					y = linearInterpo(x1, x2, y1, y2, pos) % 1
				else:
					y = linearInterpo(x1, x2, y1, y2, pos)
				interpolateValues.append(round(y,2))
			return Color(interpolateValues, colorSpace)

		elif method == 'SPLINE':
			xData = self.positions
			if len(xData) < 3: #spline interpo needs at least 3 pts, otherwise compute a linear interpolation
				return self.evaluate(pos, colorSpace, method='LINEAR')
			interpolateValues = []
			for i in range(4): #4 channels (rgba or hsva)
				yData = [color.getColor(colorSpace)[i] for color in self.colors]
				dy = (nextStop.color.getColor(colorSpace)[i] - prevStop.color.getColor(colorSpace)[i])
				if colorSpace == 'hsva' and i == 0 and abs(dy) > 0.5: # hue values with delta > 180°
					# Hue is cyclic
					# > interpolation must be done through the shortest path (clockwise or counterclockwise)
					# > to interpolate CCW, add 180° to all hue values, then compute modulo 360° on interpolate result
					yData = [hue+0.5 if hue<0 else hue-0.5 for hue in yData]
					y = akima.interpolate(xData, yData, [pos])[0] % 1
				else:
					y = akima.interpolate(xData, yData, [pos])[0]
				#Constrain result between 0-1
				y = 1 if y>1 else 0 if y<0 else y
				#append
				interpolateValues.append(round(y,2))
			return Color(interpolateValues, colorSpace)


	def getRangeColor(self, n, interpoSpace='RGB', interpoMethod='LINEAR'):
		'''return a new gradient'''
		ramp = Gradient(permissive=True)#permissive needed because discrete interpo can return same color for 2 or more following stops
		offset = 1/(n-1)
		position = 0
		for i in range(n):
			color = self.evaluate(position, interpoSpace, interpoMethod)
			ramp.addStop(position, color, reorder=False)
			position += offset
		return ramp


	def exportSVG(self, svgPath, discrete=False):
		name = os.path.splitext(os.path.basename(svgPath))[0]
		name = name.replace(" ", "_")
		# create an SVG XML element (see the SVG specification for attribute details)
		svg = etree.Element('svg', width='300', height='45', version='1.1', xmlns='http://www.w3.org/2000/svg', viewBox='0 0 300 45')
		gradient = etree.Element('linearGradient', id=name, gradientUnits='objectBoundingBox', spreadMethod='pad', x1='0%', x2='100%', y1='0%', y2='0%')

		#make discrete svg ramp
		if discrete:
			stops = []
			for i, stop in enumerate(self.stops):
				if i>0:
					stops.append( Stop(stop.position, self.stops[i-1].color) )
				stops.append( Stop(stop.position, stop.color) )
		else:
			stops = self.stops

		for stop in stops:
			p = stop.position * 100
			p = str(round(p,2)) + '%'
			r,g,b = stop.color.RGB
			c = "rgb(%d,%d,%d)" % (r, g, b)
			a = str(stop.color.alpha)
			etree.SubElement(gradient, 'stop', {'offset':p, 'stop-color':c, 'stop-opacity':a}) #use dict because hyphens in tags
		svg.append(gradient)
		rect = etree.Element('rect', {'fill':"url(#%s)" % (name), 'x':'4', 'y':'4', 'width':'292', 'height':'37', 'stroke':'black', 'stroke_width':'1'})
		svg.append(rect)
		# get string
		xmlstr = etree.tostring(svg, encoding='utf8', method='xml').decode('utf-8')
		# etree doesn't have pretty xml function, so use minidom tu get a pretty xml ...
		reparsed = parseString(xmlstr)
		xmlstr = reparsed.toprettyxml()
		# write to file
		f = open(svgPath,"w")
		f.write(xmlstr)
		f.close()

		return

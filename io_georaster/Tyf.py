# -*- encoding:utf-8 -*-

# Tyf library (here packed into one file)
# https://github.com/Moustikitos/tyf
# Tyf package provides pythonic way to view Exif data from TIFF and JPEG files
# BSD licence


__copyright__ = "Copyright © 2012-2015, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html"
__author__    = "THOORENS Bruno"
__tiff__      = (6, 0)
__geotiff__   = (1, 8, 1)


import os, sys
import datetime
import math, fractions
import io
import struct
import operator
import collections

unpack = lambda fmt, fileobj: struct.unpack(fmt, fileobj.read(struct.calcsize(fmt)))
pack = lambda fmt, fileobj, value: fileobj.write(struct.pack(fmt, *value))

TYPES = {
	1:  ("B",  "UCHAR or USHORT"),
	2:  ("c",  "ASCII"),
	3:  ("H",  "UBYTE"),
	4:  ("L",  "ULONG"),
	5:  ("LL", "URATIONAL"),
	6:  ("b",  "CHAR or SHORT"),
	7:  ("c",  "UNDEFINED"),
	8:  ("h",  "BYTE"),
	9:  ("l",  "LONG"),
	10: ("ll", "RATIONAL"),
	11: ("f",  "FLOAT"),
	12: ("d",  "DOUBLE"),
}

# assure compatibility python 2 & 3
if sys.version_info[0] >= 3:
	from io import BytesIO as StringIO
	TYPES[2] = ("s", "ASCII")
	TYPES[7] = ("s", "UDEFINED")
	import functools
	reduce = functools.reduce
	long = int
	import urllib.request as urllib
else:
	from StringIO import StringIO
	import urllib
	reduce = __builtins__["reduce"]


def _read_IFD(obj, fileobj, offset, byteorder="<"):
	# fileobj seek must be on the start offset
	fileobj.seek(offset)
	# get number of entry
	nb_entry, = unpack(byteorder+"H", fileobj)

	# for each entry 
	for i in range(nb_entry):
		# read tag, type and count values
		tag, typ, count = unpack(byteorder+"HHL", fileobj)
		# extract data
		data = fileobj.read(struct.calcsize("=L"))
		if not isinstance(data, bytes):
			data = data.encode()
		_typ = TYPES[typ][0]

		# create a tifftag
		tt = TiffTag(tag, typ, name=obj.tagname)
		# initialize what we already know
		# tt.type = typ
		tt.count = count
		# to know if ifd entry value is an offset
		tt._determine_if_offset()

		# if value is offset
		if tt.value_is_offset:
			# read offset value
			value, = struct.unpack(byteorder+"L", data)
			fmt = byteorder + _typ*count
			bckp = fileobj.tell()
			# go to offset in the file
			fileobj.seek(value)
			# if ascii type, convert to bytes
			if typ == 2: tt.value = b"".join(e for e in unpack(fmt, fileobj))
			# else if undefined type, read data
			elif typ == 7: tt.value = fileobj.read(count)
			# else unpack data
			else: tt.value = unpack(fmt, fileobj)
			# go back to ifd entry
			fileobj.seek(bckp)

		# if value is in the ifd entry
		else:
			if typ in [2, 7]:
				tt.value = data[:count]
			else:
				fmt = byteorder + _typ*count
				tt.value = struct.unpack(fmt, data[:count*struct.calcsize(_typ)])

		obj.addtag(tt)

def from_buffer(obj, fileobj, offset, byteorder="<", custom_sub_ifd={}):
	# read data from offset
	_read_IFD(obj, fileobj, offset, byteorder)
	# get next ifd offset
	next_ifd, = unpack(byteorder+"L", fileobj)

	# finding by default those SubIFD
	sub_ifd = {34665:"Exif tag", 34853:"GPS tag", 40965:"Interoperability tag"}
	# adding other SubIFD if asked
	sub_ifd.update(custom_sub_ifd)
	## read registered SubIFD
	for key,value in sub_ifd.items():
		if key in obj:
			obj.sub_ifd[key] = Ifd(tagname=value)
			_read_IFD(obj.sub_ifd[key], fileobj, obj[key], byteorder)

	return next_ifd

# for speed reason : load raster only if asked or if needed
def _load_raster(obj, fileobj):
	# striped raster data
	if 273 in obj:
		for offset,bytecount in zip(obj.get(273).value, obj.get(279).value):
			fileobj.seek(offset)
			obj.stripes += (fileobj.read(bytecount), )
	# free raster data
	elif 288 in obj:
		for offset,bytecount in zip(obj.get(288).value, obj.get(289).value):
			fileobj.seek(offset)
			obj.free += (fileobj.read(bytecount), )
	# tiled raster data
	elif 324 in obj:
		for offset,bytecount in zip(obj.get(324).value, obj.get(325).value):
			fileobj.seek(offset)
			obj.tiles += (fileobj.read(bytecount), )
	# get interExchange (thumbnail data for JPEG/EXIF data)
	if 513 in obj:
		fileobj.seek(obj[513])
		obj.jpegIF = fileobj.read(obj[514])

def _write_IFD(obj, fileobj, offset, byteorder="<"):
	# go where obj have to be written
	fileobj.seek(offset)
	# sort data to be writen
	tags = sorted(list(dict.values(obj)), key=lambda e:e.tag)
	# write number of entries
	pack(byteorder+"H", fileobj, (len(tags),))

	first_entry_offset = fileobj.tell()
	# write all ifd entries
	for t in tags:
		# write tag, type & count
		pack(byteorder+"HHL", fileobj, (t.tag, t.type, t.count))

		# if value is not an offset
		if not t.value_is_offset:
			value = t._fill()
			n = len(value)
			if sys.version_info[0] >= 3 and t.type in [2, 7]:
				fmt = str(n)+TYPES[t.type][0]
				value = (value,)
			else:
				fmt = n*TYPES[t.type][0]
			pack(byteorder+fmt, fileobj, value)
		else:
			pack(byteorder+"L", fileobj, (0,))

	next_ifd_offset = fileobj.tell()
	pack(byteorder+"L", fileobj, (0,))

	# prepare jumps
	data_offset = fileobj.tell()
	step1 = struct.calcsize("HHLL")
	step2 = struct.calcsize("HHL")

	# comme back to first ifd entry
	fileobj.seek(first_entry_offset)
	for t in tags:
		# for each tag witch value needs offset
		if t.value_is_offset:
			# go to offset value location (jump over tag, type, count)
			fileobj.seek(step2, 1)
			# write offset where value is about to be stored
			pack(byteorder+"L", fileobj, (data_offset,))
			# remember where i am in ifd entries
			bckp = fileobj.tell()
			# go to offset where value is about to be stored
			fileobj.seek(data_offset)
			# prepare value according to python version
			if sys.version_info[0] >= 3 and t.type in [2, 7]:
				fmt = str(t.count)+TYPES[t.type][0]
				value = (t.value,)
			else:
				fmt = t.count*TYPES[t.type][0]
				value = t.value
			# write value
			pack(byteorder+fmt, fileobj, value)
			# remmember where to put next value
			data_offset = fileobj.tell()
			# go to where I was in ifd entries
			fileobj.seek(bckp)
		else:
			fileobj.seek(step1, 1)

	return next_ifd_offset

def to_buffer(obj, fileobj, offset, byteorder="<"):
	obj._check()

	size = obj.size
	raw_offset = offset + size["ifd"] + size["data"]
	# add SubIFD sizes...
	for tag, p_ifd in sorted(obj.sub_ifd.items(), key=lambda e:e[0]):
		obj.set(tag, 4, raw_offset)
		size = p_ifd.size
		raw_offset = raw_offset + size["ifd"] + size["data"]

	# knowing where raw image have to be writen, update [Strip/Free/Tile]Offsets
	if 273 in obj:
		_279 = obj.get(279).value
		stripoffsets = (raw_offset,)
		for bytecount in _279[:-1]:
			stripoffsets += (stripoffsets[-1]+bytecount, )
		obj.set(273, 4, stripoffsets)
		next_ifd = stripoffsets[-1] + _279[-1]
	elif 288 in obj:
		_289 = obj.get(289).value
		freeoffsets = (raw_offset,)
		for bytecount in _289[:-1]:
			freeoffsets += (freeoffsets[-1]+bytecount, )
		obj.set(288, 4, freeoffsets)
		next_ifd = freeoffsets[-1] + _289[-1]
	elif 324 in obj:
		_325 = obj.get(325).value
		tileoffsets = (raw_offset,)
		for bytecount in _325[:-1]:
			tileoffsets += (tileoffsets[-1]+bytecount, )
		obj.set(324, 4, tileoffsets)
		next_ifd = tileoffsets[-1] + _325[-1]
	elif 513 in obj:
		interexchangeoffset = raw_offset
		obj.set(513, 4, raw_offset)
		next_ifd = interexchangeoffset + obj[514]
	else:
		next_ifd = raw_offset

	# write IFD
	next_ifd_offset = _write_IFD(obj, fileobj, offset, byteorder)
	# write SubIFD 
	for tag, p_ifd in sorted(obj.sub_ifd.items(), key=lambda e:e[0]):
		_write_IFD(p_ifd, fileobj, obj[tag], byteorder)

	# write raster data
	if len(obj.stripes):
		for offset,data in zip(stripoffsets, obj.stripes):
			fileobj.seek(offset)
			fileobj.write(data)
	elif len(obj.free):
		for offset,data in zip(freeoffsets, obj.stripes):
			fileobj.seek(offset)
			fileobj.write(data)
	elif len(obj.tiles):
		for offset,data in zip(tileoffsets, obj.tiles):
			fileobj.seek(offset)
			fileobj.write(data)
	elif obj.jpegIF != b"":
		fileobj.seek(interexchangeoffset)
		fileobj.write(obj.jpegIF)

	fileobj.seek(next_ifd_offset)
	return next_ifd


def _fileobj(f, mode):
	if hasattr(f, "close"):
		fileobj = f
		_close = False
	else:
		fileobj = io.open(f, mode)
		_close = True

	return fileobj, _close


class TiffFile(list):

	gkd = property(lambda obj: [Gkd(ifd) for ifd in obj], None, None, "list of geotiff directory")
	has_raster = property(lambda obj: reduce(operator.__or__, [ifd.has_raster for ifd in obj]), None, None, "")
	raster_loaded = property(lambda obj: reduce(operator.__and__, [ifd.raster_loaded for ifd in obj]), None, None, "")

	def __init__(self, fileobj):
		"""Initialize a TiffFile object from buffer fileobj, fileobj have to be in 'wb' mode"""

		# determine byteorder
		first, = unpack(">H", fileobj)
		byteorder = "<" if first == 0x4949 else ">"

		magic_number, = unpack(byteorder+"H", fileobj)
		if magic_number != 0x2A: # 42
			fileobj.close()
			raise IOError("Bad magic number. Not a valid TIFF file")
		next_ifd, = unpack(byteorder+"L", fileobj)

		ifds = []
		while next_ifd != 0:
			i = Ifd(sub_ifd={
				34665:[exfT,"Exif tag"],
				34853:[gpsT,"GPS tag"]
			})
			next_ifd = from_buffer(i, fileobj, next_ifd, byteorder)
			ifds.append(i)

		if hasattr(fileobj, "name"):
			self._filename = fileobj.name
		else:
			for i in ifds:
				_load_raster(i, fileobj)

		list.__init__(self, ifds)

	def __getitem__(self, item):
		if isinstance(item, tuple): return list.__getitem__(self, item[0])[item[-1]]
		else: return list.__getitem__(self, item)

	def __add__(self, value):
		self.load_raster()
		if isinstance(value, TiffFile):
			value.load_raster()
			for i in value: self.append(i)
		elif isinstance(value, Ifd):
			self.append(value)
		return self
	__iadd__ = __add__

	def load_raster(self, idx=None):
		if hasattr(self, "_filename"):
			in_ = io.open(self._filename, "rb")
			for ifd in iter(self) if idx == None else [self[idx]]:
				if not ifd.raster_loaded: _load_raster(ifd, in_)
			in_.close()

	def save(self, f, byteorder="<", idx=None):
		self.load_raster()
		fileobj, _close = _fileobj(f, "wb")

		pack(byteorder+"HH", fileobj, (0x4949 if byteorder == "<" else 0x4d4d, 0x2A,))
		next_ifd = 8

		for i in iter(self) if idx == None else [self[idx]]:
			pack(byteorder+"L", fileobj, (next_ifd,))
			next_ifd = to_buffer(i, fileobj, next_ifd, byteorder)

		if _close: fileobj.close()



def open(f):
	fileobj, _close = _fileobj(f, "rb")
		
	first, = unpack(">H", fileobj)
	fileobj.seek(0)

	if first in [0x4d4d, 0x4949]:
		obj = TiffFile(fileobj)

	if _close: fileobj.close()
	
	try:
		return obj
	except:
		raise Exception("file is not a valid TIFF image")




##################
#CODEC
##################

class decoders():
    ###############
    # type decoders

    _1 = _3 = _4 = _6 = _8 = _9 = _11 = _12 = lambda value: value[0] if len(value) == 1 else value

    _2 = lambda value: value[:-1]

    def _5(value):
    	result = tuple((float(n)/(1 if d==0 else d)) for n,d in zip(value[0::2], value[1::2]))
    	return result[0] if len(result) == 1 else result

    _7 = lambda value: value

    _10 = _5

    #######################
    # Tag-specific decoders

    # XPTitle XPComment XBAuthor
    _0x9c9b = _0x9c9c = _0x9c9d = lambda value : "".join(chr(e) for e in value[0::2]).encode()[:-1]
    # UserComment GPSProcessingMethod
    _0x9286 = _0x1b = lambda value: value[8:]
    #GPSLatitudeRef
    _0x1 = lambda value: 1 if value in [b"N\x00", b"N"] else -1
    #GPSLatitude
    def _0x2(value):
    	degrees, minutes, seconds = _5(value)
    	return (seconds/60 + minutes)/60 + degrees
    #GPSLatitudeRef
    _0x3 = lambda value: 1 if value in [b"E\x00", b"E"] else -1
    #GPSLongitude
    _0x4 = _0x2
    # GPSTimeStamp
    _0x7 = lambda value: datetime.time(*[int(e) for e in _5(value)])
    # GPSDateStamp
    _0x1d = lambda value: datetime.datetime.strptime(_2(value).decode(), "%Y:%m:%d")
    # DateTime DateTimeOriginal DateTimeDigitized
    _0x132 = _0x9003 = _0x9004 = lambda value: datetime.datetime.strptime(_2(value).decode(), "%Y:%m:%d %H:%M:%S")


class encoders():
    ###############
    # type encoders

    _m_short = 0
    _M_short = 2**8
    def _1(value):
    	value = int(value)
    	return (_m_short, ) if value < _m_short else \
    	       (_M_short, ) if value > _M_short else \
    	       (value, )

    def _2(value):
    	if not isinstance(value, bytes):
    		value = value.encode()
    	value += b"\x00" if value[-1] != b"\x00" else ""
    	return value

    _m_byte = 0
    _M_byte = 2**16
    def _3(value):
    	value = int(value)
    	return (_m_byte, ) if value < _m_byte else \
    	       (_M_byte, ) if value > _M_byte else \
    	       (value, )

    _m_long = 0
    _M_long = 2**32
    def _4(value):
    	value = int(value)
    	return (_m_long, ) if value < _m_long else \
    	       (_M_long, ) if value > _M_long else \
    	       (value, )

    def _5(value):
    	if not isinstance(value, tuple): value = (value, )
    	return reduce(tuple.__add__, [(f.numerator, f.denominator) for f in [fractions.Fraction(str(v)).limit_denominator(10000000) for v in value]])

    _m_s_short = -_M_short/2
    _M_s_short = _M_short/2-1
    def _6(value):
    	value = int(value)
    	return (_m_s_short, ) if value < _m_s_short else \
    	       (_M_s_short, ) if value > _M_s_short else \
    	       (value, )

    def _7(value):
    	if not isinstance(value, bytes):
    		value = value.encode()
    	return value

    _m_s_byte = -_M_byte/2
    _M_s_byte = _M_byte/2-1
    def _8(value):
    	value = int(value)
    	return (_m_s_byte, ) if value < _m_s_byte else \
    	       (_M_s_byte, ) if value > _M_s_byte else \
    	       (value, )

    _m_s_long = -_M_long/2
    _M_s_long = _M_long/2-1
    def _9(value):
    	value = int(value)
    	return (_m_s_long, ) if value < _m_s_long else \
    	       (_M_s_long, ) if value > _M_s_long else \
    	       (value, )

    _10 = _5

    def _11(value):
    	return (float(value), )

    _12 = _11

    #######################
    # Tag-specific encoders

    # XPTitle XPComment XBAuthor
    _0x9c9b = _0x9c9c = _0x9c9d = lambda value : reduce(tuple.__add__, [(ord(e), 0) for e in value])
    # UserComment GPSProcessingMethod
    _0x9286 = _0x1b = lambda value: b"ASCII\x00\x00\x00" + (value.encode() if not isinstance(value, bytes) else value)
    # GPSLatitudeRef
    _0x1 = lambda value: b"N\x00" if bool(value >= 0) == True else b"S\x00"
    # GPSLatitude
    def _0x2(value):
    	value = abs(value)

    	degrees = math.floor(value)
    	minutes = (value - degrees) * 60
    	seconds = (minutes - math.floor(minutes)) * 60
    	minutes = math.floor(minutes)

    	if seconds >= (60.-0.0001):
    		seconds = 0.
    		minutes += 1

    	if minutes >= (60.-0.0001):
    		minutes = 0.
    		degrees += 1

    	return _5((degrees, minutes, seconds))
    #GPSLongitudeRef
    _0x3 = lambda value: b"E\x00" if bool(value >= 0) == True else b"W\x00"
    #GPSLongitude
    _0x4 = _0x2
    # GPSTimeStamp
    _0x7 = lambda value: _5(tuple(float(e) for e in [value.hour, value.minute, value.second]))
    # GPSDateStamp
    _0x1d = lambda value: _2(value.strftime("%Y:%m:%d"))
    # DateTime DateTimeOriginal DateTimeDigitized
    _0x132 = _0x9003 = _0x9004 = lambda value: _2(value.strftime("%Y:%m:%d %H:%M:%S"))


#################
#IFD
#################


class TiffTag(object):

	# IFD entries values
	tag = 0x0
	type = 0
	count = 0
	value = None

	# end user side values
	key = "Undefined"
	name = "Undefined tag"
	comment = "Nothing about this tag"
	meaning = None

	def __init__(self, tag, type=None, value=None, name="Tiff tag"):
		self.key, _typ, default, self.comment = get(tag)
		self.tag = tag
		self.name = name

		self.type = _typ[-1] if type == None else type
		if value != None: self._encode(value)
		elif default != None: self.value = (default,) if not hasattr(default, "len") else default

	def __setattr__(self, attr, value):
		if attr == "type":
			try: object.__setattr__(self, "_encoder", getattr(encoders, "_%s"%hex(self.tag)))
			except AttributeError: object.__setattr__(self, "_encoder", getattr(encoders, "_%s"%value))
			try: object.__setattr__(self, "_decoder", getattr(decoders, "_%s"%hex(self.tag)))
			except AttributeError: object.__setattr__(self, "_decoder", getattr(decoders, "_%s"%value))
		elif attr == "value":
			restricted = getattr(values, self.key, None)
			if restricted != None:
				v = value[0] if isinstance(value, tuple) else value
				self.meaning = restricted.get(v, "no description found [%r]" % (v,))
			self.count = len(value) // (1 if self.type not in [5,10] else 2)
			self._determine_if_offset()
		object.__setattr__(self, attr, value)

	def __repr__(self):
		return "<%s 0x%x: %s = %r>" % (self.name, self.tag, self.key, self.value) + ("" if not self.meaning else ' := %r'%self.meaning)

	def _encode(self, value):
		self.value = self._encoder(value)

	def _decode(self):
		return self._decoder(self.value)

	def _determine_if_offset(self):
		if self.count == 1 and self.type in [1, 2, 3, 4, 6, 7, 8, 9]: setattr(self, "value_is_offset", False)
		elif self.count <= 2 and self.type in [3, 8]: setattr(self, "value_is_offset", False)
		elif self.count <= 4 and self.type in [1, 2, 6, 7]: setattr(self, "value_is_offset", False)
		else: setattr(self, "value_is_offset", True)

	def _fill(self):
		s = struct.calcsize(TYPES[self.type][0])
		voidspace = (struct.calcsize("L") - self.count*s)//s
		if self.type in [2, 7]: return self.value + b"\x00"*voidspace
		elif self.type in [1, 3, 6, 8]: return self.value + ((0,)*voidspace)
		return self.value

	def calcsize(self):
		return struct.calcsize(TYPES[self.type][0] * (self.count*(2 if self.type in [5,10] else 1))) if self.value_is_offset else 0


class Ifd(dict):
	tagname = "Tiff Tag"

	exif_ifd = property(lambda obj: obj.sub_ifd.get(34665, {}), None, None, "shortcut to EXIF sub ifd")
	gps_ifd = property(lambda obj: obj.sub_ifd.get(34853, {}), None, None, "shortcut to GPS sub ifd")
	has_raster = property(lambda obj: 273 in obj or 288 in obj or 324 in obj or 513 in obj, None, None, "return true if it contains raster data")
	raster_loaded = property(lambda obj: not(obj.has_raster) or bool(len(obj.stripes+obj.tiles+obj.free)+len(obj.jpegIF)), None, None, "")
	size = property(
		lambda obj: {
			"ifd": struct.calcsize("H" + (len(obj)*"HHLL") + "L"),
			"data": reduce(int.__add__, [t.calcsize() for t in dict.values(obj)])
		}, None, None, "return ifd-packed size and data-packed size")
		
	def __init__(self, sub_ifd={}, **kwargs):
		self._sub_ifd = sub_ifd
		setattr(self, "tagname", kwargs.pop("tagname", "Tiff tag"))
		dict.__init__(self)

		self.sub_ifd = {}
		self.stripes = ()
		self.tiles = ()
		self.free = ()
		self.jpegIF = b""

	def __setitem__(self, tag, value):
		for t,(ts,tname) in self._sub_ifd.items():
			tag = _2tag(tag, family=ts)
			if tag in ts:
				if not t in self.sub_ifd:
					self.sub_ifd[t] = Ifd(sub_ifd={}, tagname=tname)
				self.sub_ifd[t].addtag(TiffTag(tag, value=value))
				return
		else:
			tag = _2tag(tag)
			dict.__setitem__(self, tag, TiffTag(tag, value=value, name=self.tagname))

	def __getitem__(self, tag):
		for i in self.sub_ifd.values():
			try: return i[tag]
			except KeyError: pass
		return dict.__getitem__(self, _2tag(tag))._decode()

	def _check(self):
		for key in self.sub_ifd:
			if key not in self:
				self.addtag(TiffTag(key, 4, 0, name=self.tagname))

	def set(self, tag, typ, value):
		for t,(ts,tname) in self._sub_ifd.items():
			if tag in ts:
				if not t in self.sub_ifd:
					self.sub_ifd[t] = Ifd(sub_ifd={}, tagname=tname)
				self.sub_ifd[t].set(tag, typ, value)
				return
		tifftag = TiffTag(tag=tag, type=typ, name=self.tagname)
		tifftag.value = (value,) if not hasattr(value, "__len__") else value
		tifftag.name = self.tagname
		dict.__setitem__(self, tag, tifftag)

	def get(self, tag):
		for i in self.sub_ifd.values():
			if tag in i: return i.get(tag)
		return dict.get(self, _2tag(tag))

	def addtag(self, tifftag):
		if isinstance(tifftag, TiffTag):
			tifftag.name = self.tagname
			dict.__setitem__(self, tifftag.tag, tifftag)

	def tags(self):
		for v in sorted(dict.values(self), key=lambda e:e.tag):
			yield v
		for i in self.sub_ifd.values():
			for v in sorted(dict.values(i), key=lambda e:e.tag):
				yield v

	def load_location(self, zoom=15, size="256x256", mcolor="0xff00ff", format="png", scale=1):
		if set([1,2,3,4]) <= set(self.gps_ifd.keys()):
			latitude = self.gps_ifd[1] * self.gps_ifd[2]
			longitude = self.gps_ifd[3] * self.gps_ifd[4]
			try:
				opener = urllib.urlopen("https://maps.googleapis.com/maps/api/staticmap?center=%s,%s&zoom=%s&size=%s&markers=color:%s%%7C%s,%s&format=%s&scale=%s" % (
					latitude, longitude,
					zoom, size, mcolor,
					latitude, longitude,
					format, scale
				))
			except:
				return StringIO()
			else:
				return StringIO(opener.read())
				print("googleapis connexion error")
		else:
			return StringIO()

	def dump_location(self, tilename, zoom=15, size="256x256", mcolor="0xff00ff", format="png", scale=1):
		if set([1,2,3,4]) <= set(self.gps_ifd.keys()):
			latitude = self.gps_ifd[1] * self.gps_ifd[2]
			longitude = self.gps_ifd[3] * self.gps_ifd[4]
			try:
				urllib.urlretrieve("https://maps.googleapis.com/maps/api/staticmap?center=%s,%s&zoom=%s&size=%s&markers=color:%s%%7C%s,%s&format=%s&scale=%s" % (
						latitude, longitude,
						zoom, size, mcolor,
						latitude, longitude,
						format, scale
					),
					os.path.splitext(tilename)[0] + "."+format
				)
			except:
				print("googleapis connexion error")


######################
#TAGS
######################

# Baseline TIFF tags
bTT = {
	254:   ("NewSubfileType", [1], 0, "A general indication of the kind of data contained in this subfile"),
	255:   ("SubfileType", [1], None, "Deprecated, use NewSubfiletype instead"),
	256:   ("ImageWidth", [1,4], None, "Number of columns in the image, ie, the number of pixels per row"),
	257:   ("ImageLength", [1,4], None, "Number of rows of pixels in the image"),
	258:   ("BitsPerSample", [1], 1, "Array size = SamplesPerPixel, number of bits per component"),
	259:   ("Compression", [1], 1, "Compression scheme used on the image data"),
	262:   ("PhotometricInterpretation", [1], None, "The color space of the image data"),
	263:   ("Thresholding", [1], 1, "For black and white TIFF files that represent shades of gray, the technique used to convert from gray to black and white pixels"),
	264:   ("CellWidth", [1], None, "The width of the dithering or halftoning matrix used to create a dithered or halftoned bilevel file"),
	265:   ("CellLength", [1], None, "The length of the dithering or halftoning matrix used to create a dithered or halftoned bilevel file"),
	266:   ("FillOrder", [1], 1, "The logical order of bits within a byt"),
	270:   ("ImageDescription", [2], None, "A string that describes the subject of the image"),
	271:   ("Make", [2], None, "The scanner manufacturer"),
	272:   ("Model", [2], None, "The scanner model name or number"),
	273:   ("StripOffsets", [1,4], None, "For each strip, the byte offset of that strip"),
	274:   ("Orientation", [1], 1, "The orientation of the image with respect to the rows and columns"),
	277:   ("SamplesPerPixel", [1], 1, "The number of components per pixel"),
	278:   ("RowsPerStrip", [1,4], 2**32-1, "The number of rows per strip"),
	279:   ("StripByteCounts", [1,4], None, "For each strip, the number of bytes in the strip after compression"),
	280:   ("MinSampleValue", [1], 0, "The minimum component value used"),
	281:   ("MaxSampleValue", [1], 1, "The maximum component value used"),
	282:   ("XResolution", [5], None, "The number of pixels per ResolutionUnit in the ImageWidth direction"),
	283:   ("YResolution", [5], None, "The number of pixels per ResolutionUnit in the ImageLength direction"),
	284:   ("PlanarConfiguration", [1], 1, "How the components of each pixel are stored"),
	288:   ("FreeOffsets", [4], None, "For each string of contiguous unused bytes in a TIFF file, the byte offset of the string"),
	289:   ("FreeByteCounts", [4], None, "For each string of contiguous unused bytes in a TIFF file, the number of bytes in the string"),
	290:   ("GrayResponseUnit", [1], 2, "The precision of the information contained in the GrayResponseCurve"),
	291:   ("GrayResponseCurve", [1], 2, "Array size = 2**SamplesPerPixel"),
	296:   ("ResolutionUnit", [4], 2, "The unit of measurement for XResolution and YResolution"),
	305:   ("Software", [2], None, "Name and version number of the software package(s) used to create the image"),
	306:   ("DateTime", [2], None, "Date and time of image creation, aray size = 20, 'YYYY:MM:DD HH:MM:SS\0'"),
	315:   ("Artist", [2], None, "Person who created the image"),
	316:   ("HostComputer", [2], None, "The computer and/or operating system in use at the time of image creation"),
	320:   ("ColorMap", [1], None, "A color map for palette color images"),
	338:   ("ExtraSamples", [1], 1, "Description of extra components"),
	33432: ("Copyright", [2], None, "Copyright notice"),
}

# Extension TIFF tags
xTT = {
	269:   ("DocumentName", [2], None, "The name of the document from which this image was scanned"),
	285:   ("PageName", [2], None, "The name of the page from which this image was scanned"),
	286:   ("XPosition", [5], None, "X position of the image"),
	287:   ("YPosition", [5], None, "Y position of the image"),
	292:   ("T4Options", [4], 0, "Options for Group 3 Fax compression"),
	293:   ("T6Options", [4], 0, "Options for Group 6 Fax compression"),
	297:   ("PageNumber", [1], None, "The page number of the page from which this image was scanned"),
	301:   ("TransferFunction", [1], 1*(1<<1), "Describes a transfer function for the image in tabular style"),
	317:   ("Predictor", [3], 1, "A mathematical operator that is applied to the image data before an encoding scheme is applied"),
	318:   ("WhitePoint", [5], None, "The chromaticity of the white point of the image"),
	319:   ("PrimaryChromaticies", [5], None, "The chromaticities of the primaries of the image"),
	321:   ("HalftoneHints", [1], None, "Conveys to the halftone function the range of gray levels within a colorimetrically-specified image that should retain tonal detail"),
	322:   ("TileWidth", [1,4], None, "The tile width in pixels This is the number of columns in each tile"),
	323:   ("TileLength", [1,4], None, "The tile length (height) in pixels This is the number of rows in each tile"),
	324:   ("TileOffsets", [4], None, "For each tile, the byte offset of that tile, as compressed and stored on disk"),
	325:   ("TileByteCounts", [1,4], None, "For each tile, the number of (compressed) bytes in that tile"),
	326:   ("BadFaxLinea", [1,4], None, "Used in the TIFF-F standard, denotes the number of 'bad' scan lines encountered by the facsimile device"),
	327:   ("CleanFaxData", [1], None, "Used in the TIFF-F standard, indicates if 'bad' lines encountered during reception are stored in the data, or if 'bad' lines have been replaced by the receiver"),
	328:   ("ConsecutiveBadFaxLines", [1,4], None, "Used in the TIFF-F standard, denotes the maximum number of consecutive 'bad' scanlines received"),
	328:   ("SubIFDs", [2,4], None, "Offset to child IFDs"), # ???
	332:   ("InkSet", [1], None, "The set of inks used in a separated (PhotometricInterpretation=5) image"),
	333:   ("InkNames", [2], None, "The name of each ink used in a separated image"),
	334:   ("NumberOfInks", [1], 4, "The number of inks"),
	336:   ("DotRange", [1,3], (0,1), "The component values that correspond to a 0%% dot and 100%% dot"),
	337:   ("TargetPrinter", [2], None, "A description of the printing environment for which this separation is intended"),
	339:   ("SampleFormat", [1], 1, "Specifies how to interpret each data sample in a pixel"),
	340:   ("SMinSampleValue", [3,7,8,12], None, "Specifies the minimum sample value"),
	341:   ("SMaxSampleValue", [3,7,8,12], None, "Specifies the maximum sample value"),
	342:   ("TransferRange", [1], None, "Expands the range of the TransferFunction"),
	343:   ("ClipPath", [3], None, "Mirrors the essentials of PostScript's path creation functionality"),
	344:   ("XClipPathUnits", [4], None, "The number of units that span the width of the image, in terms of integer ClipPath coordinates"),
	345:   ("YClipPathUnits", [4], None, "The number of units that span the height of the image, in terms of integer ClipPath coordinates"),
	346:   ("Indexed", [1], 0, "Aims to broaden the support for indexed images to include support for any color space"),
	347:   ("JPEGTables", [7], None, "JPEG quantization and/or Huffman tables"),
	351:   ("OPIProxy", [1], 0, "OPI-related"),
	400:   ("GlobalParametersIFD", [2,4], None, "Used in the TIFF-FX standard to point to an IFD containing tags that are globally applicable to the complete TIFF file"),
	401:   ("ProfileType", [4], None, "Used in the TIFF-FX standard, denotes the type of data stored in this file or IFD"),
	402:   ("FaxProfile", [3], None, "Used in the TIFF-FX standard, denotes the 'profile' that applies to this file"),
	403:   ("CodingMethods", [4], None, "Used in the TIFF-FX standard, indicates which coding methods are used in the file"),
	404:   ("VersionYear", [3], None, "Used in the TIFF-FX standard, denotes the year of the standard specified by the FaxProfile field"),
	405:   ("ModeNumber", [3], None, "Used in the TIFF-FX standard, denotes the mode of the standard specified by the FaxProfile field"),
	433:   ("Decode", [10],None, "Used in the TIFF-F and TIFF-FX standards, holds information about the ITULAB (PhotometricInterpretation = 10) encoding"),
	434:   ("DefaultImageColor", [1], None, "Defined in the Mixed Raster Content part of RFC 2301, is the default color needed in areas where no image is available"),
	512:   ("JPEGProc", [1], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	513:   ("JPEGInterchangeFormat", [4], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	514:   ("JPEGInterchangeFormatLength", [4], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	515:   ("JPEGRestartInterval", [1], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	517:   ("JPEGLosslessPredictors", [1], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	518:   ("JPEGPointTransforms", [1], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	519:   ("JPEGQTables", [4], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	520:   ("JPEGDCTables", [4], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specificationl"),
	521:   ("JPEGACTables", [4], None, "Old-style JPEG compression field TechNote2 invalidates this part of the specification"),
	529:   ("YCbCrCoefficients", [5], (299,1000,587,1000,114,1000), "The transformation from RGB to YCbCr image data"),
	530:   ("YCbCrSubSampling", [1], (2,2), "Specifies the subsampling factors used for the chrominance components of a YCbCr image"),
	531:   ("YCbCrPositioning", [1], 1, "Specifies the positioning of subsampled chrominance components relative to luminance samples"),
	532:   ("ReferenceBlackWhite", [5], (0,1,1,1,0,1,1,1,0,1,1,1), "Specifies a pair of headroom and footroom image data values (codes) for each pixel component"),
	559:   ("StripRowCounts", [4], None, "Defined in the Mixed Raster Content part of RFC 2301, used to replace RowsPerStrip for IFDs with variable-sized strips"),
	700:   ("XMP", [3], None, "XML packet containing XMP metadata"),
	32781: ("ImageID", [2], None, "OPI-related"),
	34732: ("ImageLayer", [1,4], None, "Defined in the Mixed Raster Content part of RFC 2301, used to denote the particular function of this Image in the mixed raster scheme"),
}

# Private TIFF tags
pTT = {
	32932:  ("Wang Annotation", [3], None, "Annotation data, as used in 'Imaging for Windows'"),
	33445:  ("MD FileTag", [4], None, "Specifies the pixel data format encoding in the Molecular Dynamics GEL file format"),
	33446:  ("MD ScalePixel", [5], None, "Specifies a scale factor in the Molecular Dynamics GEL file format"),
	33447:  ("MD ColorTable", [1], None, "Used to specify the conversion from 16bit to 8bit in the Molecular Dynamics GEL file format"),
	33448:  ("MD LabName", [2], None, "Name of the lab that scanned this file, as used in the Molecular Dynamics GEL file format"),
	33449:  ("MD SampleInfo", [2], None, "Information about the sample, as used in the Molecular Dynamics GEL file format"),
	33450:  ("MD PrepDate", [2], None, "Date the sample was prepared, as used in the Molecular Dynamics GEL file format"),
	33451:  ("MD PrepTime", [2], None, "Time the sample was prepared, as used in the Molecular Dynamics GEL file format"),
	33452:  ("MD FileUnits", [2], None, "Units for data in this file, as used in the Molecular Dynamics GEL file format"),
	33550:  ("ModelPixelScaleTag", [12], None, "Used in interchangeable GeoTIFF files"),
	33723:  ("IPTC", [3,7], None, "IPTC (International Press Telecommunications Council) metadata"),
	33918:  ("INGR Packet Data Tag", [3], None, "Intergraph Application specific storage"),
	33919:  ("INGR Flag Registers", [4], None, "Intergraph Application specific flags"),
	33920:  ("IrasB Transformation Matrix", [12], None, "Originally part of Intergraph's GeoTIFF tags, but likely understood by IrasB only"),
	33922:  ("ModelTiepointTag", [12], None, "Originally part of Intergraph's GeoTIFF tags, but now used in interchangeable GeoTIFF files"),
	34264:  ("ModelTransformationTag", [12], None, "Used in interchangeable GeoTIFF files"),
	34377:  ("Photoshop", [1], None, "Collection of Photoshop 'Image Resource Blocks'"),
	34665:  ("Exif IFD", [4], None, "A pointer to the Exif IFD"),
	34675:  ("ICC Profile", [7], None, "ICC profile data"),
	34735:  ("GeoKeyDirectoryTag", [3], None, "Used in interchangeable GeoTIFF files"),
	34736:  ("GeoDoubleParamsTag", [12], None, "Used in interchangeable GeoTIFF files"),
	34737:  ("GeoAsciiParamsTag", [2], None, "Used in interchangeable GeoTIFF files"),
	34853:  ("GPS IFD", [4], None, "A pointer to the Exif-related GPS Info IFD"),
	34908:  ("HylaFAX FaxRecvParams", [4], None, "Used by HylaFAX"),
	34909:  ("HylaFAX FaxSubAddress", [2], None, "Used by HylaFAX"),
	34910:  ("HylaFAX FaxRecvTime", [4], None, "Used by HylaFAX"),
	37724:  ("ImageSourceData", [7], None, "Used by Adobe Photoshop"),
	40965:  ("Interoperability IFD", [4], None, "A pointer to the Exif-related Interoperability IFD"),
	42112:  ("GDAL_METADATA", [2], None, "Used by the GDAL library, holds an XML list of name=value 'metadata' values about the image as a whole, and about specific samples"),
	42113:  ("GDAL_NODATA", [2], None, "Used by the GDAL library, contains an ASCII encoded nodata or background pixel value"),
	50215:  ("Oce Scanjob Description", [2], None, "Used in the Oce scanning process"),
	50216:  ("Oce Application Selector", [2], None, "Used in the Oce scanning process"),
	50217:  ("Oce Identification Number", [2], None, "Used in the Oce scanning process"),
	50218:  ("Oce ImageLogic Characteristics", [2], None, "Used in the Oce scanning process"),
	50706:  ("DNGVersion", [3], None, "Used in IFD 0 of DNG files"),
	50707:  ("DNGBackwardVersion", [3], None, "Used in IFD 0 of DNG files"),
	50708:  ("UniqueCameraModel", [2], None, "Used in IFD 0 of DNG files"),
	50709:  ("LocalizedCameraModel", [2,3], None, "Used in IFD 0 of DNG files"),
	50710:  ("CFAPlaneColor", [3], None, "Used in Raw IFD of DNG files"),
	50711:  ("CFALayout", [1], None, "Used in Raw IFD of DNG files"),
	50712:  ("LinearizationTable", [1], None, "Used in Raw IFD of DNG files"),
	50713:  ("BlackLevelRepeatDim", [1], None, "Used in Raw IFD of DNG files"),
	50714:  ("BlackLevel", [1,4,5], None, "Used in Raw IFD of DNG files"),
	50715:  ("BlackLevelDeltaH", [10], None, "Used in Raw IFD of DNG files"),
	50716:  ("BlackLevelDeltaV", [10], None, "Used in Raw IFD of DNG files"),
	50717:  ("WhiteLevel", [1,4], None, "Used in Raw IFD of DNG files"),
	50718:  ("DefaultScale", [5], None, "Used in Raw IFD of DNG files"),
	50719:  ("DefaultCropOrigin", [1,4,5], None, "Used in Raw IFD of DNG files"),
	50720:  ("DefaultCropSize", [1,4,5], None, "Used in Raw IFD of DNG files"),
	50721:  ("ColorMatrix1", [10], None, "Used in IFD 0 of DNG files"),
	50722:  ("ColorMatrix2", [10], None, "Used in IFD 0 of DNG files"),
	50723:  ("CameraCalibration1", [10], None, "Used in IFD 0 of DNG files"),
	50724:  ("CameraCalibration2", [10], None, "Used in IFD 0 of DNG files"),
	50725:  ("ReductionMatrix1", [10], None, "Used in IFD 0 of DNG files"),
	50726:  ("ReductionMatrix2", [10], None, "Used in IFD 0 of DNG files"),
	50727:  ("AnalogBalance", [5], None, "Used in IFD 0 of DNG files"),
	50728:  ("AsShotNeutral", [1,5], None, "Used in IFD 0 of DNG files"),
	50729:  ("AsShotWhiteXY", [5], None, "Used in IFD 0 of DNG files"),
	50730:  ("BaselineExposure", [10], None, "Used in IFD 0 of DNG files"),
	50731:  ("BaselineNoise", [10], None, "Used in IFD 0 of DNG files"),
	50732:  ("BaselineSharpness", [10], None, "Used in IFD 0 of DNG files"),
	50733:  ("BayerGreenSplit", [4], None, "Used in Raw IFD of DNG files"),
	50734:  ("LinearResponseLimit", [5], None, "Used in IFD 0 of DNG files"),
	50735:  ("CameraSerialNumber", [2], None, "Used in IFD 0 of DNG files"),
	50736:  ("LensInfo", [5], None, "Used in IFD 0 of DNG files"),
	50737:  ("ChromaBlurRadius", [5], None, "Used in Raw IFD of DNG files"),
	50738:  ("AntiAliasStrength", [5], None, "Used in Raw IFD of DNG files"),
	50740:  ("DNGPrivateData", [3], None, "Used in IFD 0 of DNG files"),
	50741:  ("MakerNoteSafety", [1], None, "Used in IFD 0 of DNG files"),
	50778:  ("CalibrationIlluminant1", [1], None, "Used in IFD 0 of DNG files"),
	50779:  ("CalibrationIlluminant2", [1], None, "Used in IFD 0 of DNG files"),
	50780:  ("BestQualityScale", [5], None, "Used in Raw IFD of DNG files"),
	50784:  ("Alias Layer Metadata", [2], None, "Alias Sketchbook Pro layer usage description"),
	# XP tags
	0x9c9b: ("XPTitle", [4], None, ""),
	0x9c9c: ("XPComment", [4], None, ""),
	0x9c9d: ("XPAuthor", [4], None, ""),
	0x9c9e: ("XPKeywords", [4], None, ""),
	0x9c9f: ("XPSubject", [4], None, ""),
	0xea1c: ("Padding", [7], None, ""),
	0xea1d: ("OffsetSchema", [9], None, ""),
}

exfT = {
	33434: ("ExposureTime", [5], None, "Exposure time, given in seconds"),
	33437: ("FNumber", [5], None, "The F number"),
	34850: ("ExposureProgram", [1], 0, "The class of the program used by the camera to set exposure when the picture is taken"),
	34852: ("SpectralSensitivity", [2], None, "Indicates the spectral sensitivity of each channel of the camera used"),
	34855: ("ISOSpeedRatings", [1], None, "Indicates the ISO Speed and ISO Latitude of the camera or input device as specified in ISO 12232"),
	34856: ("OECF", [7], None, "Indicates the Opto-Electric Conversion Function (OECF) specified in ISO 14524"),
	36864: ("ExifVersion", [7], b"0220", "The version of the supported Exif standard"),
	36867: ("DateTimeOriginal", [2], None, "The date and time when the original image data was generated"),
	36868: ("DateTimeDigitized", [2], None, "The date and time when the image was stored as digital data"),
	37121: ("ComponentsConfiguration", [7], None, "Specific to compressed data; specifies the channels and complements PhotometricInterpretation"),
	37122: ("CompressedBitsPerPixel", [5], None, "Specific to compressed data; states the compressed bits per pixel"),
	37377: ("ShutterSpeedValue", [11], None, "Shutter speed"),
	37378: ("ApertureValue", [5], None, "The lens aperture"),
	37379: ("BrightnessValue", [5], None, "The value of brightness"),
	37380: ("ExposureBiasValue", [11], None, "The exposure bias"),
	37381: ("MaxApertureValue", [5], None, "The smallest F number of the lens"),
	37382: ("SubjectDistance", [5], None, "The distance to the subject, given in meters"),
	37383: ("MeteringMode", [1], 0, "The metering mode"),
	37384: ("LightSource", [1], 0, "The kind of light source"),
	37385: ("Flash", [1], None, "Indicates the status of flash when the image was shot"),
	37386: ("FocalLength", [5], None, "The actual focal length of the lens, in mm"),
	37396: ("SubjectArea", [1], None, "Indicates the location and area of the main subject in the overall scene"),
	37500: ("MakerNote", [7], None, "Manufacturer specific information"),
	37510: ("UserComment", [7], None, "Keywords or comments on the image; complements ImageDescription"),
	37520: ("SubsecTime", [2], None, "A tag used to record fractions of seconds for the DateTime tag"),
	37521: ("SubsecTimeOriginal", [2], None, "A tag used to record fractions of seconds for the DateTimeOriginal tag"),
	37522: ("SubsecTimeDigitized", [2], None, "A tag used to record fractions of seconds for the DateTimeDigitized tag"),
	40960: ("FlashpixVersion", [7], b"0100", "The Flashpix format version supported by a FPXR file"),
	40961: ("ColorSpace", [1], None, "The color space information tag is always recorded as the color space specifier"),
	40962: ("PixelXDimension", [1,4], None, "Specific to compressed data; the valid width of the meaningful image"),
	40963: ("PixelYDimension", [1,4], None, "Specific to compressed data; the valid height of the meaningful image"),
	40964: ("RelatedSoundFile", [2], None, "Used to record the name of an audio file related to the image data"),
	41483: ("FlashEnergy", [5], None, "Indicates the strobe energy at the time the image is captured, as measured in Beam Candle Power Seconds"),
	41484: ("SpatialFrequencyResponse", [7], None, "Records the camera or input device spatial frequency table and SFR values in the direction of image width, image height, and diagonal direction, as specified in ISO 12233"),
	41486: ("FocalPlaneXResolution", [5], None, "Indicates the number of pixels in the image width (X) direction per FocalPlaneResolutionUnit on the camera focal plane"),
	41487: ("FocalPlaneYResolution", [5], None, "Indicates the number of pixels in the image height (Y) direction per FocalPlaneResolutionUnit on the camera focal plane"),
	41488: ("FocalPlaneResolutionUnit", [1], 2, "Indicates the unit for measuring FocalPlaneXResolution and FocalPlaneYResolution"),
	41492: ("SubjectLocation", [2], None, "Indicates the location of the main subject in the scene"),
	41493: ("ExposureIndex", [5], None, "Indicates the exposure index selected on the camera or input device at the time the image is captured"),
	41495: ("SensingMethod", [1], None, "Indicates the image sensor type on the camera or input device"),
	41728: ("FileSource", [7], b"3", "Indicates the image source"),
	41729: ("SceneType", [7], b"1", "Indicates the type of scene"),
	41730: ("CFAPattern", [7], None, "Indicates the color filter array (CFA) geometric pattern of the image sensor when a one-chip color area sensor is used"),
	41985: ("CustomRendered", [1], 0, "Indicates the use of special processing on image data, such as rendering geared to output"),
	41986: ("ExposureMode", [1], None, "Indicates the exposure mode set when the image was shot"),
	41987: ("WhiteBalance", [1], None, "Indicates the white balance mode set when the image was shot"),
	41988: ("DigitalZoomRatio", [5], None, "Indicates the digital zoom ratio when the image was shot"),
	41989: ("FocalLengthIn35mmFilm", [1], None, "Indicates the equivalent focal length assuming a 35mm film camera, in mm"),
	41990: ("SceneCaptureType", [1], 0, "Indicates the type of scene that was shot"),
	41991: ("GainControl", [1], None, "Indicates the degree of overall image gain adjustment"),
	41992: ("Contrast", [1], 0, "Indicates the direction of contrast processing applied by the camera when the image was shot"),
	41993: ("Saturation", [1], 0, "Indicates the direction of saturation processing applied by the camera when the image was shot"),
	41994: ("Sharpness", [1], 0, "Indicates the direction of sharpness processing applied by the camera when the image was shot"),
	41995: ("DeviceSettingDescription", [7], None, "This tag indicates information on the picture-taking conditions of a particular camera model"),
	41996: ("SubjectDistanceRange", [1], None, "Indicates the distance to the subject"),
	42016: ("ImageUniqueID", [2], None, "Indicates an identifier assigned uniquely to each image"),
}

gpsT = {
	0:  ("GPSVersionID", [3], (2,2,0,0), "Indicates the version of GPSInfoIFD"),
	1:  ("GPSLatitudeRef", [2], None, "Indicates whether the latitude is north or south latitude"),
	2:  ("GPSLatitude", [5], None, "Indicates the latitude"),
	3:  ("GPSLongitudeRef", [2], None, "Indicates whether the longitude is east or west longitude"),
	4:  ("GPSLongitude", [5], None, "Indicates the longitude"),
	5:  ("GPSAltitudeRef", [3], None, "Indicates the altitude used as the reference altitude"),
	6:  ("GPSAltitude", [5], None, "Indicates the altitude based on the reference in GPSAltitudeRef"),
	7:  ("GPSTimeStamp", [5], None, "Indicates the time as UTC (Coordinated Universal Time)"),
	8:  ("GPSSatellites", [2], None, "Indicates the GPS satellites used for measurements"),
	9:  ("GPSStatus", [2], None, "Indicates the status of the GPS receiver when the image is recorded"),
	10: ("GPSMeasureMode", [2], None, "Indicates the GPS measurement mode"),
	11: ("GPSDOP", [5], None, "Indicates the GPS DOP (data degree of precision)"),
	12: ("GPSSpeedRef", [2], b'K\x00', "Indicates the unit used to express the GPS receiver speed of movement"),
	13: ("GPSSpeed", [5], None, "Indicates the speed of GPS receiver movem5nt"),
	14: ("GPSTrackRef", [2], b'T\x00', "Indicates the reference for giving the direction of GPS receiver movement"),
	15: ("GPSTrack", [5], None, "Indicates the direction of GPS receiver movement"),
	16: ("GPSImgDirectionRef", [2], b'T\x00', "Indicates the reference for giving the direction of the image when it is captured"),
	17: ("GPSImgDirection", [5], None, "Indicates the direction of the image when it was captured"),
	18: ("GPSMapDatum", [2], None, "Indicates the geodetic survey data used by the GPS receiver"),
	19: ("GPSDestLatitudeRef", [2], None, "Indicates whether the latitude of the destination point is north or south latitude"),
	20: ("GPSDestLatitude", [5], None, "Indicates the latitude of the destination point"),
	21: ("GPSDestLongitudeRef", [2], None, "Indicates whether the longitude of the destination point is east or west longitude"),
	22: ("GPSDestLongitude", [5], None, "Indicates the longitude of the destination point"),
	23: ("GPSDestBearingRef", [2], None, "Indicates the reference used for giving the bearing to the destination point"),
	24: ("GPSDestBearing", [5], None, "Indicates the bearing to the destination point"),
	25: ("GPSDestDistanceRef", [2], None, "Indicates the unit used to express the distance to the destination point"),
	26: ("GPSDestDistance", [5], None, "Indicates the distance to the destination point"),
	27: ("GPSProcessingMethod", [7], None, "A character string recording the name of the method used for location finding"),
	28: ("GPSAreaInformation", [7], None, "A character string recording the name of the GPS area"),
	29: ("GPSDateStamp", [2], None, "A character string recording date and time information relative to UTC (Coordinated Universal Time)"),
	30: ("GPSDifferential", [1], None, "Indicates whether differential correction is applied to the GPS receiver"),
}

_TAG_FAMILIES = [bTT, xTT, pTT, exfT, gpsT]
_TAG_FAMILIES_2TAG = [dict((v[0], t) for t,v in dic.items()) for dic in _TAG_FAMILIES]
_TAG_FAMILIES_2KEY = [dict((v, k) for k,v in dic.items()) for dic in _TAG_FAMILIES_2TAG]

def get(tag):
	idx = 0
	for dic in _TAG_FAMILIES:
		if isinstance(tag, (bytes, str)):
			tag = _TAG_FAMILIES_2TAG[idx][tag]
		if tag in dic:
			return dic[tag]
	return ("Unknown", [4], None, "Undefined tag 0x%x"%tag)

def _2tag(tag, family=None):
	if family != None:
		idx = _TAG_FAMILIES.index(family)
		if isinstance(tag, (bytes, str)):
			if tag in _TAG_FAMILIES_2TAG[idx]:
				return _TAG_FAMILIES_2TAG[idx][tag]
			return tag
		else:
			return tag
	elif isinstance(tag, (bytes, str)):
		for dic in _TAG_FAMILIES_2TAG:
			if tag in dic:
				return dic[tag]
		return tag
	else:
		return tag




#######################
#GEOKEYS
#######################


GeoKeyModel = {
	33550: collections.namedtuple("ModelPixelScale", "ScaleX, ScaleY, ScaleZ"),
	33922: collections.namedtuple("ModelTiepoint", "I,J,K,X,Y,Z"),
	34264: collections.namedtuple("ModelTransformation", "a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p")
}

def Transform(obj, x=0., y=0., z1=0.,z2=1.):
	return (
		obj[0] *  x + obj[1] *  y + obj[2] *  z1 + obj[3] *  z2,
		obj[4] *  x + obj[5] *  y + obj[6] *  z1 + obj[7] *  z2,
		obj[8] *  x + obj[9] *  y + obj[10] * z1 + obj[11] * z2,
		obj[12] * x + obj[13] * y + obj[14] * z1 + obj[15] * z2
	)

_TAGS = {
	# GeoTIFF Configuration GeoKeys
	1024: ("GTModelTypeGeoKey", [3], 0, None),
	1025: ("GTRasterTypeGeoKey", [3], 1, None),
	1026: ("GTCitationGeoKey", [2], None, None),             # ASCII text

	# Geographic CS Parameter GeoKeys
	2048: ("GeographicTypeGeoKey", [3], 4326, None),         # epsg datum code [4001 - 4999]
	2049: ("GeogCitationGeoKey", [2], None, None),           # ASCII text
	2050: ("GeogGeodeticDatumGeoKey", [3], None, None),      # use 2048 !
	2051: ("GeogPrimeMeridianGeoKey", [3], 8901, None),      # epsg prime meridian code [8001 - 8999]
	2052: ("GeogLinearUnitsGeoKey", [3], 9001, None),        # epsg linear unit code [9000 - 9099]
	2053: ("GeogLinearUnitSizeGeoKey", [12], None, None),    # custom unit in meters
	2054: ("GeogAngularUnitsGeoKey", [3], 9101, None),
	2055: ("GeogAngularUnitsSizeGeoKey", [12], None, None),  # custom unit in radians
	2056: ("GeogEllipsoidGeoKey", [3], None, None),          # epsg ellipsoid code [7000 - 7999]
	2057: ("GeogSemiMajorAxisGeoKey", [12], None, None),
	2058: ("GeogSemiMinorAxisGeoKey", [12], None, None),
	2059: ("GeogInvFlatteningGeoKey", [12], None, None),
	2060: ("GeogAzimuthUnitsGeoKey",[3], None, None),
	2061: ("GeogPrimeMeridianLongGeoKey", [12], None, None), # custom prime meridian value in GeogAngularUnits
	
	# Projected CS Parameter GeoKeys
	3072: ("ProjectedCSTypeGeoKey", [3], None, None),        # epsg grid code [20000 - 32760]
	3073: ("PCSCitationGeoKey", [2], None, None),            # ASCII text
	3074: ("ProjectionGeoKey", [3], None, None),             # [10000 - 19999]
	3075: ("ProjCoordTransGeoKey", [3], None, None),
	3076: ("ProjLinearUnitsGeoKey", [3], None, None),
	3077: ("ProjLinearUnitSizeGeoKey", [12], None, None),    # custom unit in meters
	3078: ("ProjStdParallel1GeoKey", [12], None, None),
	3079: ("ProjStdParallel2GeoKey", [12], None, None),
	3080: ("ProjNatOriginLongGeoKey", [12], None, None),
	3081: ("ProjNatOriginLatGeoKey", [12], None, None),
	3082: ("ProjFalseEastingGeoKey", [12], None, None),
	3083: ("ProjFalseNorthingGeoKey", [12], None, None),
	3084: ("ProjFalseOriginLongGeoKey", [12], None, None),
	3085: ("ProjFalseOriginLatGeoKey", [12], None, None),
	3086: ("ProjFalseOriginEastingGeoKey", [12], None, None),
	3087: ("ProjFalseOriginNorthingGeoKey", [12], None, None),
	3088: ("ProjCenterLongGeoKey", [12], None, None),
	3089: ("ProjCenterLatGeoKey", [12], None, None),
	3090: ("ProjCenterEastingGeoKey", [12], None, None),
	3091: ("ProjFalseOriginNorthingGeoKey", [12], None, None),
	3092: ("ProjScaleAtNatOriginGeoKey", [12], None, None),
	3093: ("ProjScaleAtCenterGeoKey", [12], None, None),
	3094: ("ProjAzimuthAngleGeoKey", [12], None, None),
	3095: ("ProjStraightVertPoleLongGeoKey", [12], None, None),
	
	# Vertical CS Parameter Keys
	4096: ("VerticalCSTypeGeoKey", [3], None, None),
	4097: ("VerticalCitationGeoKey", [2], None, None),
	4098: ("VerticalDatumGeoKey", [3], None, None),
	4099: ("VerticalUnitsGeoKey", [3], None, None),
}

_2TAG = dict((v[0], t) for t,v in _TAGS.items())
_2KEY = dict((v, k) for k,v in _2TAG.items())

if sys.version_info[0] >= 3:
	import functools
	reduce = functools.reduce
	long = int

class GkdTag(TiffTag):

	def __init__(self, tag=0x0, value=None, name="GeoTiff Tag"):
		self.name = name
		if tag == 0: return
		self.key, types, default, self.comment = _TAGS.get(tag, ("Unknown", [0,], None, "Undefined tag"))
		value = default if value == None else value

		self.tag = tag
		restricted = getattr(values, self.key, None)

		if restricted:
			if value in restricted:
				self.meaning = restricted.get(value)
			else:
				reverse = dict((v,k) for k,v in restricted.items())
				if value in reverse:
					value = reverse[value]
					self.meaning = value
				else:
					raise ValueError('"%s" value must be one of %s, get %s instead' % (self.key, list(restricted.keys()), value))

		self.type, self.count, self.value = self._encode(value, types)

	def __setattr__(self, attr, value):
		object.__setattr__(self, attr, value)

	def _encode(self, value, types):
		if isinstance(value, str): value = value.encode()
		elif not hasattr(value, "__len__"): value = (value, )
		typ = 0
		if 2 in types: typ = 34737
		elif 12 in types: typ = 34736
		return typ, len(value), value

	def _decode(self):
		if self.count == 1: return self.value[0]
		else: return self.value


class Gkd(dict):
	tagname = "Geotiff Tag"
	version = __geotiff__[0]
	revision = __geotiff__[1:]

	def __init__(self, value={}, **pairs):
		dict.__init__(self)
		self.from_ifd(value, **pairs)

	def __getitem__(self, tag):
		if isinstance(tag, str): tag = _2TAG[tag]
		return dict.__getitem__(self, tag)._decode()

	def __setitem__(self, tag, value):
		if isinstance(tag, str): tag = _2TAG[tag]
		dict.__setitem__(self, tag, GkdTag(tag, value, name=self.tagname))

	def get(self, tag, error=None):
		if hasattr(self, "_%s" % tag): return getattr(self, "_%s" % tag)
		else: return dict.get(self, tag, error)

	def to_ifd(self):
		_34735, _34736, _34737, nbkey, _ifd = (), (), b"", 0, {}
		for key,tag in sorted(self.items(), key = lambda a: a[0]):
			if tag.type == 0:
				_34735 += (key, 0, 1) + tag.value
				nbkey += 1
			elif tag.type == 34736: # GeoDoubleParamsTag
				_34735 += (key, 34736, 1, len(_34736))
				_34736 += tag.value
				nbkey += 1
			elif tag.type == 34737: # GeoAsciiParamsTag
				_34735 += (key, 34737, tag.count+1, len(_34737))
				_34737 += tag.value + b"|"
				nbkey += 1

		return dict((k,v) for k,v in {
			33922: TiffTag(33922, reduce(tuple.__add__, [tuple(e) for e in self.get(33922, ())])),
			33550: TiffTag(33550, tuple(self.get(33550, ()))),
			34264: TiffTag(34264, tuple(self.get(34264, ()))),
			34735: TiffTag(34735, (self.version,) + self.revision + (nbkey,) + _34735),
			34736: TiffTag(34736, _34736),
			34737: TiffTag(34737, _34737),
		}.items() if v.value != ())

	def from_ifd(self, ifd = {}, **kw):
		pairs = dict(ifd, **kw)
		for tag in [t for t in [33922, 33550, 34264] if t in pairs]: # ModelTiepointTag, ModelPixelScaleTag, ModelTransformationTag
			nt = GeoKeyModel[tag]
			if tag == 33922: # can be more than one TiePoint
				n = len(nt._fields)
				seq = ifd[tag]
				setattr(self, "_%s" % tag, tuple(nt(*seq[i:i+n]) for i in range(0, len(seq), n)))
			else:
				setattr(self, "_%s" % tag, nt(*ifd[tag]))
		if 34736 in pairs: # GeoDoubleParamsTag
			_34736 = ifd[34736]
		if 34737 in pairs: # GeoAsciiParamsTag
			_34737 = ifd[34737]
		if 34735 in pairs: # GeoKeyDirectoryTag
			_34735 = ifd[34735]
			self.version = _34735[0]
			self.revision = _34735[1:3]
			for (tag, typ, count, value) in zip(_34735[4::4],_34735[5::4],_34735[6::4],_34735[7::4]):
				if typ == 0: self[tag] = value
				elif typ == 34736: self[tag] = _34736[value]
				elif typ == 34737: self[tag] = _34737[value:value+count-1]

	def getModelTransformation(self, tie_index=0):
		if hasattr(self, "_34264"):
			matrix = GeoKeyModel[34264](*getattr(self, "_34264"))
		elif hasattr(self, "_33922") and hasattr(self, "_33550"):
			Sx, Sy, Sz = getattr(self, "_33550")
			I, J, K, X, Y, Z = getattr(self, "_33922")[tie_index]
			matrix = GeoKeyModel[34264](
				Sx,  0., 0., X - I*Sx,
				0., -Sy, 0., Y + J*Sy,
				0., 0. , Sz, Z - K*Sz,
				0., 0. , 0., 1.
			)
		else:
			matrix = GeoKeyModel[34264](
				1., 0. , 0., 0.,
				0., -1., 0., 0.,
				0., 0. , 1., 0.,
				0., 0. , 0., 1.
			)
		return lambda x,y,z1=0.,z2=1.,m=matrix: Transform(m, x,y,z1,z2)

	def tags(self):
		for v in sorted(dict.values(self), key=lambda e:e.tag):
			yield v



########################
#Values
########################

class values():

    ## Tiff tag values
    NewSubfileType = {
    	0: "bit flag 000",
    	1: "bit flag 001",
    	2: "bit flag 010",
    	3: "bit flag 011",
    	4: "bit flag 100",
    	5: "bit flag 101",
    	6: "bit flag 110",
    	7: "bit flag 111"
    }

    SubfileType = {
    	1: "Full-resolution image data",
    	2: "Reduced-resolution image data",
    	3: "Single page of a multi-page image"
    }

    Compression = {
    	1:     "Uncompressed",
    	2:     "CCITT 1d",
    	3:     "Group 3 Fax",
    	4:     "Group 4 Fax",
    	5:     "LZW",
    	6:     "JPEG",
    	7:     "JPEG ('new-style' JPEG)",
    	8:     "Deflate ('Adobe-style')",
    	9:     "TIFF-F and TIFF-FX standard (RFC 2301) B&W",
    	10:    "TIFF-F and TIFF-FX standard (RFC 2301) RGB",
    	32771: "CCITTRLEW",  # 16-bit padding
    	32773: "PACKBITS",
    	32809: "THUNDERSCAN",
    	32895: "IT8CTPAD",
    	32896: "IT8LW",
    	32897: "IT8MP",
    	32908: "PIXARFILM",
    	32909: "PIXARLOG",
    	32946: "DEFLATE",
    	32947: "DCS",
    	34661: "JBIG",
    	34676: "SGILOG",
    	34677: "SGILOG24",
    	34712: "JP2000",
    }

    PhotometricInterpretation = {
    	0:     "WhiteIsZero",
    	1:     "BlackIsZero",
    	2:     "RGB",
    	3:     "RGB Palette",
    	4:     "Transparency Mask",
    	5:     "CMYK",
    	6:     "YCbCr",
    	8:     "CIE L*a*b*",
    	9:     "ICC L*a*b*",
    	10:    "ITU L*a*b*",
    	32803: "CFA",       # TIFF/EP, Adobe DNG
    	32892: "LinearRaw"  # Adobe DNG
    }

    Thresholding = {
    	1: "No dithering or halftoning has been applied to the image data",
    	2: "An ordered dither or halftone technique has been applied to the image data",
    	3: "A randomized process such as error diffusion has been applied to the image data"
    }

    FillOrder = {
    	1: "Values stored in the higher-order bits of the byte",
    	2: "Values stored in the lower-order bits of the byte"
    }

    Orientation = {
    #   1        2       3      4         5            6           7          8
    # 888888  888888      88  88      8888888888  88                  88  8888888888
    # 88          88      88  88      88  88      88  88          88  88      88  88
    # 8888      8888    8888  8888    88          8888888888  8888888888          88
    # 88          88      88  88
    # 88          88  888888  888888
    	1: "Normal",
    	2: "Fliped left to right",
    	3: "Rotated 180 deg",
    	4: "Fliped top to bottom",
    	5: "Fliped left to right + rotated 90 deg counter clockwise",
    	6: "Rotated 90 deg counter clockwise",
    	7: "Fliped left to right + rotated 90 deg clockwise",
    	8: "Rotated 90 deg clockwise"
    }

    PlanarConfiguration = {
    	1: "Chunky", #, format: RGBARGBARGBA....RGBA 
    	2: "Planar"  #, format: RRR.RGGG.GBBB.BAAA.A
    }

    GrayResponseUnit = {
    	1: "Number represents tenths of a unit",
    	2: "Number represents hundredths of a unit",
    	3: "Number represents thousandths of a unit",
    	4: "Number represents ten-thousandths of a unit",
    	5: "Number represents hundred-thousandths of a unit"
    }

    ResolutionUnit = {
    	1:"No unit",
    	2:"Inch",
    	3:"Centimeter"
    }

    T4Options = {
    	0: "bit flag 000",
    	1: "bit flag 001",
    	2: "bit flag 010",
    	3: "bit flag 011",
    	4: "bit flag 100",
    	5: "bit flag 101",
    	6: "bit flag 110",
    	7: "bit flag 111"
    }

    T6Options = {
    	0: "bit flag 00",
    	2: "bit flag 10",
    }

    Predictor = {
    	1: "No prediction",
    	2: "Horizontal differencing",
    	3: "Floating point horizontal differencing"
    }

    CleanFaxData = {
    	0: "No 'bad' lines",
    	1: "'bad' lines exist, but were regenerated by the receiver",
    	2: "'bad' lines exist, but have not been regenerated"
    }

    InkSet = {
    	1:"CMYK",
    	2:"Not CMYK"
    }

    SampleFormat = {
    	1: "Unsigned integer data",
    	2: "Two's complement signed integer data",
    	3: "IEEE floating point data [IEEE]",
    	4: "Undefined data format"
    }

    Indexed = {
    	0: "Not indexed",
    	1: "Indexed"
    }

    OPIProxy = {
    	0: "A higher-resolution version of this image does not exist",
    	1: "A higher-resolution version of this image exists, and the name of that image is found in the ImageID tag"
    }

    ProfileType = {
    	0: "Unspecified",
    	1: "Group 3 fax"
    }

    FaxProfile = {
    	0: "Does not conform to a profile defined for TIFF for facsimile",
    	1: "Minimal black & white lossless, Profile S",
    	2: "Extended black & white lossless, Profile F",
    	3: "Lossless JBIG black & white, Profile J",
    	4: "Lossy color and grayscale, Profile C",
    	5: "Lossless color and grayscale, Profile L",
    	6: "Mixed Raster Content, Profile M"
    }

    CodingMethods = {
    	0b1       : "Unspecified compression",
    	0b10      : "1-dimensional coding, ITU-T Rec. T.4 (MH - Modified Huffman)",
    	0b100     : "2-dimensional coding, ITU-T Rec. T.4 (MR - Modified Read)",
    	0b1000    : "2-dimensional coding, ITU-T Rec. T.6 (MMR - Modified MR)",
    	0b10000   : "ITU-T Rec. T.82 coding, using ITU-T Rec. T.85 (JBIG)",
    	0b100000  : "ITU-T Rec. T.81 (Baseline JPEG)",
    	0b1000000 : "ITU-T Rec. T.82 coding, using ITU-T Rec. T.43 (JBIG color)"
    }

    JPEGProc = {
    	1:  "Baseline sequential process",
    	14: "Lossless process with Huffman coding"
    }

    JPEGLosslessPredictors = {
    	1: "A",
    	2: "B",
    	3: "C",
    	4: "A+B-C",
    	5: "A+((B-C)/2)",
    	6: "B+((A-C)/2)",
    	7: "(A+B)/2"
    }

    YCbCrSubSampling = {
    	(0,1): "YCbCrSubsampleHoriz : ImageWidth of this chroma image is equal to the ImageWidth of the associated luma image",
    	(0,2): "YCbCrSubsampleHoriz : ImageWidth of this chroma image is half the ImageWidth of the associated luma image",
    	(0,4): "YCbCrSubsampleHoriz : ImageWidth of this chroma image is one-quarter the ImageWidth of the associated luma image",
    	(1,1): "YCbCrSubsampleVert : ImageLength (height) of this chroma image is equal to the ImageLength of the associated luma image",
    	(2,2): "YCbCrSubsampleVert : ImageLength (height) of this chroma image is half the ImageLength of the associated luma image",
    	(4,4): "YCbCrSubsampleVert : ImageLength (height) of this chroma image is one-quarter the ImageLength of the associated luma image"
    }

    YCbCrPositioning = {
    	1: "Centered", 
    	2: "Co-sited"
    }

    ## EXIF tag values
    ExposureProgram = {
    	0: "Not defined",
    	1: "Manual",
    	2: "Normal program",
    	3: "Aperture priority",
    	4: "Shutter priority",
    	5: "Creative program (biased toward depth of field)",
    	6: "Action program (biased toward fast shutter speed)",
    	7: "Portrait mode (for closeup photos with the background out of focus)",
    	8: "Landscape mode (for landscape photos with the background in focus)"
    }

    MeteringMode = {
    	0:   "Unknown",
    	1:   "Average",
    	2:   "Center Weighted Average",
    	3:   "Spot",
    	4:   "MultiSpot",
    	5:   "Pattern",
    	6:   "Partial",
    	255: "other"
    }

    LightSource = {
    	0:   "Unknown",
    	1:   "Daylight",
    	2:   "Fluorescent",
    	3:   "Tungsten (incandescent light)",
    	4:   "Flash",
    	9:   "Fine weather",
    	10:  "Cloudy weather",
    	11:  "Shade",
    	12:  "Daylight fluorescent (D 5700 - 7100K)",
    	13:  "Day white fluorescent (N 4600 - 5400K)",
    	14:  "Cool white fluorescent (W 3900 - 4500K)",
    	15:  "White fluorescent (WW 3200 - 3700K)",
    	17:  "Standard light A",
    	18:  "Standard light B",
    	19:  "Standard light C",
    	20:  "D55",
    	21:  "D65",
    	22:  "D75",
    	23:  "D50",
    	24:  "ISO studio tungsten",
    	255: "Other light source"
    }

    ColorSpace = {
    	1:     "RGB",
    	65535: "Uncalibrated"
    }

    Flash = {
    	0x0000: "Flash did not fire",
    	0x0001: "Flash fired",
    	0x0005: "Strobe return light not detected",
    	0x0007: "Strobe return light detected",
    	0x0008: "On, did not fire",
    	0x0009: "Flash fired, compulsory flash mode",
    	0x000D: "Flash fired, compulsory flash mode, return light not detected",
    	0x000F: "Flash fired, compulsory flash mode, return light detected",
    	0x0010: "Flash did not fire, compulsory flash mode",
    	0x0014: "Off, did not fire, return not detected",
    	0x0018: "Flash did not fire, auto mode",
    	0x0019: "Flash fired, auto mode",
    	0x001D: "Flash fired, auto mode, return light not detected",
    	0x001F: "Flash fired, auto mode, return light detected",
    	0x0020: "No flash function",
    	0x0030: "Off, no flash function",
    	0x0041: "Flash fired, red-eye reduction mode",
    	0x0045: "Flash fired, red-eye reduction mode, return light not detected",
    	0x0047: "Flash fired, red-eye reduction mode, return light detected",
    	0x0049: "Flash fired, compulsory flash mode, red-eye reduction mode",
    	0x004D: "Flash fired, compulsory flash mode, red-eye reduction mode, return light not detected",
    	0x004F: "Flash fired, compulsory flash mode, red-eye reduction mode, return light detected",
    	0x0050: "Off, red-eye reduction",
    	0x0058: "Auto, Did not fire, red-eye reduction",
    	0x0059: "Flash fired, auto mode, red-eye reduction mode",
    	0x005D: "Flash fired, auto mode, return light not detected, red-eye reduction mode",
    	0x005F: "Flash fired, auto mode, return light detected, red-eye reduction mode"
    }

    FocalPlaneResolutionUnit = {
    	1: "No absolute unit of measurement",
    	2: "Inch",
    	3: "Centimeter"
    }

    SensingMethod = {
    	1: "Not defined",
    	2: "One-chip color area sensor",
    	3: "Two-chip color area sensor",
    	4: "Three-chip color area sensor",
    	5: "Color sequential area sensor",
    	7: "Trilinear sensor",
    	8: "Color sequential linear sensor"
    }

    CustomRendered = {
    	0: "Normal process",
    	1: "Custom process"
    }

    ExposureMode = {
    	0: "Auto exposure",
    	1: "Manual exposure",
    	2: "Auto bracket"
    }

    WhiteBalance = {
    	0: "Auto white balance",
    	1: "Manual white balance"
    }

    SceneCaptureType = {
    	0: "Standard",
    	1: "Landscape",
    	2: "Portrait",
    	3: "Night scene"
    }

    GainControl = {
    	0: "None",
    	1: "Low gain up",
    	2: "High gain up",
    	3: "Low gain down",
    	4: "High gain down"
    }

    Contrast = {
    	0: "Normal",
    	1: "Soft",
    	2: "Hard"
    }

    Saturation = {
    	0: "Normal",
    	1: "Low saturation",
    	2: "High saturation"
    }

    Sharpness = Contrast

    SubjectDistanceRange = {
    	0: "Unknown",
    	1: "Macro",
    	2: "Close view",
    	3: "Distant view"
    }

    ## GPS tag values
    GPSAltitudeRef = {
    	0: "Above sea level",
    	1: "Below sea level"
    }

    GPSMeasureMode = {
    	b'2':   "2-dimensional measurement",
    	b'3':   "3-dimensional measurement",
    	b'2\x00': "2-dimensional measurement",
    	b'3\x00': "3-dimensional measurement"
    }

    GPSSpeedRef = {
    	b'K':     "Kilometers per hour",
    	b'M':     "Miles per hour",
    	b'N':     "Knots",
    	b'K\x00': "Kilometers per hour",
    	b'M\x00': "Miles per hour",
    	b'N\x00': "Knots"
    }

    GPSTrackRef = {
    	b'T':     "True direction",
    	b'M':     "Magnetic direction",
    	b'T\x00': "True direction",
    	b'M\x00': "Magnetic direction"
    }

    GPSImgDirectionRef = GPSTrackRef

    GPSLatitudeRef = {
    	b'N':     "North latitude",
    	b'S':     "South latitude",
    	b'N\x00': "North latitude",
    	b'S\x00': "South latitude"
    }
    GPSDestLatitudeRef = GPSLatitudeRef

    GPSLongitudeRef = {
    	b'E':     "East longitude",
    	b'W':     "West longitude",
    	b'E\x00': "East longitude",
    	b'W\x00': "West longitude"
    }
    GPSDestLongitudeRef = GPSLongitudeRef

    GPSDestBearingRef = GPSTrackRef
    GPSDestDistanceRef = GPSSpeedRef

    GPSDifferential = {
    	0: "Measurement without differential correction",
    	1: "Differential correction applied"
    }

    ## Geotiff tag values
    GTModelTypeGeoKey = {
    	0: "Undefined",
    	1: "Projection Coordinate System",
    	2: "Geographic (latitude,longitude) System",
    	3: "Geocentric (X,Y,Z) Coordinate System",
    }

    GTRasterTypeGeoKey = {
    		1: "Raster pixel is area",
    		2: "Raster pixel is point",
    }

    GeographicTypeGeoKey = {
    	4201: "GCS_Adindan",
    	4202: "GCS_AGD66",
    	4203: "GCS_AGD84",
    	4204: "GCS_Ain_el_Abd",
    	4205: "GCS_Afgooye",
    	4206: "GCS_Agadez",
    	4207: "GCS_Lisbon",
    	4208: "GCS_Aratu",
    	4209: "GCS_Arc_1950",
    	4210: "GCS_Arc_1960",
    	4211: "GCS_Batavia",
    	4212: "GCS_Barbados",
    	4213: "GCS_Beduaram",
    	4214: "GCS_Beijing_1954",
    	4215: "GCS_Belge_1950",
    	4216: "GCS_Bermuda_1957",
    	4217: "GCS_Bern_1898",
    	4218: "GCS_Bogota",
    	4219: "GCS_Bukit_Rimpah",
    	4220: "GCS_Camacupa",
    	4221: "GCS_Campo_Inchauspe",
    	4222: "GCS_Cape",
    	4223: "GCS_Carthage",
    	4224: "GCS_Chua",
    	4225: "GCS_Corrego_Alegre",
    	4226: "GCS_Cote_d_Ivoire",
    	4227: "GCS_Deir_ez_Zor",
    	4228: "GCS_Douala",
    	4229: "GCS_Egypt_1907",
    	4230: "GCS_ED50",
    	4231: "GCS_ED87",
    	4232: "GCS_Fahud",
    	4233: "GCS_Gandajika_1970",
    	4234: "GCS_Garoua",
    	4235: "GCS_Guyane_Francaise",
    	4236: "GCS_Hu_Tzu_Shan",
    	4237: "GCS_HD72",
    	4238: "GCS_ID74",
    	4239: "GCS_Indian_1954",
    	4240: "GCS_Indian_1975",
    	4241: "GCS_Jamaica_1875",
    	4242: "GCS_JAD69",
    	4243: "GCS_Kalianpur",
    	4244: "GCS_Kandawala",
    	4245: "GCS_Kertau",
    	4246: "GCS_KOC",
    	4247: "GCS_La_Canoa",
    	4248: "GCS_PSAD56",
    	4249: "GCS_Lake",
    	4250: "GCS_Leigon",
    	4251: "GCS_Liberia_1964",
    	4252: "GCS_Lome",
    	4253: "GCS_Luzon_1911",
    	4254: "GCS_Hito_XVIII_1963",
    	4255: "GCS_Herat_North",
    	4256: "GCS_Mahe_1971",
    	4257: "GCS_Makassar",
    	4258: "GCS_EUREF89",
    	4259: "GCS_Malongo_1987",
    	4260: "GCS_Manoca",
    	4261: "GCS_Merchich",
    	4262: "GCS_Massawa",
    	4263: "GCS_Minna",
    	4264: "GCS_Mhast",
    	4265: "GCS_Monte_Mario",
    	4266: "GCS_M_poraloko",
    	4267: "GCS_NAD27",
    	4268: "GCS_NAD_Michigan",
    	4269: "GCS_NAD83",
    	4270: "GCS_Nahrwan_1967",
    	4271: "GCS_Naparima_1972",
    	4272: "GCS_GD49",
    	4273: "GCS_NGO_1948",
    	4274: "GCS_Datum_73",
    	4275: "GCS_NTF",
    	4276: "GCS_NSWC_9Z_2",
    	4277: "GCS_OSGB_1936",
    	4278: "GCS_OSGB70",
    	4279: "GCS_OS_SN80",
    	4280: "GCS_Padang",
    	4281: "GCS_Palestine_1923",
    	4282: "GCS_Pointe_Noire",
    	4283: "GCS_GDA94",
    	4284: "GCS_Pulkovo_1942",
    	4285: "GCS_Qatar",
    	4286: "GCS_Qatar_1948",
    	4287: "GCS_Qornoq",
    	4288: "GCS_Loma_Quintana",
    	4289: "GCS_Amersfoort",
    	4290: "GCS_RT38",
    	4291: "GCS_SAD69",
    	4292: "GCS_Sapper_Hill_1943",
    	4293: "GCS_Schwarzeck",
    	4294: "GCS_Segora",
    	4295: "GCS_Serindung",
    	4296: "GCS_Sudan",
    	4297: "GCS_Tananarive",
    	4298: "GCS_Timbalai_1948",
    	4299: "GCS_TM65",
    	4300: "GCS_TM75",
    	4301: "GCS_Tokyo",
    	4302: "GCS_Trinidad_1903",
    	4303: "GCS_TC_1948",
    	4304: "GCS_Voirol_1875",
    	4305: "GCS_Voirol_Unifie",
    	4306: "GCS_Bern_1938",
    	4307: "GCS_Nord_Sahara_1959",
    	4308: "GCS_Stockholm_1938",
    	4309: "GCS_Yacare",
    	4310: "GCS_Yoff",
    	4311: "GCS_Zanderij",
    	4312: "GCS_MGI",
    	4313: "GCS_Belge_1972",
    	4314: "GCS_DHDN",
    	4315: "GCS_Conakry_1905",
    	4322: "GCS_WGS_72",
    	4324: "GCS_WGS_72BE",
    	4326: "GCS_WGS_84",
    	4801: "GCS_Bern_1898_Bern",
    	4802: "GCS_Bogota_Bogota",
    	4803: "GCS_Lisbon_Lisbon",
    	4804: "GCS_Makassar_Jakarta",
    	4805: "GCS_MGI_Ferro",
    	4806: "GCS_Monte_Mario_Rome",
    	4807: "GCS_NTF_Paris",
    	4808: "GCS_Padang_Jakarta",
    	4809: "GCS_Belge_1950_Brussels",
    	4810: "GCS_Tananarive_Paris",
    	4811: "GCS_Voirol_1875_Paris",
    	4812: "GCS_Voirol_Unifie_Paris",
    	4813: "GCS_Batavia_Jakarta",
    	4901: "GCS_ATF_Paris",
    	4902: "GCS_NDG_Paris",
    	# Ellipsoid-Only GCS:
    	4001: "GCSE_Airy1830",
    	4002: "GCSE_AiryModified1849",
    	4003: "GCSE_AustralianNationalSpheroid",
    	4004: "GCSE_Bessel1841",
    	4005: "GCSE_BesselModified",
    	4006: "GCSE_BesselNamibia",
    	4007: "GCSE_Clarke1858",
    	4008: "GCSE_Clarke1866",
    	4009: "GCSE_Clarke1866Michigan",
    	4010: "GCSE_Clarke1880_Benoit",
    	4011: "GCSE_Clarke1880_IGN",
    	4012: "GCSE_Clarke1880_RGS",
    	4013: "GCSE_Clarke1880_Arc",
    	4014: "GCSE_Clarke1880_SGA1922",
    	4015: "GCSE_Everest1830_1937Adjustment",
    	4016: "GCSE_Everest1830_1967Definition",
    	4017: "GCSE_Everest1830_1975Definition",
    	4018: "GCSE_Everest1830Modified",
    	4019: "GCSE_GRS1980",
    	4020: "GCSE_Helmert1906",
    	4021: "GCSE_IndonesianNationalSpheroid",
    	4022: "GCSE_International1924",
    	4023: "GCSE_International1967",
    	4024: "GCSE_Krassowsky1940",
    	4025: "GCSE_NWL9D",
    	4026: "GCSE_NWL10D",
    	4027: "GCSE_Plessis1817",
    	4028: "GCSE_Struve1860",
    	4029: "GCSE_WarOffice",
    	4030: "GCSE_WGS84",
    	4031: "GCSE_GEM10C",
    	4032: "GCSE_OSU86F",
    	4033: "GCSE_OSU91A",
    	4034: "GCSE_Clarke1880",
    	4035: "GCSE_Sphere",
    	32767: "User-defined"
    }

    GeogGeodeticDatumGeoKey = {
    	6201: "Datum_Adindan",
    	6202: "Datum_Australian_Geodetic_Datum_1966",
    	6203: "Datum_Australian_Geodetic_Datum_1984",
    	6204: "Datum_Ain_el_Abd_1970",
    	6205: "Datum_Afgooye",
    	6206: "Datum_Agadez",
    	6207: "Datum_Lisbon",
    	6208: "Datum_Aratu",
    	6209: "Datum_Arc_1950",
    	6210: "Datum_Arc_1960",
    	6211: "Datum_Batavia",
    	6212: "Datum_Barbados",
    	6213: "Datum_Beduaram",
    	6214: "Datum_Beijing_1954",
    	6215: "Datum_Reseau_National_Belge_1950",
    	6216: "Datum_Bermuda_1957",
    	6217: "Datum_Bern_1898",
    	6218: "Datum_Bogota",
    	6219: "Datum_Bukit_Rimpah",
    	6220: "Datum_Camacupa",
    	6221: "Datum_Campo_Inchauspe",
    	6222: "Datum_Cape",
    	6223: "Datum_Carthage",
    	6224: "Datum_Chua",
    	6225: "Datum_Corrego_Alegre",
    	6226: "Datum_Cote_d_Ivoire",
    	6227: "Datum_Deir_ez_Zor",
    	6228: "Datum_Douala",
    	6229: "Datum_Egypt_1907",
    	6230: "Datum_European_Datum_1950",
    	6231: "Datum_European_Datum_1987",
    	6232: "Datum_Fahud",
    	6233: "Datum_Gandajika_1970",
    	6234: "Datum_Garoua",
    	6235: "Datum_Guyane_Francaise",
    	6236: "Datum_Hu_Tzu_Shan",
    	6237: "Datum_Hungarian_Datum_1972",
    	6238: "Datum_Indonesian_Datum_1974",
    	6239: "Datum_Indian_1954",
    	6240: "Datum_Indian_1975",
    	6241: "Datum_Jamaica_1875",
    	6242: "Datum_Jamaica_1969",
    	6243: "Datum_Kalianpur",
    	6244: "Datum_Kandawala",
    	6245: "Datum_Kertau",
    	6246: "Datum_Kuwait_Oil_Company",
    	6247: "Datum_La_Canoa",
    	6248: "Datum_Provisional_S_American_Datum_1956",
    	6249: "Datum_Lake",
    	6250: "Datum_Leigon",
    	6251: "Datum_Liberia_1964",
    	6252: "Datum_Lome",
    	6253: "Datum_Luzon_1911",
    	6254: "Datum_Hito_XVIII_1963",
    	6255: "Datum_Herat_North",
    	6256: "Datum_Mahe_1971",
    	6257: "Datum_Makassar",
    	6258: "Datum_European_Reference_System_1989",
    	6259: "Datum_Malongo_1987",
    	6260: "Datum_Manoca",
    	6261: "Datum_Merchich",
    	6262: "Datum_Massawa",
    	6263: "Datum_Minna",
    	6264: "Datum_Mhast",
    	6265: "Datum_Monte_Mario",
    	6266: "Datum_M_poraloko",
    	6267: "Datum_North_American_Datum_1927",
    	6268: "Datum_NAD_Michigan",
    	6269: "Datum_North_American_Datum_1983",
    	6270: "Datum_Nahrwan_1967",
    	6271: "Datum_Naparima_1972",
    	6272: "Datum_New_Zealand_Geodetic_Datum_1949",
    	6273: "Datum_NGO_1948",
    	6274: "Datum_Datum_73",
    	6275: "Datum_Nouvelle_Triangulation_Francaise",
    	6276: "Datum_NSWC_9Z_2",
    	6277: "Datum_OSGB_1936",
    	6278: "Datum_OSGB_1970_SN",
    	6279: "Datum_OS_SN_1980",
    	6280: "Datum_Padang_1884",
    	6281: "Datum_Palestine_1923",
    	6282: "Datum_Pointe_Noire",
    	6283: "Datum_Geocentric_Datum_of_Australia_1994",
    	6284: "Datum_Pulkovo_1942",
    	6285: "Datum_Qatar",
    	6286: "Datum_Qatar_1948",
    	6287: "Datum_Qornoq",
    	6288: "Datum_Loma_Quintana",
    	6289: "Datum_Amersfoort",
    	6290: "Datum_RT38",
    	6291: "Datum_South_American_Datum_1969",
    	6292: "Datum_Sapper_Hill_1943",
    	6293: "Datum_Schwarzeck",
    	6294: "Datum_Segora",
    	6295: "Datum_Serindung",
    	6296: "Datum_Sudan",
    	6297: "Datum_Tananarive_1925",
    	6298: "Datum_Timbalai_1948",
    	6299: "Datum_TM65",
    	6300: "Datum_TM75",
    	6301: "Datum_Tokyo",
    	6302: "Datum_Trinidad_1903",
    	6303: "Datum_Trucial_Coast_1948",
    	6304: "Datum_Voirol_1875",
    	6305: "Datum_Voirol_Unifie_1960",
    	6306: "Datum_Bern_1938",
    	6307: "Datum_Nord_Sahara_1959",
    	6308: "Datum_Stockholm_1938",
    	6309: "Datum_Yacare",
    	6310: "Datum_Yoff",
    	6311: "Datum_Zanderij",
    	6312: "Datum_Militar_Geographische_Institut",
    	6313: "Datum_Reseau_National_Belge_1972",
    	6314: "Datum_Deutsche_Hauptdreiecksnetz",
    	6315: "Datum_Conakry_1905",
    	6322: "Datum_WGS72",
    	6324: "Datum_WGS72_Transit_Broadcast_Ephemeris",
    	6326: "Datum_WGS84",
    	6901: "Datum_Ancienne_Triangulation_Francaise",
    	6902: "Datum_Nord_de_Guerre",
    	# Ellipsoid-Only Datum:
    	6001: "DatumE_Airy1830",
    	6002: "DatumE_AiryModified1849",
    	6003: "DatumE_AustralianNationalSpheroid",
    	6004: "DatumE_Bessel1841",
    	6005: "DatumE_BesselModified",
    	6006: "DatumE_BesselNamibia",
    	6007: "DatumE_Clarke1858",
    	6008: "DatumE_Clarke1866",
    	6009: "DatumE_Clarke1866Michigan",
    	6010: "DatumE_Clarke1880_Benoit",
    	6011: "DatumE_Clarke1880_IGN",
    	6012: "DatumE_Clarke1880_RGS",
    	6013: "DatumE_Clarke1880_Arc",
    	6014: "DatumE_Clarke1880_SGA1922",
    	6015: "DatumE_Everest1830_1937Adjustment",
    	6016: "DatumE_Everest1830_1967Definition",
    	6017: "DatumE_Everest1830_1975Definition",
    	6018: "DatumE_Everest1830Modified",
    	6019: "DatumE_GRS1980",
    	6020: "DatumE_Helmert1906",
    	6021: "DatumE_IndonesianNationalSpheroid",
    	6022: "DatumE_International1924",
    	6023: "DatumE_International1967",
    	6024: "DatumE_Krassowsky1960",
    	6025: "DatumE_NWL9D",
    	6026: "DatumE_NWL10D",
    	6027: "DatumE_Plessis1817",
    	6028: "DatumE_Struve1860",
    	6029: "DatumE_WarOffice",
    	6030: "DatumE_WGS84",
    	6031: "DatumE_GEM10C",
    	6032: "DatumE_OSU86F",
    	6033: "DatumE_OSU91A",
    	6034: "DatumE_Clarke1880",
    	6035: "DatumE_Sphere",
    	32767: "User-defined"
    }

    GeogPrimeMeridianGeoKey = {
    	8901: "PM_Greenwich",
    	8902: "PM_Lisbon",
    	8903: "PM_Paris",
    	8904: "PM_Bogota",
    	8905: "PM_Madrid",
    	8906: "PM_Rome",
    	8907: "PM_Bern",
    	8908: "PM_Jakarta",
    	8909: "PM_Ferro",
    	8910: "PM_Brussels",
    	8911: "PM_Stockholm"
    }

    GeogLinearUnitsGeoKey = {
    	9001: "Linear_Meter",
    	9002: "Linear_Foot",
    	9003: "Linear_Foot_US_Survey",
    	9004: "Linear_Foot_Modified_American",
    	9005: "Linear_Foot_Clarke",
    	9006: "Linear_Foot_Indian",
    	9007: "Linear_Link",
    	9008: "Linear_Link_Benoit",
    	9009: "Linear_Link_Sears",
    	9010: "Linear_Chain_Benoit",
    	9011: "Linear_Chain_Sears",
    	9012: "Linear_Yard_Sears",
    	9013: "Linear_Yard_Indian",
    	9014: "Linear_Fathom",
    	9015: "Linear_Mile_International_Nautical"
    }

    GeogAngularUnitsGeoKey = {
    	9101: "Radian",
    	9102: "Degree",
    	9103: "Arc minute",
    	9104: "Arc second",
    	9105: "Grad",
    	9106: "Gon",
    	9107: "DMS",
    	9108: "DMS hemisphere"
    }

    GeogEllipsoidGeoKey = {
    	7001: "Ellipse_Airy_1830",
    	7002: "Ellipse_Airy_Modified_1849",
    	7003: "Ellipse_Australian_National_Spheroid",
    	7004: "Ellipse_Bessel_1841",
    	7005: "Ellipse_Bessel_Modified",
    	7006: "Ellipse_Bessel_Namibia",
    	7007: "Ellipse_Clarke_1858",
    	7008: "Ellipse_Clarke_1866",
    	7009: "Ellipse_Clarke_1866_Michigan",
    	7010: "Ellipse_Clarke_1880_Benoit",
    	7011: "Ellipse_Clarke_1880_IGN",
    	7012: "Ellipse_Clarke_1880_RGS",
    	7013: "Ellipse_Clarke_1880_Arc",
    	7014: "Ellipse_Clarke_1880_SGA_1922",
    	7015: "Ellipse_Everest_1830_1937_Adjustment",
    	7016: "Ellipse_Everest_1830_1967_Definition",
    	7017: "Ellipse_Everest_1830_1975_Definition",
    	7018: "Ellipse_Everest_1830_Modified",
    	7019: "Ellipse_GRS_1980",
    	7020: "Ellipse_Helmert_1906",
    	7021: "Ellipse_Indonesian_National_Spheroid",
    	7022: "Ellipse_International_1924",
    	7023: "Ellipse_International_1967",
    	7024: "Ellipse_Krassowsky_1940",
    	7025: "Ellipse_NWL_9D",
    	7026: "Ellipse_NWL_10D",
    	7027: "Ellipse_Plessis_1817",
    	7028: "Ellipse_Struve_1860",
    	7029: "Ellipse_War_Office",
    	7030: "Ellipse_WGS_84",
    	7031: "Ellipse_GEM_10C",
    	7032: "Ellipse_OSU86F",
    	7033: "Ellipse_OSU91A",
    	7034: "Ellipse_Clarke_1880",
    	7035: "Ellipse_Sphere",
    	32767: "User-defined"
    }

    GeogAzimuthUnitsGeoKey = GeogAngularUnitsGeoKey

    ProjectionGeoKey = {
    	10101: "Proj_Alabama_CS27_East",
    	10102: "Proj_Alabama_CS27_West",
    	10131: "Proj_Alabama_CS83_East",
    	10132: "Proj_Alabama_CS83_West",
    	10201: "Proj_Arizona_Coordinate_System_east",
    	10202: "Proj_Arizona_Coordinate_System_Central",
    	10203: "Proj_Arizona_Coordinate_System_west",
    	10231: "Proj_Arizona_CS83_east",
    	10232: "Proj_Arizona_CS83_Central",
    	10233: "Proj_Arizona_CS83_west",
    	10301: "Proj_Arkansas_CS27_North",
    	10302: "Proj_Arkansas_CS27_South",
    	10331: "Proj_Arkansas_CS83_North",
    	10332: "Proj_Arkansas_CS83_South",
    	10401: "Proj_California_CS27_I",
    	10402: "Proj_California_CS27_II",
    	10403: "Proj_California_CS27_III",
    	10404: "Proj_California_CS27_IV",
    	10405: "Proj_California_CS27_V",
    	10406: "Proj_California_CS27_VI",
    	10407: "Proj_California_CS27_VII",
    	10431: "Proj_California_CS83_1",
    	10432: "Proj_California_CS83_2",
    	10433: "Proj_California_CS83_3",
    	10434: "Proj_California_CS83_4",
    	10435: "Proj_California_CS83_5",
    	10436: "Proj_California_CS83_6",
    	10501: "Proj_Colorado_CS27_North",
    	10502: "Proj_Colorado_CS27_Central",
    	10503: "Proj_Colorado_CS27_South",
    	10531: "Proj_Colorado_CS83_North",
    	10532: "Proj_Colorado_CS83_Central",
    	10533: "Proj_Colorado_CS83_South",
    	10600: "Proj_Connecticut_CS27",
    	10630: "Proj_Connecticut_CS83",
    	10700: "Proj_Delaware_CS27",
    	10730: "Proj_Delaware_CS83",
    	10901: "Proj_Florida_CS27_East",
    	10902: "Proj_Florida_CS27_West",
    	10903: "Proj_Florida_CS27_North",
    	10931: "Proj_Florida_CS83_East",
    	10932: "Proj_Florida_CS83_West",
    	10933: "Proj_Florida_CS83_North",
    	11001: "Proj_Georgia_CS27_East",
    	11002: "Proj_Georgia_CS27_West",
    	11031: "Proj_Georgia_CS83_East",
    	11032: "Proj_Georgia_CS83_West",
    	11101: "Proj_Idaho_CS27_East",
    	11102: "Proj_Idaho_CS27_Central",
    	11103: "Proj_Idaho_CS27_West",
    	11131: "Proj_Idaho_CS83_East",
    	11132: "Proj_Idaho_CS83_Central",
    	11133: "Proj_Idaho_CS83_West",
    	11201: "Proj_Illinois_CS27_East",
    	11202: "Proj_Illinois_CS27_West",
    	11231: "Proj_Illinois_CS83_East",
    	11232: "Proj_Illinois_CS83_West",
    	11301: "Proj_Indiana_CS27_East",
    	11302: "Proj_Indiana_CS27_West",
    	11331: "Proj_Indiana_CS83_East",
    	11332: "Proj_Indiana_CS83_West",
    	11401: "Proj_Iowa_CS27_North",
    	11402: "Proj_Iowa_CS27_South",
    	11431: "Proj_Iowa_CS83_North",
    	11432: "Proj_Iowa_CS83_South",
    	11501: "Proj_Kansas_CS27_North",
    	11502: "Proj_Kansas_CS27_South",
    	11531: "Proj_Kansas_CS83_North",
    	11532: "Proj_Kansas_CS83_South",
    	11601: "Proj_Kentucky_CS27_North",
    	11602: "Proj_Kentucky_CS27_South",
    	11631: "Proj_Kentucky_CS83_North",
    	11632: "Proj_Kentucky_CS83_South",
    	11701: "Proj_Louisiana_CS27_North",
    	11702: "Proj_Louisiana_CS27_South",
    	11731: "Proj_Louisiana_CS83_North",
    	11732: "Proj_Louisiana_CS83_South",
    	11801: "Proj_Maine_CS27_East",
    	11802: "Proj_Maine_CS27_West",
    	11831: "Proj_Maine_CS83_East",
    	11832: "Proj_Maine_CS83_West",
    	11900: "Proj_Maryland_CS27",
    	11930: "Proj_Maryland_CS83",
    	12001: "Proj_Massachusetts_CS27_Mainland",
    	12002: "Proj_Massachusetts_CS27_Island",
    	12031: "Proj_Massachusetts_CS83_Mainland",
    	12032: "Proj_Massachusetts_CS83_Island",
    	12101: "Proj_Michigan_State_Plane_East",
    	12102: "Proj_Michigan_State_Plane_Old_Central",
    	12103: "Proj_Michigan_State_Plane_West",
    	12111: "Proj_Michigan_CS27_North",
    	12112: "Proj_Michigan_CS27_Central",
    	12113: "Proj_Michigan_CS27_South",
    	12141: "Proj_Michigan_CS83_North",
    	12142: "Proj_Michigan_CS83_Central",
    	12143: "Proj_Michigan_CS83_South",
    	12201: "Proj_Minnesota_CS27_North",
    	12202: "Proj_Minnesota_CS27_Central",
    	12203: "Proj_Minnesota_CS27_South",
    	12231: "Proj_Minnesota_CS83_North",
    	12232: "Proj_Minnesota_CS83_Central",
    	12233: "Proj_Minnesota_CS83_South",
    	12301: "Proj_Mississippi_CS27_East",
    	12302: "Proj_Mississippi_CS27_West",
    	12331: "Proj_Mississippi_CS83_East",
    	12332: "Proj_Mississippi_CS83_West",
    	12401: "Proj_Missouri_CS27_East",
    	12402: "Proj_Missouri_CS27_Central",
    	12403: "Proj_Missouri_CS27_West",
    	12431: "Proj_Missouri_CS83_East",
    	12432: "Proj_Missouri_CS83_Central",
    	12433: "Proj_Missouri_CS83_West",
    	12501: "Proj_Montana_CS27_North",
    	12502: "Proj_Montana_CS27_Central",
    	12503: "Proj_Montana_CS27_South",
    	12530: "Proj_Montana_CS83",
    	12601: "Proj_Nebraska_CS27_North",
    	12602: "Proj_Nebraska_CS27_South",
    	12630: "Proj_Nebraska_CS83",
    	12701: "Proj_Nevada_CS27_East",
    	12702: "Proj_Nevada_CS27_Central",
    	12703: "Proj_Nevada_CS27_West",
    	12731: "Proj_Nevada_CS83_East",
    	12732: "Proj_Nevada_CS83_Central",
    	12733: "Proj_Nevada_CS83_West",
    	12800: "Proj_New_Hampshire_CS27",
    	12830: "Proj_New_Hampshire_CS83",
    	12900: "Proj_New_Jersey_CS27",
    	12930: "Proj_New_Jersey_CS83",
    	13001: "Proj_New_Mexico_CS27_East",
    	13002: "Proj_New_Mexico_CS27_Central",
    	13003: "Proj_New_Mexico_CS27_West",
    	13031: "Proj_New_Mexico_CS83_East",
    	13032: "Proj_New_Mexico_CS83_Central",
    	13033: "Proj_New_Mexico_CS83_West",
    	13101: "Proj_New_York_CS27_East",
    	13102: "Proj_New_York_CS27_Central",
    	13103: "Proj_New_York_CS27_West",
    	13104: "Proj_New_York_CS27_Long_Island",
    	13131: "Proj_New_York_CS83_East",
    	13132: "Proj_New_York_CS83_Central",
    	13133: "Proj_New_York_CS83_West",
    	13134: "Proj_New_York_CS83_Long_Island",
    	13200: "Proj_North_Carolina_CS27",
    	13230: "Proj_North_Carolina_CS83",
    	13301: "Proj_North_Dakota_CS27_North",
    	13302: "Proj_North_Dakota_CS27_South",
    	13331: "Proj_North_Dakota_CS83_North",
    	13332: "Proj_North_Dakota_CS83_South",
    	13401: "Proj_Ohio_CS27_North",
    	13402: "Proj_Ohio_CS27_South",
    	13431: "Proj_Ohio_CS83_North",
    	13432: "Proj_Ohio_CS83_South",
    	13501: "Proj_Oklahoma_CS27_North",
    	13502: "Proj_Oklahoma_CS27_South",
    	13531: "Proj_Oklahoma_CS83_North",
    	13532: "Proj_Oklahoma_CS83_South",
    	13601: "Proj_Oregon_CS27_North",
    	13602: "Proj_Oregon_CS27_South",
    	13631: "Proj_Oregon_CS83_North",
    	13632: "Proj_Oregon_CS83_South",
    	13701: "Proj_Pennsylvania_CS27_North",
    	13702: "Proj_Pennsylvania_CS27_South",
    	13731: "Proj_Pennsylvania_CS83_North",
    	13732: "Proj_Pennsylvania_CS83_South",
    	13800: "Proj_Rhode_Island_CS27",
    	13830: "Proj_Rhode_Island_CS83",
    	13901: "Proj_South_Carolina_CS27_North",
    	13902: "Proj_South_Carolina_CS27_South",
    	13930: "Proj_South_Carolina_CS83",
    	14001: "Proj_South_Dakota_CS27_North",
    	14002: "Proj_South_Dakota_CS27_South",
    	14031: "Proj_South_Dakota_CS83_North",
    	14032: "Proj_South_Dakota_CS83_South",
    	14100: "Proj_Tennessee_CS27",
    	14130: "Proj_Tennessee_CS83",
    	14201: "Proj_Texas_CS27_North",
    	14202: "Proj_Texas_CS27_North_Central",
    	14203: "Proj_Texas_CS27_Central",
    	14204: "Proj_Texas_CS27_South_Central",
    	14205: "Proj_Texas_CS27_South",
    	14231: "Proj_Texas_CS83_North",
    	14232: "Proj_Texas_CS83_North_Central",
    	14233: "Proj_Texas_CS83_Central",
    	14234: "Proj_Texas_CS83_South_Central",
    	14235: "Proj_Texas_CS83_South",
    	14301: "Proj_Utah_CS27_North",
    	14302: "Proj_Utah_CS27_Central",
    	14303: "Proj_Utah_CS27_South",
    	14331: "Proj_Utah_CS83_North",
    	14332: "Proj_Utah_CS83_Central",
    	14333: "Proj_Utah_CS83_South",
    	14400: "Proj_Vermont_CS27",
    	14430: "Proj_Vermont_CS83",
    	14501: "Proj_Virginia_CS27_North",
    	14502: "Proj_Virginia_CS27_South",
    	14531: "Proj_Virginia_CS83_North",
    	14532: "Proj_Virginia_CS83_South",
    	14601: "Proj_Washington_CS27_North",
    	14602: "Proj_Washington_CS27_South",
    	14631: "Proj_Washington_CS83_North",
    	14632: "Proj_Washington_CS83_South",
    	14701: "Proj_West_Virginia_CS27_North",
    	14702: "Proj_West_Virginia_CS27_South",
    	14731: "Proj_West_Virginia_CS83_North",
    	14732: "Proj_West_Virginia_CS83_South",
    	14801: "Proj_Wisconsin_CS27_North",
    	14802: "Proj_Wisconsin_CS27_Central",
    	14803: "Proj_Wisconsin_CS27_South",
    	14831: "Proj_Wisconsin_CS83_North",
    	14832: "Proj_Wisconsin_CS83_Central",
    	14833: "Proj_Wisconsin_CS83_South",
    	14901: "Proj_Wyoming_CS27_East",
    	14902: "Proj_Wyoming_CS27_East_Central",
    	14903: "Proj_Wyoming_CS27_West_Central",
    	14904: "Proj_Wyoming_CS27_West",
    	14931: "Proj_Wyoming_CS83_East",
    	14932: "Proj_Wyoming_CS83_East_Central",
    	14933: "Proj_Wyoming_CS83_West_Central",
    	14934: "Proj_Wyoming_CS83_West",
    	15001: "Proj_Alaska_CS27_1",
    	15002: "Proj_Alaska_CS27_2",
    	15003: "Proj_Alaska_CS27_3",
    	15004: "Proj_Alaska_CS27_4",
    	15005: "Proj_Alaska_CS27_5",
    	15006: "Proj_Alaska_CS27_6",
    	15007: "Proj_Alaska_CS27_7",
    	15008: "Proj_Alaska_CS27_8",
    	15009: "Proj_Alaska_CS27_9",
    	15010: "Proj_Alaska_CS27_10",
    	15031: "Proj_Alaska_CS83_1",
    	15032: "Proj_Alaska_CS83_2",
    	15033: "Proj_Alaska_CS83_3",
    	15034: "Proj_Alaska_CS83_4",
    	15035: "Proj_Alaska_CS83_5",
    	15036: "Proj_Alaska_CS83_6",
    	15037: "Proj_Alaska_CS83_7",
    	15038: "Proj_Alaska_CS83_8",
    	15039: "Proj_Alaska_CS83_9",
    	15040: "Proj_Alaska_CS83_10",
    	15101: "Proj_Hawaii_CS27_1",
    	15102: "Proj_Hawaii_CS27_2",
    	15103: "Proj_Hawaii_CS27_3",
    	15104: "Proj_Hawaii_CS27_4",
    	15105: "Proj_Hawaii_CS27_5",
    	15131: "Proj_Hawaii_CS83_1",
    	15132: "Proj_Hawaii_CS83_2",
    	15133: "Proj_Hawaii_CS83_3",
    	15134: "Proj_Hawaii_CS83_4",
    	15135: "Proj_Hawaii_CS83_5",
    	15201: "Proj_Puerto_Rico_CS27",
    	15202: "Proj_St_Croix",
    	15230: "Proj_Puerto_Rico_Virgin_Is",
    	15914: "Proj_BLM_14N_feet",
    	15915: "Proj_BLM_15N_feet",
    	15916: "Proj_BLM_16N_feet",
    	15917: "Proj_BLM_17N_feet",
    	17348: "Proj_Map_Grid_of_Australia_48",
    	17349: "Proj_Map_Grid_of_Australia_49",
    	17350: "Proj_Map_Grid_of_Australia_50",
    	17351: "Proj_Map_Grid_of_Australia_51",
    	17352: "Proj_Map_Grid_of_Australia_52",
    	17353: "Proj_Map_Grid_of_Australia_53",
    	17354: "Proj_Map_Grid_of_Australia_54",
    	17355: "Proj_Map_Grid_of_Australia_55",
    	17356: "Proj_Map_Grid_of_Australia_56",
    	17357: "Proj_Map_Grid_of_Australia_57",
    	17358: "Proj_Map_Grid_of_Australia_58",
    	17448: "Proj_Australian_Map_Grid_48",
    	17449: "Proj_Australian_Map_Grid_49",
    	17450: "Proj_Australian_Map_Grid_50",
    	17451: "Proj_Australian_Map_Grid_51",
    	17452: "Proj_Australian_Map_Grid_52",
    	17453: "Proj_Australian_Map_Grid_53",
    	17454: "Proj_Australian_Map_Grid_54",
    	17455: "Proj_Australian_Map_Grid_55",
    	17456: "Proj_Australian_Map_Grid_56",
    	17457: "Proj_Australian_Map_Grid_57",
    	17458: "Proj_Australian_Map_Grid_58",
    	18031: "Proj_Argentina_1",
    	18032: "Proj_Argentina_2",
    	18033: "Proj_Argentina_3",
    	18034: "Proj_Argentina_4",
    	18035: "Proj_Argentina_5",
    	18036: "Proj_Argentina_6",
    	18037: "Proj_Argentina_7",
    	18051: "Proj_Colombia_3W",
    	18052: "Proj_Colombia_Bogota",
    	18053: "Proj_Colombia_3E",
    	18054: "Proj_Colombia_6E",
    	18072: "Proj_Egypt_Red_Belt",
    	18073: "Proj_Egypt_Purple_Belt",
    	18074: "Proj_Extended_Purple_Belt",
    	18141: "Proj_New_Zealand_North_Island_Nat_Grid",
    	18142: "Proj_New_Zealand_South_Island_Nat_Grid",
    	19900: "Proj_Bahrain_Grid",
    	19905: "Proj_Netherlands_E_Indies_Equatorial",
    	19912: "Proj_RSO_Borneo",
    	32767: "User-defined"
    }

    ProjectedCSTypeGeoKey = {
    	20137: "PCS_Adindan_UTM_zone_37N",
    	20138: "PCS_Adindan_UTM_zone_38N",
    	20248: "PCS_AGD66_AMG_zone_48",
    	20249: "PCS_AGD66_AMG_zone_49",
    	20250: "PCS_AGD66_AMG_zone_50",
    	20251: "PCS_AGD66_AMG_zone_51",
    	20252: "PCS_AGD66_AMG_zone_52",
    	20253: "PCS_AGD66_AMG_zone_53",
    	20254: "PCS_AGD66_AMG_zone_54",
    	20255: "PCS_AGD66_AMG_zone_55",
    	20256: "PCS_AGD66_AMG_zone_56",
    	20257: "PCS_AGD66_AMG_zone_57",
    	20258: "PCS_AGD66_AMG_zone_58",
    	20348: "PCS_AGD84_AMG_zone_48",
    	20349: "PCS_AGD84_AMG_zone_49",
    	20350: "PCS_AGD84_AMG_zone_50",
    	20351: "PCS_AGD84_AMG_zone_51",
    	20352: "PCS_AGD84_AMG_zone_52",
    	20353: "PCS_AGD84_AMG_zone_53",
    	20354: "PCS_AGD84_AMG_zone_54",
    	20355: "PCS_AGD84_AMG_zone_55",
    	20356: "PCS_AGD84_AMG_zone_56",
    	20357: "PCS_AGD84_AMG_zone_57",
    	20358: "PCS_AGD84_AMG_zone_58",
    	20437: "PCS_Ain_el_Abd_UTM_zone_37N",
    	20438: "PCS_Ain_el_Abd_UTM_zone_38N",
    	20439: "PCS_Ain_el_Abd_UTM_zone_39N",
    	20499: "PCS_Ain_el_Abd_Bahrain_Grid",
    	20538: "PCS_Afgooye_UTM_zone_38N",
    	20539: "PCS_Afgooye_UTM_zone_39N",
    	20700: "PCS_Lisbon_Portugese_Grid",
    	20822: "PCS_Aratu_UTM_zone_22S",
    	20823: "PCS_Aratu_UTM_zone_23S",
    	20824: "PCS_Aratu_UTM_zone_24S",
    	20973: "PCS_Arc_1950_Lo13",
    	20975: "PCS_Arc_1950_Lo15",
    	20977: "PCS_Arc_1950_Lo17",
    	20979: "PCS_Arc_1950_Lo19",
    	20981: "PCS_Arc_1950_Lo21",
    	20983: "PCS_Arc_1950_Lo23",
    	20985: "PCS_Arc_1950_Lo25",
    	20987: "PCS_Arc_1950_Lo27",
    	20989: "PCS_Arc_1950_Lo29",
    	20991: "PCS_Arc_1950_Lo31",
    	20993: "PCS_Arc_1950_Lo33",
    	20995: "PCS_Arc_1950_Lo35",
    	21100: "PCS_Batavia_NEIEZ",
    	21148: "PCS_Batavia_UTM_zone_48S",
    	21149: "PCS_Batavia_UTM_zone_49S",
    	21150: "PCS_Batavia_UTM_zone_50S",
    	21413: "PCS_Beijing_Gauss_zone_13",
    	21414: "PCS_Beijing_Gauss_zone_14",
    	21415: "PCS_Beijing_Gauss_zone_15",
    	21416: "PCS_Beijing_Gauss_zone_16",
    	21417: "PCS_Beijing_Gauss_zone_17",
    	21418: "PCS_Beijing_Gauss_zone_18",
    	21419: "PCS_Beijing_Gauss_zone_19",
    	21420: "PCS_Beijing_Gauss_zone_20",
    	21421: "PCS_Beijing_Gauss_zone_21",
    	21422: "PCS_Beijing_Gauss_zone_22",
    	21423: "PCS_Beijing_Gauss_zone_23",
    	21473: "PCS_Beijing_Gauss_13N",
    	21474: "PCS_Beijing_Gauss_14N",
    	21475: "PCS_Beijing_Gauss_15N",
    	21476: "PCS_Beijing_Gauss_16N",
    	21477: "PCS_Beijing_Gauss_17N",
    	21478: "PCS_Beijing_Gauss_18N",
    	21479: "PCS_Beijing_Gauss_19N",
    	21480: "PCS_Beijing_Gauss_20N",
    	21481: "PCS_Beijing_Gauss_21N",
    	21482: "PCS_Beijing_Gauss_22N",
    	21483: "PCS_Beijing_Gauss_23N",
    	21500: "PCS_Belge_Lambert_50",
    	21790: "PCS_Bern_1898_Swiss_Old",
    	21817: "PCS_Bogota_UTM_zone_17N",
    	21818: "PCS_Bogota_UTM_zone_18N",
    	21891: "PCS_Bogota_Colombia_3W",
    	21892: "PCS_Bogota_Colombia_Bogota",
    	21893: "PCS_Bogota_Colombia_3E",
    	21894: "PCS_Bogota_Colombia_6E",
    	22032: "PCS_Camacupa_UTM_32S",
    	22033: "PCS_Camacupa_UTM_33S",
    	22191: "PCS_C_Inchauspe_Argentina_1",
    	22192: "PCS_C_Inchauspe_Argentina_2",
    	22193: "PCS_C_Inchauspe_Argentina_3",
    	22194: "PCS_C_Inchauspe_Argentina_4",
    	22195: "PCS_C_Inchauspe_Argentina_5",
    	22196: "PCS_C_Inchauspe_Argentina_6",
    	22197: "PCS_C_Inchauspe_Argentina_7",
    	22332: "PCS_Carthage_UTM_zone_32N",
    	22391: "PCS_Carthage_Nord_Tunisie",
    	22392: "PCS_Carthage_Sud_Tunisie",
    	22523: "PCS_Corrego_Alegre_UTM_23S",
    	22524: "PCS_Corrego_Alegre_UTM_24S",
    	22832: "PCS_Douala_UTM_zone_32N",
    	22992: "PCS_Egypt_1907_Red_Belt",
    	22993: "PCS_Egypt_1907_Purple_Belt",
    	22994: "PCS_Egypt_1907_Ext_Purple",
    	23028: "PCS_ED50_UTM_zone_28N",
    	23029: "PCS_ED50_UTM_zone_29N",
    	23030: "PCS_ED50_UTM_zone_30N",
    	23031: "PCS_ED50_UTM_zone_31N",
    	23032: "PCS_ED50_UTM_zone_32N",
    	23033: "PCS_ED50_UTM_zone_33N",
    	23034: "PCS_ED50_UTM_zone_34N",
    	23035: "PCS_ED50_UTM_zone_35N",
    	23036: "PCS_ED50_UTM_zone_36N",
    	23037: "PCS_ED50_UTM_zone_37N",
    	23038: "PCS_ED50_UTM_zone_38N",
    	23239: "PCS_Fahud_UTM_zone_39N",
    	23240: "PCS_Fahud_UTM_zone_40N",
    	23433: "PCS_Garoua_UTM_zone_33N",
    	23846: "PCS_ID74_UTM_zone_46N",
    	23847: "PCS_ID74_UTM_zone_47N",
    	23848: "PCS_ID74_UTM_zone_48N",
    	23849: "PCS_ID74_UTM_zone_49N",
    	23850: "PCS_ID74_UTM_zone_50N",
    	23851: "PCS_ID74_UTM_zone_51N",
    	23852: "PCS_ID74_UTM_zone_52N",
    	23853: "PCS_ID74_UTM_zone_53N",
    	23886: "PCS_ID74_UTM_zone_46S",
    	23887: "PCS_ID74_UTM_zone_47S",
    	23888: "PCS_ID74_UTM_zone_48S",
    	23889: "PCS_ID74_UTM_zone_49S",
    	23890: "PCS_ID74_UTM_zone_50S",
    	23891: "PCS_ID74_UTM_zone_51S",
    	23892: "PCS_ID74_UTM_zone_52S",
    	23893: "PCS_ID74_UTM_zone_53S",
    	23894: "PCS_ID74_UTM_zone_54S",
    	23947: "PCS_Indian_1954_UTM_47N",
    	23948: "PCS_Indian_1954_UTM_48N",
    	24047: "PCS_Indian_1975_UTM_47N",
    	24048: "PCS_Indian_1975_UTM_48N",
    	24100: "PCS_Jamaica_1875_Old_Grid",
    	24200: "PCS_JAD69_Jamaica_Grid",
    	24370: "PCS_Kalianpur_India_0",
    	24371: "PCS_Kalianpur_India_I",
    	24372: "PCS_Kalianpur_India_IIa",
    	24373: "PCS_Kalianpur_India_IIIa",
    	24374: "PCS_Kalianpur_India_IVa",
    	24382: "PCS_Kalianpur_India_IIb",
    	24383: "PCS_Kalianpur_India_IIIb",
    	24384: "PCS_Kalianpur_India_IVb",
    	24500: "PCS_Kertau_Singapore_Grid",
    	24547: "PCS_Kertau_UTM_zone_47N",
    	24548: "PCS_Kertau_UTM_zone_48N",
    	24720: "PCS_La_Canoa_UTM_zone_20N",
    	24721: "PCS_La_Canoa_UTM_zone_21N",
    	24818: "PCS_PSAD56_UTM_zone_18N",
    	24819: "PCS_PSAD56_UTM_zone_19N",
    	24820: "PCS_PSAD56_UTM_zone_20N",
    	24821: "PCS_PSAD56_UTM_zone_21N",
    	24877: "PCS_PSAD56_UTM_zone_17S",
    	24878: "PCS_PSAD56_UTM_zone_18S",
    	24879: "PCS_PSAD56_UTM_zone_19S",
    	24880: "PCS_PSAD56_UTM_zone_20S",
    	24891: "PCS_PSAD56_Peru_west_zone",
    	24892: "PCS_PSAD56_Peru_central",
    	24893: "PCS_PSAD56_Peru_east_zone",
    	25000: "PCS_Leigon_Ghana_Grid",
    	25231: "PCS_Lome_UTM_zone_31N",
    	25391: "PCS_Luzon_Philippines_I",
    	25392: "PCS_Luzon_Philippines_II",
    	25393: "PCS_Luzon_Philippines_III",
    	25394: "PCS_Luzon_Philippines_IV",
    	25395: "PCS_Luzon_Philippines_V",
    	25700: "PCS_Makassar_NEIEZ",
    	25932: "PCS_Malongo_1987_UTM_32S",
    	26191: "PCS_Merchich_Nord_Maroc",
    	26192: "PCS_Merchich_Sud_Maroc",
    	26193: "PCS_Merchich_Sahara",
    	26237: "PCS_Massawa_UTM_zone_37N",
    	26331: "PCS_Minna_UTM_zone_31N",
    	26332: "PCS_Minna_UTM_zone_32N",
    	26391: "PCS_Minna_Nigeria_West",
    	26392: "PCS_Minna_Nigeria_Mid_Belt",
    	26393: "PCS_Minna_Nigeria_East",
    	26432: "PCS_Mhast_UTM_zone_32S",
    	26591: "PCS_Monte_Mario_Italy_1",
    	26592: "PCS_Monte_Mario_Italy_2",
    	26632: "PCS_M_poraloko_UTM_32N",
    	26692: "PCS_M_poraloko_UTM_32S",
    	26703: "PCS_NAD27_UTM_zone_3N",
    	26704: "PCS_NAD27_UTM_zone_4N",
    	26705: "PCS_NAD27_UTM_zone_5N",
    	26706: "PCS_NAD27_UTM_zone_6N",
    	26707: "PCS_NAD27_UTM_zone_7N",
    	26708: "PCS_NAD27_UTM_zone_8N",
    	26709: "PCS_NAD27_UTM_zone_9N",
    	26710: "PCS_NAD27_UTM_zone_10N",
    	26711: "PCS_NAD27_UTM_zone_11N",
    	26712: "PCS_NAD27_UTM_zone_12N",
    	26713: "PCS_NAD27_UTM_zone_13N",
    	26714: "PCS_NAD27_UTM_zone_14N",
    	26715: "PCS_NAD27_UTM_zone_15N",
    	26716: "PCS_NAD27_UTM_zone_16N",
    	26717: "PCS_NAD27_UTM_zone_17N",
    	26718: "PCS_NAD27_UTM_zone_18N",
    	26719: "PCS_NAD27_UTM_zone_19N",
    	26720: "PCS_NAD27_UTM_zone_20N",
    	26721: "PCS_NAD27_UTM_zone_21N",
    	26722: "PCS_NAD27_UTM_zone_22N",
    	26729: "PCS_NAD27_Alabama_East",
    	26730: "PCS_NAD27_Alabama_West",
    	26731: "PCS_NAD27_Alaska_zone_1",
    	26732: "PCS_NAD27_Alaska_zone_2",
    	26733: "PCS_NAD27_Alaska_zone_3",
    	26734: "PCS_NAD27_Alaska_zone_4",
    	26735: "PCS_NAD27_Alaska_zone_5",
    	26736: "PCS_NAD27_Alaska_zone_6",
    	26737: "PCS_NAD27_Alaska_zone_7",
    	26738: "PCS_NAD27_Alaska_zone_8",
    	26739: "PCS_NAD27_Alaska_zone_9",
    	26740: "PCS_NAD27_Alaska_zone_10",
    	26741: "PCS_NAD27_California_I",
    	26742: "PCS_NAD27_California_II",
    	26743: "PCS_NAD27_California_III",
    	26744: "PCS_NAD27_California_IV",
    	26745: "PCS_NAD27_California_V",
    	26746: "PCS_NAD27_California_VI",
    	26747: "PCS_NAD27_California_VII",
    	26748: "PCS_NAD27_Arizona_East",
    	26749: "PCS_NAD27_Arizona_Central",
    	26750: "PCS_NAD27_Arizona_West",
    	26751: "PCS_NAD27_Arkansas_North",
    	26752: "PCS_NAD27_Arkansas_South",
    	26753: "PCS_NAD27_Colorado_North",
    	26754: "PCS_NAD27_Colorado_Central",
    	26755: "PCS_NAD27_Colorado_South",
    	26756: "PCS_NAD27_Connecticut",
    	26757: "PCS_NAD27_Delaware",
    	26758: "PCS_NAD27_Florida_East",
    	26759: "PCS_NAD27_Florida_West",
    	26760: "PCS_NAD27_Florida_North",
    	26761: "PCS_NAD27_Hawaii_zone_1",
    	26762: "PCS_NAD27_Hawaii_zone_2",
    	26763: "PCS_NAD27_Hawaii_zone_3",
    	26764: "PCS_NAD27_Hawaii_zone_4",
    	26765: "PCS_NAD27_Hawaii_zone_5",
    	26766: "PCS_NAD27_Georgia_East",
    	26767: "PCS_NAD27_Georgia_West",
    	26768: "PCS_NAD27_Idaho_East",
    	26769: "PCS_NAD27_Idaho_Central",
    	26770: "PCS_NAD27_Idaho_West",
    	26771: "PCS_NAD27_Illinois_East",
    	26772: "PCS_NAD27_Illinois_West",
    	26773: "PCS_NAD27_Indiana_East",
    	26774: "PCS_NAD27_BLM_14N_feet",
    	26774: "PCS_NAD27_Indiana_West",
    	26775: "PCS_NAD27_BLM_15N_feet",
    	26775: "PCS_NAD27_Iowa_North",
    	26776: "PCS_NAD27_BLM_16N_feet",
    	26776: "PCS_NAD27_Iowa_South",
    	26777: "PCS_NAD27_BLM_17N_feet",
    	26777: "PCS_NAD27_Kansas_North",
    	26778: "PCS_NAD27_Kansas_South",
    	26779: "PCS_NAD27_Kentucky_North",
    	26780: "PCS_NAD27_Kentucky_South",
    	26781: "PCS_NAD27_Louisiana_North",
    	26782: "PCS_NAD27_Louisiana_South",
    	26783: "PCS_NAD27_Maine_East",
    	26784: "PCS_NAD27_Maine_West",
    	26785: "PCS_NAD27_Maryland",
    	26786: "PCS_NAD27_Massachusetts",
    	26787: "PCS_NAD27_Massachusetts_Is",
    	26788: "PCS_NAD27_Michigan_North",
    	26789: "PCS_NAD27_Michigan_Central",
    	26790: "PCS_NAD27_Michigan_South",
    	26791: "PCS_NAD27_Minnesota_North",
    	26792: "PCS_NAD27_Minnesota_Cent",
    	26793: "PCS_NAD27_Minnesota_South",
    	26794: "PCS_NAD27_Mississippi_East",
    	26795: "PCS_NAD27_Mississippi_West",
    	26796: "PCS_NAD27_Missouri_East",
    	26797: "PCS_NAD27_Missouri_Central",
    	26798: "PCS_NAD27_Missouri_West",
    	26801: "PCS_NAD_Michigan_Michigan_East",
    	26802: "PCS_NAD_Michigan_Michigan_Old_Central",
    	26803: "PCS_NAD_Michigan_Michigan_West",
    	26903: "PCS_NAD83_UTM_zone_3N",
    	26904: "PCS_NAD83_UTM_zone_4N",
    	26905: "PCS_NAD83_UTM_zone_5N",
    	26906: "PCS_NAD83_UTM_zone_6N",
    	26907: "PCS_NAD83_UTM_zone_7N",
    	26908: "PCS_NAD83_UTM_zone_8N",
    	26909: "PCS_NAD83_UTM_zone_9N",
    	26910: "PCS_NAD83_UTM_zone_10N",
    	26911: "PCS_NAD83_UTM_zone_11N",
    	26912: "PCS_NAD83_UTM_zone_12N",
    	26913: "PCS_NAD83_UTM_zone_13N",
    	26914: "PCS_NAD83_UTM_zone_14N",
    	26915: "PCS_NAD83_UTM_zone_15N",
    	26916: "PCS_NAD83_UTM_zone_16N",
    	26917: "PCS_NAD83_UTM_zone_17N",
    	26918: "PCS_NAD83_UTM_zone_18N",
    	26919: "PCS_NAD83_UTM_zone_19N",
    	26920: "PCS_NAD83_UTM_zone_20N",
    	26921: "PCS_NAD83_UTM_zone_21N",
    	26922: "PCS_NAD83_UTM_zone_22N",
    	26923: "PCS_NAD83_UTM_zone_23N",
    	26929: "PCS_NAD83_Alabama_East",
    	26930: "PCS_NAD83_Alabama_West",
    	26931: "PCS_NAD83_Alaska_zone_1",
    	26932: "PCS_NAD83_Alaska_zone_2",
    	26933: "PCS_NAD83_Alaska_zone_3",
    	26934: "PCS_NAD83_Alaska_zone_4",
    	26935: "PCS_NAD83_Alaska_zone_5",
    	26936: "PCS_NAD83_Alaska_zone_6",
    	26937: "PCS_NAD83_Alaska_zone_7",
    	26938: "PCS_NAD83_Alaska_zone_8",
    	26939: "PCS_NAD83_Alaska_zone_9",
    	26940: "PCS_NAD83_Alaska_zone_10",
    	26941: "PCS_NAD83_California_1",
    	26942: "PCS_NAD83_California_2",
    	26943: "PCS_NAD83_California_3",
    	26944: "PCS_NAD83_California_4",
    	26945: "PCS_NAD83_California_5",
    	26946: "PCS_NAD83_California_6",
    	26948: "PCS_NAD83_Arizona_East",
    	26949: "PCS_NAD83_Arizona_Central",
    	26950: "PCS_NAD83_Arizona_West",
    	26951: "PCS_NAD83_Arkansas_North",
    	26952: "PCS_NAD83_Arkansas_South",
    	26953: "PCS_NAD83_Colorado_North",
    	26954: "PCS_NAD83_Colorado_Central",
    	26955: "PCS_NAD83_Colorado_South",
    	26956: "PCS_NAD83_Connecticut",
    	26957: "PCS_NAD83_Delaware",
    	26958: "PCS_NAD83_Florida_East",
    	26959: "PCS_NAD83_Florida_West",
    	26960: "PCS_NAD83_Florida_North",
    	26961: "PCS_NAD83_Hawaii_zone_1",
    	26962: "PCS_NAD83_Hawaii_zone_2",
    	26963: "PCS_NAD83_Hawaii_zone_3",
    	26964: "PCS_NAD83_Hawaii_zone_4",
    	26965: "PCS_NAD83_Hawaii_zone_5",
    	26966: "PCS_NAD83_Georgia_East",
    	26967: "PCS_NAD83_Georgia_West",
    	26968: "PCS_NAD83_Idaho_East",
    	26969: "PCS_NAD83_Idaho_Central",
    	26970: "PCS_NAD83_Idaho_West",
    	26971: "PCS_NAD83_Illinois_East",
    	26972: "PCS_NAD83_Illinois_West",
    	26973: "PCS_NAD83_Indiana_East",
    	26974: "PCS_NAD83_Indiana_West",
    	26975: "PCS_NAD83_Iowa_North",
    	26976: "PCS_NAD83_Iowa_South",
    	26977: "PCS_NAD83_Kansas_North",
    	26978: "PCS_NAD83_Kansas_South",
    	26979: "PCS_NAD83_Kentucky_North",
    	26980: "PCS_NAD83_Kentucky_South",
    	26981: "PCS_NAD83_Louisiana_North",
    	26982: "PCS_NAD83_Louisiana_South",
    	26983: "PCS_NAD83_Maine_East",
    	26984: "PCS_NAD83_Maine_West",
    	26985: "PCS_NAD83_Maryland",
    	26986: "PCS_NAD83_Massachusetts",
    	26987: "PCS_NAD83_Massachusetts_Is",
    	26988: "PCS_NAD83_Michigan_North",
    	26989: "PCS_NAD83_Michigan_Central",
    	26990: "PCS_NAD83_Michigan_South",
    	26991: "PCS_NAD83_Minnesota_North",
    	26992: "PCS_NAD83_Minnesota_Cent",
    	26993: "PCS_NAD83_Minnesota_South",
    	26994: "PCS_NAD83_Mississippi_East",
    	26995: "PCS_NAD83_Mississippi_West",
    	26996: "PCS_NAD83_Missouri_East",
    	26997: "PCS_NAD83_Missouri_Central",
    	26998: "PCS_NAD83_Missouri_West",
    	27038: "PCS_Nahrwan_1967_UTM_38N",
    	27039: "PCS_Nahrwan_1967_UTM_39N",
    	27040: "PCS_Nahrwan_1967_UTM_40N",
    	27120: "PCS_Naparima_UTM_20N",
    	27200: "PCS_GD49_NZ_Map_Grid",
    	27291: "PCS_GD49_North_Island_Grid",
    	27292: "PCS_GD49_South_Island_Grid",
    	27429: "PCS_Datum_73_UTM_zone_29N",
    	27500: "PCS_ATF_Nord_de_Guerre",
    	27581: "PCS_NTF_France_I",
    	27582: "PCS_NTF_France_II",
    	27583: "PCS_NTF_France_III",
    	27591: "PCS_NTF_Nord_France",
    	27592: "PCS_NTF_Centre_France",
    	27593: "PCS_NTF_Sud_France",
    	27700: "PCS_British_National_Grid",
    	28232: "PCS_Point_Noire_UTM_32S",
    	28348: "PCS_GDA94_MGA_zone_48",
    	28349: "PCS_GDA94_MGA_zone_49",
    	28350: "PCS_GDA94_MGA_zone_50",
    	28351: "PCS_GDA94_MGA_zone_51",
    	28352: "PCS_GDA94_MGA_zone_52",
    	28353: "PCS_GDA94_MGA_zone_53",
    	28354: "PCS_GDA94_MGA_zone_54",
    	28355: "PCS_GDA94_MGA_zone_55",
    	28356: "PCS_GDA94_MGA_zone_56",
    	28357: "PCS_GDA94_MGA_zone_57",
    	28358: "PCS_GDA94_MGA_zone_58",
    	28404: "PCS_Pulkovo_Gauss_zone_4",
    	28405: "PCS_Pulkovo_Gauss_zone_5",
    	28406: "PCS_Pulkovo_Gauss_zone_6",
    	28407: "PCS_Pulkovo_Gauss_zone_7",
    	28408: "PCS_Pulkovo_Gauss_zone_8",
    	28409: "PCS_Pulkovo_Gauss_zone_9",
    	28410: "PCS_Pulkovo_Gauss_zone_10",
    	28411: "PCS_Pulkovo_Gauss_zone_11",
    	28412: "PCS_Pulkovo_Gauss_zone_12",
    	28413: "PCS_Pulkovo_Gauss_zone_13",
    	28414: "PCS_Pulkovo_Gauss_zone_14",
    	28415: "PCS_Pulkovo_Gauss_zone_15",
    	28416: "PCS_Pulkovo_Gauss_zone_16",
    	28417: "PCS_Pulkovo_Gauss_zone_17",
    	28418: "PCS_Pulkovo_Gauss_zone_18",
    	28419: "PCS_Pulkovo_Gauss_zone_19",
    	28420: "PCS_Pulkovo_Gauss_zone_20",
    	28421: "PCS_Pulkovo_Gauss_zone_21",
    	28422: "PCS_Pulkovo_Gauss_zone_22",
    	28423: "PCS_Pulkovo_Gauss_zone_23",
    	28424: "PCS_Pulkovo_Gauss_zone_24",
    	28425: "PCS_Pulkovo_Gauss_zone_25",
    	28426: "PCS_Pulkovo_Gauss_zone_26",
    	28427: "PCS_Pulkovo_Gauss_zone_27",
    	28428: "PCS_Pulkovo_Gauss_zone_28",
    	28429: "PCS_Pulkovo_Gauss_zone_29",
    	28430: "PCS_Pulkovo_Gauss_zone_30",
    	28431: "PCS_Pulkovo_Gauss_zone_31",
    	28432: "PCS_Pulkovo_Gauss_zone_32",
    	28464: "PCS_Pulkovo_Gauss_4N",
    	28465: "PCS_Pulkovo_Gauss_5N",
    	28466: "PCS_Pulkovo_Gauss_6N",
    	28467: "PCS_Pulkovo_Gauss_7N",
    	28468: "PCS_Pulkovo_Gauss_8N",
    	28469: "PCS_Pulkovo_Gauss_9N",
    	28470: "PCS_Pulkovo_Gauss_10N",
    	28471: "PCS_Pulkovo_Gauss_11N",
    	28472: "PCS_Pulkovo_Gauss_12N",
    	28473: "PCS_Pulkovo_Gauss_13N",
    	28474: "PCS_Pulkovo_Gauss_14N",
    	28475: "PCS_Pulkovo_Gauss_15N",
    	28476: "PCS_Pulkovo_Gauss_16N",
    	28477: "PCS_Pulkovo_Gauss_17N",
    	28478: "PCS_Pulkovo_Gauss_18N",
    	28479: "PCS_Pulkovo_Gauss_19N",
    	28480: "PCS_Pulkovo_Gauss_20N",
    	28481: "PCS_Pulkovo_Gauss_21N",
    	28482: "PCS_Pulkovo_Gauss_22N",
    	28483: "PCS_Pulkovo_Gauss_23N",
    	28484: "PCS_Pulkovo_Gauss_24N",
    	28485: "PCS_Pulkovo_Gauss_25N",
    	28486: "PCS_Pulkovo_Gauss_26N",
    	28487: "PCS_Pulkovo_Gauss_27N",
    	28488: "PCS_Pulkovo_Gauss_28N",
    	28489: "PCS_Pulkovo_Gauss_29N",
    	28490: "PCS_Pulkovo_Gauss_30N",
    	28491: "PCS_Pulkovo_Gauss_31N",
    	28492: "PCS_Pulkovo_Gauss_32N",
    	28600: "PCS_Qatar_National_Grid",
    	28991: "PCS_RD_Netherlands_Old",
    	28992: "PCS_RD_Netherlands_New",
    	29118: "PCS_SAD69_UTM_zone_18N",
    	29119: "PCS_SAD69_UTM_zone_19N",
    	29120: "PCS_SAD69_UTM_zone_20N",
    	29121: "PCS_SAD69_UTM_zone_21N",
    	29122: "PCS_SAD69_UTM_zone_22N",
    	29177: "PCS_SAD69_UTM_zone_17S",
    	29178: "PCS_SAD69_UTM_zone_18S",
    	29179: "PCS_SAD69_UTM_zone_19S",
    	29180: "PCS_SAD69_UTM_zone_20S",
    	29181: "PCS_SAD69_UTM_zone_21S",
    	29182: "PCS_SAD69_UTM_zone_22S",
    	29183: "PCS_SAD69_UTM_zone_23S",
    	29184: "PCS_SAD69_UTM_zone_24S",
    	29185: "PCS_SAD69_UTM_zone_25S",
    	29220: "PCS_Sapper_Hill_UTM_20S",
    	29221: "PCS_Sapper_Hill_UTM_21S",
    	29333: "PCS_Schwarzeck_UTM_33S",
    	29635: "PCS_Sudan_UTM_zone_35N",
    	29636: "PCS_Sudan_UTM_zone_36N",
    	29700: "PCS_Tananarive_Laborde",
    	29738: "PCS_Tananarive_UTM_38S",
    	29739: "PCS_Tananarive_UTM_39S",
    	29800: "PCS_Timbalai_1948_Borneo",
    	29849: "PCS_Timbalai_1948_UTM_49N",
    	29850: "PCS_Timbalai_1948_UTM_50N",
    	29900: "PCS_TM65_Irish_Nat_Grid",
    	30200: "PCS_Trinidad_1903_Trinidad",
    	30339: "PCS_TC_1948_UTM_zone_39N",
    	30340: "PCS_TC_1948_UTM_zone_40N",
    	30491: "PCS_Voirol_N_Algerie_ancien",
    	30492: "PCS_Voirol_S_Algerie_ancien",
    	30591: "PCS_Voirol_Unifie_N_Algerie",
    	30592: "PCS_Voirol_Unifie_S_Algerie",
    	30600: "PCS_Bern_1938_Swiss_New",
    	30729: "PCS_Nord_Sahara_UTM_29N",
    	30730: "PCS_Nord_Sahara_UTM_30N",
    	30731: "PCS_Nord_Sahara_UTM_31N",
    	30732: "PCS_Nord_Sahara_UTM_32N",
    	31028: "PCS_Yoff_UTM_zone_28N",
    	31121: "PCS_Zanderij_UTM_zone_21N",
    	31291: "PCS_MGI_Austria_West",
    	31292: "PCS_MGI_Austria_Central",
    	31293: "PCS_MGI_Austria_East",
    	31300: "PCS_Belge_Lambert_72",
    	31491: "PCS_DHDN_Germany_zone_1",
    	31492: "PCS_DHDN_Germany_zone_2",
    	31493: "PCS_DHDN_Germany_zone_3",
    	31494: "PCS_DHDN_Germany_zone_4",
    	31495: "PCS_DHDN_Germany_zone_5",
    	32001: "PCS_NAD27_Montana_North",
    	32002: "PCS_NAD27_Montana_Central",
    	32003: "PCS_NAD27_Montana_South",
    	32005: "PCS_NAD27_Nebraska_North",
    	32006: "PCS_NAD27_Nebraska_South",
    	32007: "PCS_NAD27_Nevada_East",
    	32008: "PCS_NAD27_Nevada_Central",
    	32009: "PCS_NAD27_Nevada_West",
    	32010: "PCS_NAD27_New_Hampshire",
    	32011: "PCS_NAD27_New_Jersey",
    	32012: "PCS_NAD27_New_Mexico_East",
    	32013: "PCS_NAD27_New_Mexico_Cent",
    	32014: "PCS_NAD27_New_Mexico_West",
    	32015: "PCS_NAD27_New_York_East",
    	32016: "PCS_NAD27_New_York_Central",
    	32017: "PCS_NAD27_New_York_West",
    	32018: "PCS_NAD27_New_York_Long_Is",
    	32019: "PCS_NAD27_North_Carolina",
    	32020: "PCS_NAD27_North_Dakota_N",
    	32021: "PCS_NAD27_North_Dakota_S",
    	32022: "PCS_NAD27_Ohio_North",
    	32023: "PCS_NAD27_Ohio_South",
    	32024: "PCS_NAD27_Oklahoma_North",
    	32025: "PCS_NAD27_Oklahoma_South",
    	32026: "PCS_NAD27_Oregon_North",
    	32027: "PCS_NAD27_Oregon_South",
    	32028: "PCS_NAD27_Pennsylvania_N",
    	32029: "PCS_NAD27_Pennsylvania_S",
    	32030: "PCS_NAD27_Rhode_Island",
    	32031: "PCS_NAD27_South_Carolina_N",
    	32033: "PCS_NAD27_South_Carolina_S",
    	32034: "PCS_NAD27_South_Dakota_N",
    	32035: "PCS_NAD27_South_Dakota_S",
    	32036: "PCS_NAD27_Tennessee",
    	32037: "PCS_NAD27_Texas_North",
    	32038: "PCS_NAD27_Texas_North_Cen",
    	32039: "PCS_NAD27_Texas_Central",
    	32040: "PCS_NAD27_Texas_South_Cen",
    	32041: "PCS_NAD27_Texas_South",
    	32042: "PCS_NAD27_Utah_North",
    	32043: "PCS_NAD27_Utah_Central",
    	32044: "PCS_NAD27_Utah_South",
    	32045: "PCS_NAD27_Vermont",
    	32046: "PCS_NAD27_Virginia_North",
    	32047: "PCS_NAD27_Virginia_South",
    	32048: "PCS_NAD27_Washington_North",
    	32049: "PCS_NAD27_Washington_South",
    	32050: "PCS_NAD27_West_Virginia_N",
    	32051: "PCS_NAD27_West_Virginia_S",
    	32052: "PCS_NAD27_Wisconsin_North",
    	32053: "PCS_NAD27_Wisconsin_Cen",
    	32054: "PCS_NAD27_Wisconsin_South",
    	32055: "PCS_NAD27_Wyoming_East",
    	32056: "PCS_NAD27_Wyoming_E_Cen",
    	32057: "PCS_NAD27_Wyoming_W_Cen",
    	32058: "PCS_NAD27_Wyoming_West",
    	32059: "PCS_NAD27_Puerto_Rico",
    	32060: "PCS_NAD27_St_Croix",
    	32100: "PCS_NAD83_Montana",
    	32104: "PCS_NAD83_Nebraska",
    	32107: "PCS_NAD83_Nevada_East",
    	32108: "PCS_NAD83_Nevada_Central",
    	32109: "PCS_NAD83_Nevada_West",
    	32110: "PCS_NAD83_New_Hampshire",
    	32111: "PCS_NAD83_New_Jersey",
    	32112: "PCS_NAD83_New_Mexico_East",
    	32113: "PCS_NAD83_New_Mexico_Cent",
    	32114: "PCS_NAD83_New_Mexico_West",
    	32115: "PCS_NAD83_New_York_East",
    	32116: "PCS_NAD83_New_York_Central",
    	32117: "PCS_NAD83_New_York_West",
    	32118: "PCS_NAD83_New_York_Long_Is",
    	32119: "PCS_NAD83_North_Carolina",
    	32120: "PCS_NAD83_North_Dakota_N",
    	32121: "PCS_NAD83_North_Dakota_S",
    	32122: "PCS_NAD83_Ohio_North",
    	32123: "PCS_NAD83_Ohio_South",
    	32124: "PCS_NAD83_Oklahoma_North",
    	32125: "PCS_NAD83_Oklahoma_South",
    	32126: "PCS_NAD83_Oregon_North",
    	32127: "PCS_NAD83_Oregon_South",
    	32128: "PCS_NAD83_Pennsylvania_N",
    	32129: "PCS_NAD83_Pennsylvania_S",
    	32130: "PCS_NAD83_Rhode_Island",
    	32133: "PCS_NAD83_South_Carolina",
    	32134: "PCS_NAD83_South_Dakota_N",
    	32135: "PCS_NAD83_South_Dakota_S",
    	32136: "PCS_NAD83_Tennessee",
    	32137: "PCS_NAD83_Texas_North",
    	32138: "PCS_NAD83_Texas_North_Cen",
    	32139: "PCS_NAD83_Texas_Central",
    	32140: "PCS_NAD83_Texas_South_Cen",
    	32141: "PCS_NAD83_Texas_South",
    	32142: "PCS_NAD83_Utah_North",
    	32143: "PCS_NAD83_Utah_Central",
    	32144: "PCS_NAD83_Utah_South",
    	32145: "PCS_NAD83_Vermont",
    	32146: "PCS_NAD83_Virginia_North",
    	32147: "PCS_NAD83_Virginia_South",
    	32148: "PCS_NAD83_Washington_North",
    	32149: "PCS_NAD83_Washington_South",
    	32150: "PCS_NAD83_West_Virginia_N",
    	32151: "PCS_NAD83_West_Virginia_S",
    	32152: "PCS_NAD83_Wisconsin_North",
    	32153: "PCS_NAD83_Wisconsin_Cen",
    	32154: "PCS_NAD83_Wisconsin_South",
    	32155: "PCS_NAD83_Wyoming_East",
    	32156: "PCS_NAD83_Wyoming_E_Cen",
    	32157: "PCS_NAD83_Wyoming_W_Cen",
    	32158: "PCS_NAD83_Wyoming_West",
    	32161: "PCS_NAD83_Puerto_Rico_Virgin_Is",
    	32201: "PCS_WGS72_UTM_zone_1N",
    	32202: "PCS_WGS72_UTM_zone_2N",
    	32203: "PCS_WGS72_UTM_zone_3N",
    	32204: "PCS_WGS72_UTM_zone_4N",
    	32205: "PCS_WGS72_UTM_zone_5N",
    	32206: "PCS_WGS72_UTM_zone_6N",
    	32207: "PCS_WGS72_UTM_zone_7N",
    	32208: "PCS_WGS72_UTM_zone_8N",
    	32209: "PCS_WGS72_UTM_zone_9N",
    	32210: "PCS_WGS72_UTM_zone_10N",
    	32211: "PCS_WGS72_UTM_zone_11N",
    	32212: "PCS_WGS72_UTM_zone_12N",
    	32213: "PCS_WGS72_UTM_zone_13N",
    	32214: "PCS_WGS72_UTM_zone_14N",
    	32215: "PCS_WGS72_UTM_zone_15N",
    	32216: "PCS_WGS72_UTM_zone_16N",
    	32217: "PCS_WGS72_UTM_zone_17N",
    	32218: "PCS_WGS72_UTM_zone_18N",
    	32219: "PCS_WGS72_UTM_zone_19N",
    	32220: "PCS_WGS72_UTM_zone_20N",
    	32221: "PCS_WGS72_UTM_zone_21N",
    	32222: "PCS_WGS72_UTM_zone_22N",
    	32223: "PCS_WGS72_UTM_zone_23N",
    	32224: "PCS_WGS72_UTM_zone_24N",
    	32225: "PCS_WGS72_UTM_zone_25N",
    	32226: "PCS_WGS72_UTM_zone_26N",
    	32227: "PCS_WGS72_UTM_zone_27N",
    	32228: "PCS_WGS72_UTM_zone_28N",
    	32229: "PCS_WGS72_UTM_zone_29N",
    	32230: "PCS_WGS72_UTM_zone_30N",
    	32231: "PCS_WGS72_UTM_zone_31N",
    	32232: "PCS_WGS72_UTM_zone_32N",
    	32233: "PCS_WGS72_UTM_zone_33N",
    	32234: "PCS_WGS72_UTM_zone_34N",
    	32235: "PCS_WGS72_UTM_zone_35N",
    	32236: "PCS_WGS72_UTM_zone_36N",
    	32237: "PCS_WGS72_UTM_zone_37N",
    	32238: "PCS_WGS72_UTM_zone_38N",
    	32239: "PCS_WGS72_UTM_zone_39N",
    	32240: "PCS_WGS72_UTM_zone_40N",
    	32241: "PCS_WGS72_UTM_zone_41N",
    	32242: "PCS_WGS72_UTM_zone_42N",
    	32243: "PCS_WGS72_UTM_zone_43N",
    	32244: "PCS_WGS72_UTM_zone_44N",
    	32245: "PCS_WGS72_UTM_zone_45N",
    	32246: "PCS_WGS72_UTM_zone_46N",
    	32247: "PCS_WGS72_UTM_zone_47N",
    	32248: "PCS_WGS72_UTM_zone_48N",
    	32249: "PCS_WGS72_UTM_zone_49N",
    	32250: "PCS_WGS72_UTM_zone_50N",
    	32251: "PCS_WGS72_UTM_zone_51N",
    	32252: "PCS_WGS72_UTM_zone_52N",
    	32253: "PCS_WGS72_UTM_zone_53N",
    	32254: "PCS_WGS72_UTM_zone_54N",
    	32255: "PCS_WGS72_UTM_zone_55N",
    	32256: "PCS_WGS72_UTM_zone_56N",
    	32257: "PCS_WGS72_UTM_zone_57N",
    	32258: "PCS_WGS72_UTM_zone_58N",
    	32259: "PCS_WGS72_UTM_zone_59N",
    	32260: "PCS_WGS72_UTM_zone_60N",
    	32301: "PCS_WGS72_UTM_zone_1S",
    	32302: "PCS_WGS72_UTM_zone_2S",
    	32303: "PCS_WGS72_UTM_zone_3S",
    	32304: "PCS_WGS72_UTM_zone_4S",
    	32305: "PCS_WGS72_UTM_zone_5S",
    	32306: "PCS_WGS72_UTM_zone_6S",
    	32307: "PCS_WGS72_UTM_zone_7S",
    	32308: "PCS_WGS72_UTM_zone_8S",
    	32309: "PCS_WGS72_UTM_zone_9S",
    	32310: "PCS_WGS72_UTM_zone_10S",
    	32311: "PCS_WGS72_UTM_zone_11S",
    	32312: "PCS_WGS72_UTM_zone_12S",
    	32313: "PCS_WGS72_UTM_zone_13S",
    	32314: "PCS_WGS72_UTM_zone_14S",
    	32315: "PCS_WGS72_UTM_zone_15S",
    	32316: "PCS_WGS72_UTM_zone_16S",
    	32317: "PCS_WGS72_UTM_zone_17S",
    	32318: "PCS_WGS72_UTM_zone_18S",
    	32319: "PCS_WGS72_UTM_zone_19S",
    	32320: "PCS_WGS72_UTM_zone_20S",
    	32321: "PCS_WGS72_UTM_zone_21S",
    	32322: "PCS_WGS72_UTM_zone_22S",
    	32323: "PCS_WGS72_UTM_zone_23S",
    	32324: "PCS_WGS72_UTM_zone_24S",
    	32325: "PCS_WGS72_UTM_zone_25S",
    	32326: "PCS_WGS72_UTM_zone_26S",
    	32327: "PCS_WGS72_UTM_zone_27S",
    	32328: "PCS_WGS72_UTM_zone_28S",
    	32329: "PCS_WGS72_UTM_zone_29S",
    	32330: "PCS_WGS72_UTM_zone_30S",
    	32331: "PCS_WGS72_UTM_zone_31S",
    	32332: "PCS_WGS72_UTM_zone_32S",
    	32333: "PCS_WGS72_UTM_zone_33S",
    	32334: "PCS_WGS72_UTM_zone_34S",
    	32335: "PCS_WGS72_UTM_zone_35S",
    	32336: "PCS_WGS72_UTM_zone_36S",
    	32337: "PCS_WGS72_UTM_zone_37S",
    	32338: "PCS_WGS72_UTM_zone_38S",
    	32339: "PCS_WGS72_UTM_zone_39S",
    	32340: "PCS_WGS72_UTM_zone_40S",
    	32341: "PCS_WGS72_UTM_zone_41S",
    	32342: "PCS_WGS72_UTM_zone_42S",
    	32343: "PCS_WGS72_UTM_zone_43S",
    	32344: "PCS_WGS72_UTM_zone_44S",
    	32345: "PCS_WGS72_UTM_zone_45S",
    	32346: "PCS_WGS72_UTM_zone_46S",
    	32347: "PCS_WGS72_UTM_zone_47S",
    	32348: "PCS_WGS72_UTM_zone_48S",
    	32349: "PCS_WGS72_UTM_zone_49S",
    	32350: "PCS_WGS72_UTM_zone_50S",
    	32351: "PCS_WGS72_UTM_zone_51S",
    	32352: "PCS_WGS72_UTM_zone_52S",
    	32353: "PCS_WGS72_UTM_zone_53S",
    	32354: "PCS_WGS72_UTM_zone_54S",
    	32355: "PCS_WGS72_UTM_zone_55S",
    	32356: "PCS_WGS72_UTM_zone_56S",
    	32357: "PCS_WGS72_UTM_zone_57S",
    	32358: "PCS_WGS72_UTM_zone_58S",
    	32359: "PCS_WGS72_UTM_zone_59S",
    	32360: "PCS_WGS72_UTM_zone_60S",
    	32401: "PCS_WGS72BE_UTM_zone_1N",
    	32402: "PCS_WGS72BE_UTM_zone_2N",
    	32403: "PCS_WGS72BE_UTM_zone_3N",
    	32404: "PCS_WGS72BE_UTM_zone_4N",
    	32405: "PCS_WGS72BE_UTM_zone_5N",
    	32406: "PCS_WGS72BE_UTM_zone_6N",
    	32407: "PCS_WGS72BE_UTM_zone_7N",
    	32408: "PCS_WGS72BE_UTM_zone_8N",
    	32409: "PCS_WGS72BE_UTM_zone_9N",
    	32410: "PCS_WGS72BE_UTM_zone_10N",
    	32411: "PCS_WGS72BE_UTM_zone_11N",
    	32412: "PCS_WGS72BE_UTM_zone_12N",
    	32413: "PCS_WGS72BE_UTM_zone_13N",
    	32414: "PCS_WGS72BE_UTM_zone_14N",
    	32415: "PCS_WGS72BE_UTM_zone_15N",
    	32416: "PCS_WGS72BE_UTM_zone_16N",
    	32417: "PCS_WGS72BE_UTM_zone_17N",
    	32418: "PCS_WGS72BE_UTM_zone_18N",
    	32419: "PCS_WGS72BE_UTM_zone_19N",
    	32420: "PCS_WGS72BE_UTM_zone_20N",
    	32421: "PCS_WGS72BE_UTM_zone_21N",
    	32422: "PCS_WGS72BE_UTM_zone_22N",
    	32423: "PCS_WGS72BE_UTM_zone_23N",
    	32424: "PCS_WGS72BE_UTM_zone_24N",
    	32425: "PCS_WGS72BE_UTM_zone_25N",
    	32426: "PCS_WGS72BE_UTM_zone_26N",
    	32427: "PCS_WGS72BE_UTM_zone_27N",
    	32428: "PCS_WGS72BE_UTM_zone_28N",
    	32429: "PCS_WGS72BE_UTM_zone_29N",
    	32430: "PCS_WGS72BE_UTM_zone_30N",
    	32431: "PCS_WGS72BE_UTM_zone_31N",
    	32432: "PCS_WGS72BE_UTM_zone_32N",
    	32433: "PCS_WGS72BE_UTM_zone_33N",
    	32434: "PCS_WGS72BE_UTM_zone_34N",
    	32435: "PCS_WGS72BE_UTM_zone_35N",
    	32436: "PCS_WGS72BE_UTM_zone_36N",
    	32437: "PCS_WGS72BE_UTM_zone_37N",
    	32438: "PCS_WGS72BE_UTM_zone_38N",
    	32439: "PCS_WGS72BE_UTM_zone_39N",
    	32440: "PCS_WGS72BE_UTM_zone_40N",
    	32441: "PCS_WGS72BE_UTM_zone_41N",
    	32442: "PCS_WGS72BE_UTM_zone_42N",
    	32443: "PCS_WGS72BE_UTM_zone_43N",
    	32444: "PCS_WGS72BE_UTM_zone_44N",
    	32445: "PCS_WGS72BE_UTM_zone_45N",
    	32446: "PCS_WGS72BE_UTM_zone_46N",
    	32447: "PCS_WGS72BE_UTM_zone_47N",
    	32448: "PCS_WGS72BE_UTM_zone_48N",
    	32449: "PCS_WGS72BE_UTM_zone_49N",
    	32450: "PCS_WGS72BE_UTM_zone_50N",
    	32451: "PCS_WGS72BE_UTM_zone_51N",
    	32452: "PCS_WGS72BE_UTM_zone_52N",
    	32453: "PCS_WGS72BE_UTM_zone_53N",
    	32454: "PCS_WGS72BE_UTM_zone_54N",
    	32455: "PCS_WGS72BE_UTM_zone_55N",
    	32456: "PCS_WGS72BE_UTM_zone_56N",
    	32457: "PCS_WGS72BE_UTM_zone_57N",
    	32458: "PCS_WGS72BE_UTM_zone_58N",
    	32459: "PCS_WGS72BE_UTM_zone_59N",
    	32460: "PCS_WGS72BE_UTM_zone_60N",
    	32501: "PCS_WGS72BE_UTM_zone_1S",
    	32502: "PCS_WGS72BE_UTM_zone_2S",
    	32503: "PCS_WGS72BE_UTM_zone_3S",
    	32504: "PCS_WGS72BE_UTM_zone_4S",
    	32505: "PCS_WGS72BE_UTM_zone_5S",
    	32506: "PCS_WGS72BE_UTM_zone_6S",
    	32507: "PCS_WGS72BE_UTM_zone_7S",
    	32508: "PCS_WGS72BE_UTM_zone_8S",
    	32509: "PCS_WGS72BE_UTM_zone_9S",
    	32510: "PCS_WGS72BE_UTM_zone_10S",
    	32511: "PCS_WGS72BE_UTM_zone_11S",
    	32512: "PCS_WGS72BE_UTM_zone_12S",
    	32513: "PCS_WGS72BE_UTM_zone_13S",
    	32514: "PCS_WGS72BE_UTM_zone_14S",
    	32515: "PCS_WGS72BE_UTM_zone_15S",
    	32516: "PCS_WGS72BE_UTM_zone_16S",
    	32517: "PCS_WGS72BE_UTM_zone_17S",
    	32518: "PCS_WGS72BE_UTM_zone_18S",
    	32519: "PCS_WGS72BE_UTM_zone_19S",
    	32520: "PCS_WGS72BE_UTM_zone_20S",
    	32521: "PCS_WGS72BE_UTM_zone_21S",
    	32522: "PCS_WGS72BE_UTM_zone_22S",
    	32523: "PCS_WGS72BE_UTM_zone_23S",
    	32524: "PCS_WGS72BE_UTM_zone_24S",
    	32525: "PCS_WGS72BE_UTM_zone_25S",
    	32526: "PCS_WGS72BE_UTM_zone_26S",
    	32527: "PCS_WGS72BE_UTM_zone_27S",
    	32528: "PCS_WGS72BE_UTM_zone_28S",
    	32529: "PCS_WGS72BE_UTM_zone_29S",
    	32530: "PCS_WGS72BE_UTM_zone_30S",
    	32531: "PCS_WGS72BE_UTM_zone_31S",
    	32532: "PCS_WGS72BE_UTM_zone_32S",
    	32533: "PCS_WGS72BE_UTM_zone_33S",
    	32534: "PCS_WGS72BE_UTM_zone_34S",
    	32535: "PCS_WGS72BE_UTM_zone_35S",
    	32536: "PCS_WGS72BE_UTM_zone_36S",
    	32537: "PCS_WGS72BE_UTM_zone_37S",
    	32538: "PCS_WGS72BE_UTM_zone_38S",
    	32539: "PCS_WGS72BE_UTM_zone_39S",
    	32540: "PCS_WGS72BE_UTM_zone_40S",
    	32541: "PCS_WGS72BE_UTM_zone_41S",
    	32542: "PCS_WGS72BE_UTM_zone_42S",
    	32543: "PCS_WGS72BE_UTM_zone_43S",
    	32544: "PCS_WGS72BE_UTM_zone_44S",
    	32545: "PCS_WGS72BE_UTM_zone_45S",
    	32546: "PCS_WGS72BE_UTM_zone_46S",
    	32547: "PCS_WGS72BE_UTM_zone_47S",
    	32548: "PCS_WGS72BE_UTM_zone_48S",
    	32549: "PCS_WGS72BE_UTM_zone_49S",
    	32550: "PCS_WGS72BE_UTM_zone_50S",
    	32551: "PCS_WGS72BE_UTM_zone_51S",
    	32552: "PCS_WGS72BE_UTM_zone_52S",
    	32553: "PCS_WGS72BE_UTM_zone_53S",
    	32554: "PCS_WGS72BE_UTM_zone_54S",
    	32555: "PCS_WGS72BE_UTM_zone_55S",
    	32556: "PCS_WGS72BE_UTM_zone_56S",
    	32557: "PCS_WGS72BE_UTM_zone_57S",
    	32558: "PCS_WGS72BE_UTM_zone_58S",
    	32559: "PCS_WGS72BE_UTM_zone_59S",
    	32560: "PCS_WGS72BE_UTM_zone_60S",
    	32601: "PCS_WGS84_UTM_zone_1N",
    	32602: "PCS_WGS84_UTM_zone_2N",
    	32603: "PCS_WGS84_UTM_zone_3N",
    	32604: "PCS_WGS84_UTM_zone_4N",
    	32605: "PCS_WGS84_UTM_zone_5N",
    	32606: "PCS_WGS84_UTM_zone_6N",
    	32607: "PCS_WGS84_UTM_zone_7N",
    	32608: "PCS_WGS84_UTM_zone_8N",
    	32609: "PCS_WGS84_UTM_zone_9N",
    	32610: "PCS_WGS84_UTM_zone_10N",
    	32611: "PCS_WGS84_UTM_zone_11N",
    	32612: "PCS_WGS84_UTM_zone_12N",
    	32613: "PCS_WGS84_UTM_zone_13N",
    	32614: "PCS_WGS84_UTM_zone_14N",
    	32615: "PCS_WGS84_UTM_zone_15N",
    	32616: "PCS_WGS84_UTM_zone_16N",
    	32617: "PCS_WGS84_UTM_zone_17N",
    	32618: "PCS_WGS84_UTM_zone_18N",
    	32619: "PCS_WGS84_UTM_zone_19N",
    	32620: "PCS_WGS84_UTM_zone_20N",
    	32621: "PCS_WGS84_UTM_zone_21N",
    	32622: "PCS_WGS84_UTM_zone_22N",
    	32623: "PCS_WGS84_UTM_zone_23N",
    	32624: "PCS_WGS84_UTM_zone_24N",
    	32625: "PCS_WGS84_UTM_zone_25N",
    	32626: "PCS_WGS84_UTM_zone_26N",
    	32627: "PCS_WGS84_UTM_zone_27N",
    	32628: "PCS_WGS84_UTM_zone_28N",
    	32629: "PCS_WGS84_UTM_zone_29N",
    	32630: "PCS_WGS84_UTM_zone_30N",
    	32631: "PCS_WGS84_UTM_zone_31N",
    	32632: "PCS_WGS84_UTM_zone_32N",
    	32633: "PCS_WGS84_UTM_zone_33N",
    	32634: "PCS_WGS84_UTM_zone_34N",
    	32635: "PCS_WGS84_UTM_zone_35N",
    	32636: "PCS_WGS84_UTM_zone_36N",
    	32637: "PCS_WGS84_UTM_zone_37N",
    	32638: "PCS_WGS84_UTM_zone_38N",
    	32639: "PCS_WGS84_UTM_zone_39N",
    	32640: "PCS_WGS84_UTM_zone_40N",
    	32641: "PCS_WGS84_UTM_zone_41N",
    	32642: "PCS_WGS84_UTM_zone_42N",
    	32643: "PCS_WGS84_UTM_zone_43N",
    	32644: "PCS_WGS84_UTM_zone_44N",
    	32645: "PCS_WGS84_UTM_zone_45N",
    	32646: "PCS_WGS84_UTM_zone_46N",
    	32647: "PCS_WGS84_UTM_zone_47N",
    	32648: "PCS_WGS84_UTM_zone_48N",
    	32649: "PCS_WGS84_UTM_zone_49N",
    	32650: "PCS_WGS84_UTM_zone_50N",
    	32651: "PCS_WGS84_UTM_zone_51N",
    	32652: "PCS_WGS84_UTM_zone_52N",
    	32653: "PCS_WGS84_UTM_zone_53N",
    	32654: "PCS_WGS84_UTM_zone_54N",
    	32655: "PCS_WGS84_UTM_zone_55N",
    	32656: "PCS_WGS84_UTM_zone_56N",
    	32657: "PCS_WGS84_UTM_zone_57N",
    	32658: "PCS_WGS84_UTM_zone_58N",
    	32659: "PCS_WGS84_UTM_zone_59N",
    	32660: "PCS_WGS84_UTM_zone_60N",
    	32701: "PCS_WGS84_UTM_zone_1S",
    	32702: "PCS_WGS84_UTM_zone_2S",
    	32703: "PCS_WGS84_UTM_zone_3S",
    	32704: "PCS_WGS84_UTM_zone_4S",
    	32705: "PCS_WGS84_UTM_zone_5S",
    	32706: "PCS_WGS84_UTM_zone_6S",
    	32707: "PCS_WGS84_UTM_zone_7S",
    	32708: "PCS_WGS84_UTM_zone_8S",
    	32709: "PCS_WGS84_UTM_zone_9S",
    	32710: "PCS_WGS84_UTM_zone_10S",
    	32711: "PCS_WGS84_UTM_zone_11S",
    	32712: "PCS_WGS84_UTM_zone_12S",
    	32713: "PCS_WGS84_UTM_zone_13S",
    	32714: "PCS_WGS84_UTM_zone_14S",
    	32715: "PCS_WGS84_UTM_zone_15S",
    	32716: "PCS_WGS84_UTM_zone_16S",
    	32717: "PCS_WGS84_UTM_zone_17S",
    	32718: "PCS_WGS84_UTM_zone_18S",
    	32719: "PCS_WGS84_UTM_zone_19S",
    	32720: "PCS_WGS84_UTM_zone_20S",
    	32721: "PCS_WGS84_UTM_zone_21S",
    	32722: "PCS_WGS84_UTM_zone_22S",
    	32723: "PCS_WGS84_UTM_zone_23S",
    	32724: "PCS_WGS84_UTM_zone_24S",
    	32725: "PCS_WGS84_UTM_zone_25S",
    	32726: "PCS_WGS84_UTM_zone_26S",
    	32727: "PCS_WGS84_UTM_zone_27S",
    	32728: "PCS_WGS84_UTM_zone_28S",
    	32729: "PCS_WGS84_UTM_zone_29S",
    	32730: "PCS_WGS84_UTM_zone_30S",
    	32731: "PCS_WGS84_UTM_zone_31S",
    	32732: "PCS_WGS84_UTM_zone_32S",
    	32733: "PCS_WGS84_UTM_zone_33S",
    	32734: "PCS_WGS84_UTM_zone_34S",
    	32735: "PCS_WGS84_UTM_zone_35S",
    	32736: "PCS_WGS84_UTM_zone_36S",
    	32737: "PCS_WGS84_UTM_zone_37S",
    	32738: "PCS_WGS84_UTM_zone_38S",
    	32739: "PCS_WGS84_UTM_zone_39S",
    	32740: "PCS_WGS84_UTM_zone_40S",
    	32741: "PCS_WGS84_UTM_zone_41S",
    	32742: "PCS_WGS84_UTM_zone_42S",
    	32743: "PCS_WGS84_UTM_zone_43S",
    	32744: "PCS_WGS84_UTM_zone_44S",
    	32745: "PCS_WGS84_UTM_zone_45S",
    	32746: "PCS_WGS84_UTM_zone_46S",
    	32747: "PCS_WGS84_UTM_zone_47S",
    	32748: "PCS_WGS84_UTM_zone_48S",
    	32749: "PCS_WGS84_UTM_zone_49S",
    	32750: "PCS_WGS84_UTM_zone_50S",
    	32751: "PCS_WGS84_UTM_zone_51S",
    	32752: "PCS_WGS84_UTM_zone_52S",
    	32753: "PCS_WGS84_UTM_zone_53S",
    	32754: "PCS_WGS84_UTM_zone_54S",
    	32755: "PCS_WGS84_UTM_zone_55S",
    	32756: "PCS_WGS84_UTM_zone_56S",
    	32757: "PCS_WGS84_UTM_zone_57S",
    	32758: "PCS_WGS84_UTM_zone_58S",
    	32759: "PCS_WGS84_UTM_zone_59S",
    	32760: "PCS_WGS84_UTM_zone_60S",
    	32767: "User-defined",
     }

    ProjCoordTransGeoKey = {
    	10101: "Proj_Alabama_CS27_East",
    	10102: "Proj_Alabama_CS27_West",
    	10131: "Proj_Alabama_CS83_East",
    	10132: "Proj_Alabama_CS83_West",
    	10201: "Proj_Arizona_Coordinate_System_east",
    	10202: "Proj_Arizona_Coordinate_System_Central",
    	10203: "Proj_Arizona_Coordinate_System_west",
    	10231: "Proj_Arizona_CS83_east",
    	10232: "Proj_Arizona_CS83_Central",
    	10233: "Proj_Arizona_CS83_west",
    	10301: "Proj_Arkansas_CS27_North",
    	10302: "Proj_Arkansas_CS27_South",
    	10331: "Proj_Arkansas_CS83_North",
    	10332: "Proj_Arkansas_CS83_South",
    	10401: "Proj_California_CS27_I",
    	10402: "Proj_California_CS27_II",
    	10403: "Proj_California_CS27_III",
    	10404: "Proj_California_CS27_IV",
    	10405: "Proj_California_CS27_V",
    	10406: "Proj_California_CS27_VI",
    	10407: "Proj_California_CS27_VII",
    	10431: "Proj_California_CS83_1",
    	10432: "Proj_California_CS83_2",
    	10433: "Proj_California_CS83_3",
    	10434: "Proj_California_CS83_4",
    	10435: "Proj_California_CS83_5",
    	10436: "Proj_California_CS83_6",
    	10501: "Proj_Colorado_CS27_North",
    	10502: "Proj_Colorado_CS27_Central",
    	10503: "Proj_Colorado_CS27_South",
    	10531: "Proj_Colorado_CS83_North",
    	10532: "Proj_Colorado_CS83_Central",
    	10533: "Proj_Colorado_CS83_South",
    	10600: "Proj_Connecticut_CS27",
    	10630: "Proj_Connecticut_CS83",
    	10700: "Proj_Delaware_CS27",
    	10730: "Proj_Delaware_CS83",
    	10901: "Proj_Florida_CS27_East",
    	10902: "Proj_Florida_CS27_West",
    	10903: "Proj_Florida_CS27_North",
    	10931: "Proj_Florida_CS83_East",
    	10932: "Proj_Florida_CS83_West",
    	10933: "Proj_Florida_CS83_North",
    	11001: "Proj_Georgia_CS27_East",
    	11002: "Proj_Georgia_CS27_West",
    	11031: "Proj_Georgia_CS83_East",
    	11032: "Proj_Georgia_CS83_West",
    	11101: "Proj_Idaho_CS27_East",
    	11102: "Proj_Idaho_CS27_Central",
    	11103: "Proj_Idaho_CS27_West",
    	11131: "Proj_Idaho_CS83_East",
    	11132: "Proj_Idaho_CS83_Central",
    	11133: "Proj_Idaho_CS83_West",
    	11201: "Proj_Illinois_CS27_East",
    	11202: "Proj_Illinois_CS27_West",
    	11231: "Proj_Illinois_CS83_East",
    	11232: "Proj_Illinois_CS83_West",
    	11301: "Proj_Indiana_CS27_East",
    	11302: "Proj_Indiana_CS27_West",
    	11331: "Proj_Indiana_CS83_East",
    	11332: "Proj_Indiana_CS83_West",
    	11401: "Proj_Iowa_CS27_North",
    	11402: "Proj_Iowa_CS27_South",
    	11431: "Proj_Iowa_CS83_North",
    	11432: "Proj_Iowa_CS83_South",
    	11501: "Proj_Kansas_CS27_North",
    	11502: "Proj_Kansas_CS27_South",
    	11531: "Proj_Kansas_CS83_North",
    	11532: "Proj_Kansas_CS83_South",
    	11601: "Proj_Kentucky_CS27_North",
    	11602: "Proj_Kentucky_CS27_South",
    	11631: "Proj_Kentucky_CS83_North",
    	11632: "Proj_Kentucky_CS83_South",
    	11701: "Proj_Louisiana_CS27_North",
    	11702: "Proj_Louisiana_CS27_South",
    	11731: "Proj_Louisiana_CS83_North",
    	11732: "Proj_Louisiana_CS83_South",
    	11801: "Proj_Maine_CS27_East",
    	11802: "Proj_Maine_CS27_West",
    	11831: "Proj_Maine_CS83_East",
    	11832: "Proj_Maine_CS83_West",
    	11900: "Proj_Maryland_CS27",
    	11930: "Proj_Maryland_CS83",
    	12001: "Proj_Massachusetts_CS27_Mainland",
    	12002: "Proj_Massachusetts_CS27_Island",
    	12031: "Proj_Massachusetts_CS83_Mainland",
    	12032: "Proj_Massachusetts_CS83_Island",
    	12101: "Proj_Michigan_State_Plane_East",
    	12102: "Proj_Michigan_State_Plane_Old_Central",
    	12103: "Proj_Michigan_State_Plane_West",
    	12111: "Proj_Michigan_CS27_North",
    	12112: "Proj_Michigan_CS27_Central",
    	12113: "Proj_Michigan_CS27_South",
    	12141: "Proj_Michigan_CS83_North",
    	12142: "Proj_Michigan_CS83_Central",
    	12143: "Proj_Michigan_CS83_South",
    	12201: "Proj_Minnesota_CS27_North",
    	12202: "Proj_Minnesota_CS27_Central",
    	12203: "Proj_Minnesota_CS27_South",
    	12231: "Proj_Minnesota_CS83_North",
    	12232: "Proj_Minnesota_CS83_Central",
    	12233: "Proj_Minnesota_CS83_South",
    	12301: "Proj_Mississippi_CS27_East",
    	12302: "Proj_Mississippi_CS27_West",
    	12331: "Proj_Mississippi_CS83_East",
    	12332: "Proj_Mississippi_CS83_West",
    	12401: "Proj_Missouri_CS27_East",
    	12402: "Proj_Missouri_CS27_Central",
    	12403: "Proj_Missouri_CS27_West",
    	12431: "Proj_Missouri_CS83_East",
    	12432: "Proj_Missouri_CS83_Central",
    	12433: "Proj_Missouri_CS83_West",
    	12501: "Proj_Montana_CS27_North",
    	12502: "Proj_Montana_CS27_Central",
    	12503: "Proj_Montana_CS27_South",
    	12530: "Proj_Montana_CS83",
    	12601: "Proj_Nebraska_CS27_North",
    	12602: "Proj_Nebraska_CS27_South",
    	12630: "Proj_Nebraska_CS83",
    	12701: "Proj_Nevada_CS27_East",
    	12702: "Proj_Nevada_CS27_Central",
    	12703: "Proj_Nevada_CS27_West",
    	12731: "Proj_Nevada_CS83_East",
    	12732: "Proj_Nevada_CS83_Central",
    	12733: "Proj_Nevada_CS83_West",
    	12800: "Proj_New_Hampshire_CS27",
    	12830: "Proj_New_Hampshire_CS83",
    	12900: "Proj_New_Jersey_CS27",
    	12930: "Proj_New_Jersey_CS83",
    	13001: "Proj_New_Mexico_CS27_East",
    	13002: "Proj_New_Mexico_CS27_Central",
    	13003: "Proj_New_Mexico_CS27_West",
    	13031: "Proj_New_Mexico_CS83_East",
    	13032: "Proj_New_Mexico_CS83_Central",
    	13033: "Proj_New_Mexico_CS83_West",
    	13101: "Proj_New_York_CS27_East",
    	13102: "Proj_New_York_CS27_Central",
    	13103: "Proj_New_York_CS27_West",
    	13104: "Proj_New_York_CS27_Long_Island",
    	13131: "Proj_New_York_CS83_East",
    	13132: "Proj_New_York_CS83_Central",
    	13133: "Proj_New_York_CS83_West",
    	13134: "Proj_New_York_CS83_Long_Island",
    	13200: "Proj_North_Carolina_CS27",
    	13230: "Proj_North_Carolina_CS83",
    	13301: "Proj_North_Dakota_CS27_North",
    	13302: "Proj_North_Dakota_CS27_South",
    	13331: "Proj_North_Dakota_CS83_North",
    	13332: "Proj_North_Dakota_CS83_South",
    	13401: "Proj_Ohio_CS27_North",
    	13402: "Proj_Ohio_CS27_South",
    	13431: "Proj_Ohio_CS83_North",
    	13432: "Proj_Ohio_CS83_South",
    	13501: "Proj_Oklahoma_CS27_North",
    	13502: "Proj_Oklahoma_CS27_South",
    	13531: "Proj_Oklahoma_CS83_North",
    	13532: "Proj_Oklahoma_CS83_South",
    	13601: "Proj_Oregon_CS27_North",
    	13602: "Proj_Oregon_CS27_South",
    	13631: "Proj_Oregon_CS83_North",
    	13632: "Proj_Oregon_CS83_South",
    	13701: "Proj_Pennsylvania_CS27_North",
    	13702: "Proj_Pennsylvania_CS27_South",
    	13731: "Proj_Pennsylvania_CS83_North",
    	13732: "Proj_Pennsylvania_CS83_South",
    	13800: "Proj_Rhode_Island_CS27",
    	13830: "Proj_Rhode_Island_CS83",
    	13901: "Proj_South_Carolina_CS27_North",
    	13902: "Proj_South_Carolina_CS27_South",
    	13930: "Proj_South_Carolina_CS83",
    	14001: "Proj_South_Dakota_CS27_North",
    	14002: "Proj_South_Dakota_CS27_South",
    	14031: "Proj_South_Dakota_CS83_North",
    	14032: "Proj_South_Dakota_CS83_South",
    	14100: "Proj_Tennessee_CS27",
    	14130: "Proj_Tennessee_CS83",
    	14201: "Proj_Texas_CS27_North",
    	14202: "Proj_Texas_CS27_North_Central",
    	14203: "Proj_Texas_CS27_Central",
    	14204: "Proj_Texas_CS27_South_Central",
    	14205: "Proj_Texas_CS27_South",
    	14231: "Proj_Texas_CS83_North",
    	14232: "Proj_Texas_CS83_North_Central",
    	14233: "Proj_Texas_CS83_Central",
    	14234: "Proj_Texas_CS83_South_Central",
    	14235: "Proj_Texas_CS83_South",
    	14301: "Proj_Utah_CS27_North",
    	14302: "Proj_Utah_CS27_Central",
    	14303: "Proj_Utah_CS27_South",
    	14331: "Proj_Utah_CS83_North",
    	14332: "Proj_Utah_CS83_Central",
    	14333: "Proj_Utah_CS83_South",
    	14400: "Proj_Vermont_CS27",
    	14430: "Proj_Vermont_CS83",
    	14501: "Proj_Virginia_CS27_North",
    	14502: "Proj_Virginia_CS27_South",
    	14531: "Proj_Virginia_CS83_North",
    	14532: "Proj_Virginia_CS83_South",
    	14601: "Proj_Washington_CS27_North",
    	14602: "Proj_Washington_CS27_South",
    	14631: "Proj_Washington_CS83_North",
    	14632: "Proj_Washington_CS83_South",
    	14701: "Proj_West_Virginia_CS27_North",
    	14702: "Proj_West_Virginia_CS27_South",
    	14731: "Proj_West_Virginia_CS83_North",
    	14732: "Proj_West_Virginia_CS83_South",
    	14801: "Proj_Wisconsin_CS27_North",
    	14802: "Proj_Wisconsin_CS27_Central",
    	14803: "Proj_Wisconsin_CS27_South",
    	14831: "Proj_Wisconsin_CS83_North",
    	14832: "Proj_Wisconsin_CS83_Central",
    	14833: "Proj_Wisconsin_CS83_South",
    	14901: "Proj_Wyoming_CS27_East",
    	14902: "Proj_Wyoming_CS27_East_Central",
    	14903: "Proj_Wyoming_CS27_West_Central",
    	14904: "Proj_Wyoming_CS27_West",
    	14931: "Proj_Wyoming_CS83_East",
    	14932: "Proj_Wyoming_CS83_East_Central",
    	14933: "Proj_Wyoming_CS83_West_Central",
    	14934: "Proj_Wyoming_CS83_West",
    	15001: "Proj_Alaska_CS27_1",
    	15002: "Proj_Alaska_CS27_2",
    	15003: "Proj_Alaska_CS27_3",
    	15004: "Proj_Alaska_CS27_4",
    	15005: "Proj_Alaska_CS27_5",
    	15006: "Proj_Alaska_CS27_6",
    	15007: "Proj_Alaska_CS27_7",
    	15008: "Proj_Alaska_CS27_8",
    	15009: "Proj_Alaska_CS27_9",
    	15010: "Proj_Alaska_CS27_10",
    	15031: "Proj_Alaska_CS83_1",
    	15032: "Proj_Alaska_CS83_2",
    	15033: "Proj_Alaska_CS83_3",
    	15034: "Proj_Alaska_CS83_4",
    	15035: "Proj_Alaska_CS83_5",
    	15036: "Proj_Alaska_CS83_6",
    	15037: "Proj_Alaska_CS83_7",
    	15038: "Proj_Alaska_CS83_8",
    	15039: "Proj_Alaska_CS83_9",
    	15040: "Proj_Alaska_CS83_10",
    	15101: "Proj_Hawaii_CS27_1",
    	15102: "Proj_Hawaii_CS27_2",
    	15103: "Proj_Hawaii_CS27_3",
    	15104: "Proj_Hawaii_CS27_4",
    	15105: "Proj_Hawaii_CS27_5",
    	15131: "Proj_Hawaii_CS83_1",
    	15132: "Proj_Hawaii_CS83_2",
    	15133: "Proj_Hawaii_CS83_3",
    	15134: "Proj_Hawaii_CS83_4",
    	15135: "Proj_Hawaii_CS83_5",
    	15201: "Proj_Puerto_Rico_CS27",
    	15202: "Proj_St_Croix",
    	15230: "Proj_Puerto_Rico_Virgin_Is",
    	15914: "Proj_BLM_14N_feet",
    	15915: "Proj_BLM_15N_feet",
    	15916: "Proj_BLM_16N_feet",
    	15917: "Proj_BLM_17N_feet",
    	17348: "Proj_Map_Grid_of_Australia_48",
    	17349: "Proj_Map_Grid_of_Australia_49",
    	17350: "Proj_Map_Grid_of_Australia_50",
    	17351: "Proj_Map_Grid_of_Australia_51",
    	17352: "Proj_Map_Grid_of_Australia_52",
    	17353: "Proj_Map_Grid_of_Australia_53",
    	17354: "Proj_Map_Grid_of_Australia_54",
    	17355: "Proj_Map_Grid_of_Australia_55",
    	17356: "Proj_Map_Grid_of_Australia_56",
    	17357: "Proj_Map_Grid_of_Australia_57",
    	17358: "Proj_Map_Grid_of_Australia_58",
    	17448: "Proj_Australian_Map_Grid_48",
    	17449: "Proj_Australian_Map_Grid_49",
    	17450: "Proj_Australian_Map_Grid_50",
    	17451: "Proj_Australian_Map_Grid_51",
    	17452: "Proj_Australian_Map_Grid_52",
    	17453: "Proj_Australian_Map_Grid_53",
    	17454: "Proj_Australian_Map_Grid_54",
    	17455: "Proj_Australian_Map_Grid_55",
    	17456: "Proj_Australian_Map_Grid_56",
    	17457: "Proj_Australian_Map_Grid_57",
    	17458: "Proj_Australian_Map_Grid_58",
    	18031: "Proj_Argentina_1",
    	18032: "Proj_Argentina_2",
    	18033: "Proj_Argentina_3",
    	18034: "Proj_Argentina_4",
    	18035: "Proj_Argentina_5",
    	18036: "Proj_Argentina_6",
    	18037: "Proj_Argentina_7",
    	18051: "Proj_Colombia_3W",
    	18052: "Proj_Colombia_Bogota",
    	18053: "Proj_Colombia_3E",
    	18054: "Proj_Colombia_6E",
    	18072: "Proj_Egypt_Red_Belt",
    	18073: "Proj_Egypt_Purple_Belt",
    	18074: "Proj_Extended_Purple_Belt",
    	18141: "Proj_New_Zealand_North_Island_Nat_Grid",
    	18142: "Proj_New_Zealand_South_Island_Nat_Grid",
    	19900: "Proj_Bahrain_Grid",
    	19905: "Proj_Netherlands_E_Indies_Equatorial",
    	19912: "Proj_RSO_Borneo",
    	32767: "User-defined"
    }

    ProjCoordTransGeoKey = {
    	1:  "CT_TransverseMercator",
    	2:  "CT_TransvMercator_Modified_Alaska",
    	3:  "CT_ObliqueMercator",
    	4:  "CT_ObliqueMercator_Laborde",
    	5:  "CT_ObliqueMercator_Rosenmund",
    	6:  "CT_ObliqueMercator_Spherical",
    	7:  "CT_Mercator",
    	8:  "CT_LambertConfConic_2SP",
    	9:  "CT_LambertConfConic_Helmert",
    	10: "CT_LambertAzimEqualArea",
    	11: "CT_AlbersEqualArea",
    	12: "CT_AzimuthalEquidistant",
    	13: "CT_EquidistantConic",
    	14: "CT_Stereographic",
    	15: "CT_PolarStereographic",
    	16: "CT_ObliqueStereographic",
    	17: "CT_Equirectangular",
    	18: "CT_CassiniSoldner",
    	19: "CT_Gnomonic",
    	20: "CT_MillerCylindrical",
    	21: "CT_Orthographic",
    	22: "CT_Polyconic",
    	23: "CT_Robinson",
    	24: "CT_Sinusoidal",
    	25: "CT_VanDerGrinten",
    	26: "CT_NewZealandMapGrid",
    	27: "CT_TransvMercator_SouthOriented",
    	28: "User-defined",
    	32767: "User-defined"
    }

    ProjLinearUnitsGeoKey = GeogLinearUnitsGeoKey

    VerticalCSTypeGeoKey = {
    	5001: "VertCS_Airy_1830_ellipsoid",
    	5002: "VertCS_Airy_Modified_1849_ellipsoid",
    	5003: "VertCS_ANS_ellipsoid",
    	5004: "VertCS_Bessel_1841_ellipsoid",
    	5005: "VertCS_Bessel_Modified_ellipsoid",
    	5006: "VertCS_Bessel_Namibia_ellipsoid",
    	5007: "VertCS_Clarke_1858_ellipsoid",
    	5008: "VertCS_Clarke_1866_ellipsoid",
    	5010: "VertCS_Clarke_1880_Benoit_ellipsoid",
    	5011: "VertCS_Clarke_1880_IGN_ellipsoid",
    	5012: "VertCS_Clarke_1880_RGS_ellipsoid",
    	5013: "VertCS_Clarke_1880_Arc_ellipsoid",
    	5014: "VertCS_Clarke_1880_SGA_1922_ellipsoid",
    	5015: "VertCS_Everest_1830_1937_Adjustment_ellipsoid",
    	5016: "VertCS_Everest_1830_1967_Definition_ellipsoid",
    	5017: "VertCS_Everest_1830_1975_Definition_ellipsoid",
    	5018: "VertCS_Everest_1830_Modified_ellipsoid",
    	5019: "VertCS_GRS_1980_ellipsoid",
    	5020: "VertCS_Helmert_1906_ellipsoid",
    	5021: "VertCS_INS_ellipsoid",
    	5022: "VertCS_International_1924_ellipsoid",
    	5023: "VertCS_International_1967_ellipsoid",
    	5024: "VertCS_Krassowsky_1940_ellipsoid",
    	5025: "VertCS_NWL_9D_ellipsoid",
    	5026: "VertCS_NWL_10D_ellipsoid",
    	5027: "VertCS_Plessis_1817_ellipsoid",
    	5028: "VertCS_Struve_1860_ellipsoid",
    	5029: "VertCS_War_Office_ellipsoid",
    	5030: "VertCS_WGS_84_ellipsoid",
    	5031: "VertCS_GEM_10C_ellipsoid",
    	5032: "VertCS_OSU86F_ellipsoid",
    	5033: "VertCS_OSU91A_ellipsoid",
    	5101: "VertCS_Newlyn",
    	5102: "VertCS_North_American_Vertical_Datum_1929",
    	5103: "VertCS_North_American_Vertical_Datum_1988",
    	5104: "VertCS_Yellow_Sea_1956",
    	5105: "VertCS_Baltic_Sea",
    	5106: "VertCS_Caspian_Sea",
    	32767: "User-defined"
    }

    VerticalUnitsGeoKey = GeogLinearUnitsGeoKey


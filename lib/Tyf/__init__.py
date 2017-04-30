# -*- encoding:utf-8 -*-
__copyright__ = "Copyright © 2012-2015, THOORENS Bruno - http://bruno.thoorens.free.fr/licences/tyf.html"
__author__    = "THOORENS Bruno"
__tiff__      = (6, 0)
__geotiff__   = (1, 8, 1)

import io, os, sys, struct, operator, collections

__PY3__ = True if sys.version_info[0] >= 3 else False

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
if __PY3__:
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

from . import ifd, gkd, tags


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
		tt = ifd.TiffTag(tag, typ, name=obj.tagname)
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
				tt.value = struct.unpack(fmt, data[:count*struct.calcsize("="+_typ)])

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
			obj.sub_ifd[key] = ifd.Ifd(tagname=value)
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
			if __PY3__ and t.type in [2, 7]:
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
	step1 = struct.calcsize("=HHLL")
	step2 = struct.calcsize("=HHL")

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
			if __PY3__ and t.type in [2, 7]:
				fmt = str(t.count)+TYPES[t.type][0]
				value = (t.value,)
			else:
				fmt = t.count*TYPES[t.type][0]
				value = t.value
			# write value
			# print(">>>", fmt, value)
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

	gkd = property(lambda obj: [gkd.Gkd(ifd) for ifd in obj], None, None, "list of geotiff directory")
	has_raster = property(lambda obj: reduce(operator.__or__, [ifd.has_raster for ifd in obj]), None, None, "")
	raster_loaded = property(lambda obj: reduce(operator.__and__, [ifd.raster_loaded for ifd in obj]), None, None, "")

	def __init__(self, fileobj):
		# Initialize a TiffFile object from buffer fileobj, fileobj have to be in 'wb' mode

		# determine byteorder
		first, = unpack(">H", fileobj)
		byteorder = "<" if first == 0x4949 else ">"

		magic_number, = unpack(byteorder+"H", fileobj)
		if magic_number not in [0x732E,0x2A]: #29486, 42
			fileobj.close()
			if magic_number == 0x2B: # 43
				raise IOError("BigTIFF file not supported")
			else:
				raise IOError("Bad magic number. Not a valid TIFF file")
		next_ifd, = unpack(byteorder+"L", fileobj)

		ifds = []
		while next_ifd != 0:
			i = ifd.Ifd(sub_ifd={
				34665:[tags.exfT,"Exif tag"],
				34853:[tags.gpsT,"GPS tag"]
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
		elif isinstance(value, ifd.Ifd):
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


class JpegFile(collections.OrderedDict):

	jfif = property(lambda obj: collections.OrderedDict.__getitem__(obj, 0xffe0), None, None, "JFIF data")
	exif = property(lambda obj: collections.OrderedDict.__getitem__(obj, 0xffe1)[0], None, None, "Image IFD")
	ifd1 = property(lambda obj: collections.OrderedDict.__getitem__(obj, 0xffe1)[1], None, None, "Thumbnail IFD")

	def __init__(self, fileobj):
		markers = collections.OrderedDict()
		marker, = unpack(">H", fileobj)
		if marker != 0xffd8: raise Exception("not a valid jpeg file")
		while marker != 0xffd9: # EOI (End Of Image) Marker
			marker, count = unpack(">HH", fileobj)
			# here is raster data marker, copy all after marker id
			if marker == 0xffda:
				fileobj.seek(-2, 1)
				markers[0xffda] = fileobj.read()[:-2]
				# say it is the end of the file
				marker = 0xffd9
			elif marker == 0xffe1:
				string = StringIO(fileobj.read(count-2)[6:])
				try: markers[marker] = TiffFile(string)
				except: setattr(markers, "_0xffe1", string.getvalue())
				string.close()
			else:
				markers[marker] = fileobj.read(count-2)

		collections.OrderedDict.__init__(self, markers)

	def __getitem__(self, item):
		try: return collections.OrderedDict.__getitem__(self, 0xffe1)[0,item]
		except KeyError: return collections.OrderedDict.__getitem__(self, item)

	def _pack(self, marker, fileobj):
		data = self[marker]
		if marker == 0xffda:
			pack(">H", fileobj, (marker,))
		elif marker == 0xffe1:
			string = StringIO()
			self[marker].save(string)
			data = b"Exif\x00\x00" + string.getvalue()
			pack(">HH", fileobj, (marker, len(data) + 2))
			string.close()
		else:
			pack(">HH", fileobj, (marker, len(data) + 2))
		fileobj.write(data)

	def save(self, f):
		fileobj, _close = _fileobj(f, "wb")

		pack(">H", fileobj, (0xffd8,))
		for key in self: self._pack(key, fileobj)
		pack(">H", fileobj, (0xffd9,))

		if _close: fileobj.close()

	def save_thumbnail(self, f):
		try:
			ifd = self.ifd1
		except IndexError:
			pass
		else:
			compression = ifd[259]
			if hasattr(f, "close"):
				fileobj = f
				_close = False
			else:
				fileobj = io.open(os.path.splitext(f)[0] + (".jpg" if compression == 6 else ".tif"), "wb")
				_close = True

			if compression == 6:
				fileobj.write(ifd.jpegIF)
			elif compression == 1:
				self[0xffe1].save(fileobj, idx=1)

			if _close: fileobj.close()

	def dump_exif(self, f):
		fileobj, _close = _fileobj(f, "wb")
		self[0xffe1].save(fileobj)
		if _close: fileobj.close()

	def load_exif(self, f):
		fileobj, _close = _fileobj(f, "rb")
		self[0xffe1] = TiffFile(fileobj)
		self[0xffe1].load_raster()
		if _close: fileobj.close()

	def strip_exif(self):
		for key in [k for k in self.exif.sub_ifd if k in self.exif]:
			self.exif.pop(key)
		self.exif.sub_ifd = {}
		for key in list(k for k in self.exif if k not in tags.bTT):
			self.exif.pop(key)
		while len(self[0xffe1]) > 1:
			self[0xffe1].pop(-1)


def jpeg_extract(f):
	fileobj, _close = _fileobj(f, "rb")

	ifd = False
	marker, = unpack(">H", fileobj)
	if marker != 0xffd8: raise Exception("not a valid jpeg file")
	while marker != 0xffd9:
		marker, count = unpack(">HH", fileobj)
		if marker == 0xffe1:
			string = StringIO(fileobj.read(count-2)[6:])
			ifd = TiffFile(string)
			string.close()
			marker = 0xffd9
		else:
			fileobj.read(count-2)

	if _close: fileobj.close()
	return ifd

def open(f):
	fileobj, _close = _fileobj(f, "rb")
		
	first, = unpack(">H", fileobj)
	fileobj.seek(0)

	if first == 0xffd8: obj = JpegFile(fileobj)
	elif first in [0x4d4d, 0x4949]: obj = TiffFile(fileobj)

	if _close: fileobj.close()
	try: return obj
	except: raise Exception("file is not a valid JPEG nor TIFF image")


